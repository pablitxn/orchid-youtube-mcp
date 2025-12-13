"""Video query service for semantic search and RAG."""

import asyncio
import base64
import time
from typing import Any

from src.application.dtos.query import (
    CitationDTO,
    CrossVideoRequest,
    CrossVideoResponse,
    DecompositionInfo,
    GetSourcesRequest,
    QueryMetadata,
    QueryModality,
    QueryVideoRequest,
    QueryVideoResponse,
    RefinementInfo,
    SourceArtifact,
    SourceDetail,
    SourcesResponse,
    SubTaskInfo,
    TimestampRangeDTO,
    ToolCall,
    VideoResult,
)
from src.application.services.agentic_query import (
    CrossVideoSearcher,
    QueryRefiner,
    RefinementStrategy,
    ToolExecutor,
    get_tools_prompt,
)
from src.application.services.multimodal_message import MultimodalMessageBuilder
from src.application.services.query_decomposer import (
    QueryDecomposer,
    ResultSynthesizer,
    SubTask,
    SubTaskResult,
)
from src.commons.infrastructure.blob.base import BlobStorageBase
from src.commons.infrastructure.documentdb.base import DocumentDBBase
from src.commons.infrastructure.vectordb.base import VectorDBBase
from src.commons.model_capabilities import ContentType
from src.commons.settings.models import FrameEmbeddingStrategy, Settings
from src.commons.telemetry import LogContext, get_logger
from src.domain.models.chunk import Modality
from src.infrastructure.embeddings.base import EmbeddingServiceBase
from src.infrastructure.llm.base import LLMServiceBase, Message, MessageRole


class VideoQueryService:
    """Service for querying video content using semantic search and LLM.

    Performs vector search across video chunks and uses LLM to generate
    answers with citations to source material.
    """

    def __init__(
        self,
        text_embedding_service: EmbeddingServiceBase,
        llm_service: LLMServiceBase,
        vector_db: VectorDBBase,
        document_db: DocumentDBBase,
        settings: Settings,
        blob_storage: BlobStorageBase | None = None,
    ) -> None:
        """Initialize query service.

        Args:
            text_embedding_service: Service for generating query embeddings.
            llm_service: LLM for generating answers.
            vector_db: Vector database for similarity search.
            document_db: Document database for metadata.
            settings: Application settings.
            blob_storage: Optional blob storage for presigned URLs.
        """
        self._embedder = text_embedding_service
        self._llm = llm_service
        self._vector_db = vector_db
        self._document_db = document_db
        self._settings = settings
        self._blob = blob_storage
        self._logger = get_logger(__name__)

        self._vectors_collection = settings.vector_db.collections.transcripts
        self._videos_collection = settings.document_db.collections.videos
        self._chunks_collection = settings.document_db.collections.transcript_chunks
        self._frames_collection = settings.document_db.collections.frame_chunks
        self._frames_bucket = settings.blob_storage.buckets.frames

        # Agentic components
        self._decomposer = QueryDecomposer(llm_service)
        self._synthesizer = ResultSynthesizer(llm_service)
        self._refiner = QueryRefiner(llm_service)
        self._cross_video = CrossVideoSearcher(llm_service)
        self._tool_executor = ToolExecutor(
            document_db=document_db,
            blob_storage=blob_storage,
            llm_service=llm_service,
            embedder=text_embedding_service,
            vector_db=vector_db,
        )

    async def query(  # noqa: PLR0912, PLR0915
        self,
        video_id: str,
        request: QueryVideoRequest,
    ) -> QueryVideoResponse:
        """Query a video's content with natural language.

        Args:
            video_id: ID of the video to query.
            request: Query request with question and options.

        Returns:
            Response with answer and citations.

        Raises:
            ValueError: If video not found or not ready.
        """
        # Use agentic decomposition if enabled
        if request.enable_decomposition:
            return await self.query_with_decomposition(video_id, request)

        # Check for visual query - route to visual_query if forced or auto-detected
        visual_settings = self._settings.query.visual
        is_visual = request.force_visual or (
            visual_settings.enabled and self._is_visual_query(request.query)
        )
        if is_visual:
            self._logger.info(
                "Visual query mode activated",
                extra={
                    "query": request.query[:50],
                    "forced": request.force_visual,
                    "auto_detected": not request.force_visual,
                },
            )
            return await self.visual_query(video_id, request)

        start_time = time.perf_counter()

        query_preview = (
            request.query[:100] + "..." if len(request.query) > 100 else request.query
        )
        self._logger.info(
            "Starting video query",
            extra={
                "video_id": video_id,
                "query": query_preview,
                "max_citations": request.max_citations,
                "similarity_threshold": request.similarity_threshold,
                "modalities": [m.value for m in request.modalities],
                "include_reasoning": request.include_reasoning,
                "enable_decomposition": request.enable_decomposition,
            },
        )

        # Use LogContext to add video_id to all subsequent logs
        with LogContext(video_id=video_id):
            # Verify video exists and is ready
            self._logger.debug(
                "Fetching video metadata from document DB",
                extra={"collection": self._videos_collection},
            )
            video = await self._document_db.find_by_id(
                self._videos_collection, video_id
            )

            if not video:
                self._logger.warning(
                    "Video not found in database",
                    extra={"video_id": video_id},
                )
                raise ValueError(f"Video not found: {video_id}")

            self._logger.debug(
                "Video found",
                extra={
                    "title": video.get("title"),
                    "status": video.get("status"),
                    "duration_seconds": video.get("duration_seconds"),
                    "transcript_chunk_count": video.get("transcript_chunk_count"),
                },
            )

            if video.get("status") != "ready":
                self._logger.warning(
                    "Video not ready for querying",
                    extra={
                        "video_id": video_id,
                        "current_status": video.get("status"),
                    },
                )
                raise ValueError(f"Video not ready for querying: {video.get('status')}")

            # Generate query embedding
            self._logger.debug(
                "Generating query embedding",
                extra={
                    "query_length": len(request.query),
                    "embedding_dimensions": self._embedder.text_dimensions,
                },
            )
            embed_start = time.perf_counter()
            query_embeddings = await self._embedder.embed_texts([request.query])
            embed_time_ms = int((time.perf_counter() - embed_start) * 1000)

            if not query_embeddings:
                self._logger.error("Failed to generate query embedding")
                raise ValueError("Failed to generate query embedding")

            query_vector = query_embeddings[0].vector
            self._logger.debug(
                "Query embedding generated",
                extra={
                    "vector_length": len(query_vector),
                    "embed_time_ms": embed_time_ms,
                },
            )

            # Search for relevant chunks
            strategy = self._settings.query.visual.frame_embedding_strategy
            self._logger.warning(
                f"=== QUERY SEARCH START === strategy={strategy.value}",
                extra={
                    "query": request.query[:100],
                    "video_id": video_id,
                },
            )

            self._logger.debug(
                "Searching vector database for relevant chunks",
                extra={
                    "collection": self._vectors_collection,
                    "limit": request.max_citations * 2,
                    "score_threshold": request.similarity_threshold,
                    "filter_video_id": video_id,
                    "frame_strategy": strategy.value,
                },
            )

            search_start = time.perf_counter()

            # Search transcripts
            transcript_results = await self._vector_db.search(
                collection=self._vectors_collection,
                query_vector=query_vector,
                limit=request.max_citations * 2,
                score_threshold=request.similarity_threshold,
                filters={"video_id": video_id},
            )
            self._logger.warning(
                f"Transcript search: {len(transcript_results)} results"
            )

            # Search frame descriptions if strategy uses them
            frame_results = []
            if strategy in (
                FrameEmbeddingStrategy.FRAME_DESCRIPTION_EMBEDDING,
                FrameEmbeddingStrategy.HYBRID,
            ):
                frames_collection = self._settings.vector_db.collections.frames
                try:
                    frame_results = await self._vector_db.search(
                        collection=frames_collection,
                        query_vector=query_vector,
                        limit=request.max_citations,
                        score_threshold=request.similarity_threshold,
                        filters={"video_id": video_id},
                    )
                    self._logger.warning(
                        f"Frame description search: {len(frame_results)} results "
                        f"(collection={frames_collection})"
                    )
                    for i, fr in enumerate(frame_results[:5]):
                        self._logger.warning(
                            f"  Frame result {i}: score={fr.score:.3f}, "
                            f"preview={fr.payload.get('text_preview', '')[:80]}..."
                        )
                except Exception as e:
                    self._logger.warning(
                        f"Frame search failed (collection may not exist): {e}"
                    )

            # Combine and sort by score
            search_results = transcript_results + frame_results
            search_results.sort(key=lambda x: x.score, reverse=True)

            search_time_ms = int((time.perf_counter() - search_start) * 1000)

            top_scores = [r.score for r in search_results[:5]] if search_results else []
            self._logger.warning(
                f"Combined search: {len(search_results)} total results",
                extra={
                    "transcript_results": len(transcript_results),
                    "frame_results": len(frame_results),
                    "search_time_ms": search_time_ms,
                    "top_scores": top_scores,
                },
            )

            # Build context from search results
            self._logger.debug("Building context from search results")
            context_chunks: list[dict[str, Any]] = []
            chunks_fetched = 0
            chunks_not_found = 0
            frames_fetched = 0

            for result in search_results:
                chunk_id = result.payload.get("chunk_id")
                modality = result.payload.get("modality", "transcript")

                if chunk_id:
                    # Determine which collection to search based on modality
                    if modality == Modality.FRAME.value:
                        chunk = await self._document_db.find_by_id(
                            self._frames_collection,
                            chunk_id,
                        )
                        if chunk:
                            frames_fetched += 1
                    else:
                        chunk = await self._document_db.find_by_id(
                            self._chunks_collection,
                            chunk_id,
                        )

                    if chunk:
                        context_chunks.append(
                            {
                                "chunk": chunk,
                                "score": result.score,
                                "payload": result.payload,
                                "modality": modality,
                            }
                        )
                        chunks_fetched += 1
                    else:
                        chunks_not_found += 1
                        self._logger.debug(
                            "Chunk not found in document DB",
                            extra={"chunk_id": chunk_id, "modality": modality},
                        )

            transcripts_count = chunks_fetched - frames_fetched
            self._logger.warning(
                f"Context built: {chunks_fetched} chunks "
                f"({frames_fetched} frames, {transcripts_count} transcripts)",
                extra={
                    "chunks_fetched": chunks_fetched,
                    "frames_fetched": frames_fetched,
                    "chunks_not_found": chunks_not_found,
                    "total_context_chunks": len(context_chunks),
                },
            )

            if not context_chunks:
                self._logger.warning(
                    "No relevant chunks found for query",
                    extra={
                        "search_results_count": len(search_results),
                        "similarity_threshold": request.similarity_threshold,
                    },
                )

            # Get enabled content types from request
            enabled_content_types = request.enabled_content_types.to_content_types()

            # Generate answer with LLM
            self._logger.debug(
                "Generating answer with LLM",
                extra={
                    "context_chunks_count": len(context_chunks),
                    "video_title": video.get("title", "Unknown"),
                    "include_reasoning": request.include_reasoning,
                    "enabled_content_types": [ct.value for ct in enabled_content_types],
                },
            )
            llm_start = time.perf_counter()
            (
                answer,
                reasoning,
                confidence,
                content_types_used,
            ) = await self._generate_answer(
                query=request.query,
                context_chunks=context_chunks,
                video_title=video.get("title", "Unknown"),
                include_reasoning=request.include_reasoning,
                enabled_content_types=enabled_content_types,
            )
            llm_time_ms = int((time.perf_counter() - llm_start) * 1000)

            self._logger.debug(
                "LLM answer generated",
                extra={
                    "answer_length": len(answer),
                    "has_reasoning": reasoning is not None,
                    "confidence": confidence,
                    "llm_time_ms": llm_time_ms,
                    "content_types_used": content_types_used,
                },
            )

            # Build citations
            self._logger.debug(
                "Building citations",
                extra={
                    "max_citations": request.max_citations,
                    "available_chunks": len(context_chunks),
                },
            )
            citations = self._build_citations(
                context_chunks=context_chunks[: request.max_citations],
                video=video,
            )

            self._logger.debug(
                "Citations built",
                extra={
                    "citation_count": len(citations),
                    "citation_ids": [c.id for c in citations],
                },
            )

            # Calculate processing time
            processing_time_ms = int((time.perf_counter() - start_time) * 1000)

            self._logger.info(
                "Query completed successfully",
                extra={
                    "total_time_ms": processing_time_ms,
                    "embed_time_ms": embed_time_ms,
                    "search_time_ms": search_time_ms,
                    "llm_time_ms": llm_time_ms,
                    "chunks_analyzed": len(context_chunks),
                    "citations_returned": len(citations),
                    "confidence": confidence,
                    "content_types_used": content_types_used,
                },
            )

            # Build response
            return QueryVideoResponse(
                answer=answer,
                reasoning=reasoning if request.include_reasoning else None,
                confidence=confidence,
                citations=citations,
                query_metadata=QueryMetadata(
                    video_id=video_id,
                    video_title=video.get("title", "Unknown"),
                    modalities_searched=[
                        QueryModality(m.value)
                        for m in self._map_modalities(request.modalities)
                    ],
                    chunks_analyzed=len(context_chunks),
                    processing_time_ms=processing_time_ms,
                    multimodal_content_used=content_types_used,
                ),
            )

    async def _generate_answer(  # noqa: PLR0912, PLR0915
        self,
        query: str,
        context_chunks: list[dict[str, Any]],
        video_title: str,
        include_reasoning: bool,
        enabled_content_types: set[ContentType] | None = None,
    ) -> tuple[str, str | None, float, list[str]]:
        """Generate answer using LLM with optional multimodal content.

        Args:
            query: User's question.
            context_chunks: Relevant chunks with scores.
            video_title: Title of the video.
            include_reasoning: Whether to include reasoning.
            enabled_content_types: Which content types to include in message.

        Returns:
            Tuple of (answer, reasoning, confidence, content_types_used).
        """
        content_types_used: list[str] = ["text"]

        if not context_chunks:
            self._logger.debug(
                "No context chunks provided, returning no-info response",
            )
            no_info_msg = (
                "I couldn't find relevant information in this video "
                "to answer your question."
            )
            return (
                no_info_msg,
                "No matching content found in the video transcripts or frames.",
                0.0,
                content_types_used,
            )

        # Determine content types to use
        enabled = enabled_content_types or {ContentType.TEXT}

        # Build multimodal message using builder
        model_id = self._llm.default_model
        builder = MultimodalMessageBuilder(
            model_id=model_id,
            enabled_modalities=enabled,
            blob_storage=self._blob,
        )

        self._logger.debug(
            "Building multimodal context",
            extra={
                "chunk_count": len(context_chunks),
                "enabled_modalities": [ct.value for ct in enabled],
                "model": model_id,
            },
        )

        # Add context header
        builder.add_text("Context from the video:\n")

        # Add context chunks
        for i, item in enumerate(context_chunks, 1):
            chunk_data = item["chunk"]
            score = item["score"]
            modality = item.get("modality", chunk_data.get("modality", "transcript"))

            chunk_start_time = chunk_data.get("start_time", 0)
            chunk_end_time = chunk_data.get("end_time", 0)
            start_fmt = self._format_timestamp(chunk_start_time)
            end_fmt = self._format_timestamp(chunk_end_time)

            # Handle different modalities
            if modality == Modality.FRAME.value:
                # Frame chunk - use description as text
                description = chunk_data.get("description", "")
                text = (
                    f"[FRAME] {description}"
                    if description
                    else "[FRAME - no description]"
                )

                self._logger.warning(
                    f"Adding frame context [{i}]: {text[:100]}...",
                    extra={
                        "frame_id": chunk_data.get("id"),
                        "frame_number": chunk_data.get("frame_number"),
                        "has_description": bool(description),
                        "score": score,
                    },
                )

                builder.add_text(
                    f"[{i}] ({start_fmt} - {end_fmt}) {text}",
                    metadata={
                        "chunk_id": chunk_data.get("id"),
                        "score": score,
                        "modality": "frame",
                    },
                )

                # Add the actual frame image if images enabled
                if ContentType.IMAGE in enabled and self._blob:
                    blob_path = chunk_data.get("blob_path")
                    if blob_path:
                        try:
                            # Use base64 for reliability
                            image_data = await self._get_image_as_base64(blob_path)
                            if image_data:
                                builder.add_image(
                                    image_data,
                                    metadata={
                                        "chunk_id": chunk_data.get("id"),
                                        "timestamp": chunk_start_time,
                                        "frame_number": chunk_data.get("frame_number"),
                                    },
                                )
                                if "image" not in content_types_used:
                                    content_types_used.append("image")
                                frame_num = chunk_data.get("frame_number")
                                self._logger.warning(
                                    f"  -> Added frame image for frame {frame_num}"
                                )
                        except Exception as e:
                            self._logger.warning(
                                f"Failed to add frame image: {e}",
                                extra={"blob_path": blob_path},
                            )
            else:
                # Transcript chunk
                text = chunk_data.get("text", "")

                builder.add_text(
                    f"[{i}] ({start_fmt} - {end_fmt}): {text}",
                    metadata={
                        "chunk_id": chunk_data.get("id"),
                        "score": score,
                        "modality": "transcript",
                    },
                )

                # Vision-augmented: add nearby frames for transcript chunks
                if ContentType.IMAGE in enabled and self._blob:
                    video_id = chunk_data.get("video_id")
                    if video_id:
                        vs = self._settings.query.visual
                        nearby_frames = await self._get_frames_near_timestamp(
                            video_id=video_id,
                            timestamp=chunk_start_time,
                            window_seconds=vs.frame_window_seconds,
                            max_frames=min(2, vs.max_frames_per_query),
                        )
                        for frame in nearby_frames:
                            blob_path = frame.get("blob_path")
                            if blob_path:
                                try:
                                    image_data = await self._get_image_as_base64(
                                        blob_path
                                    )
                                    if image_data:
                                        builder.add_image(
                                            image_data,
                                            metadata={
                                                "source": "nearby_frame",
                                                "transcript_chunk": chunk_data.get(
                                                    "id"
                                                ),
                                                "timestamp": frame.get("start_time"),
                                            },
                                        )
                                        if "image" not in content_types_used:
                                            content_types_used.append("image")
                                except Exception as e:
                                    self._logger.debug(
                                        "Failed to add nearby frame",
                                        extra={"error": str(e)},
                                    )

            self._logger.debug(
                f"Context chunk {i} added",
                extra={
                    "chunk_id": chunk_data.get("id"),
                    "start_time": chunk_start_time,
                    "modality": modality,
                    "text_length": len(text) if text else 0,
                    "score": score,
                },
            )

        # Add the question
        question_text = (
            f"\n\nQuestion: {query}\n\n"
            "Please provide a clear, concise answer based on the context above."
        )
        if include_reasoning:
            question_text += "\n\nAlso briefly explain your reasoning."

        builder.add_text(question_text)

        # Build the user message
        user_message = builder.build_as_llm_message()

        # System prompt
        system_prompt = (
            "You are an assistant that answers questions about video content.\n"
            f'You have been given excerpts from "{video_title}".\n'
            "Answer the question based ONLY on the provided context.\n"
            "If the context doesn't contain enough information, say so.\n"
            "Always cite the relevant timestamps in your answer."
        )

        if ContentType.IMAGE in enabled:
            system_prompt += "\nImages from the video are included for visual context."

        messages = [
            Message(role=MessageRole.SYSTEM, content=system_prompt),
            user_message,
        ]

        self._logger.debug(
            "Calling LLM service",
            extra={
                "temperature": 0.3,
                "max_tokens": 1024,
                "message_count": len(messages),
                "has_images": user_message.images is not None,
                "image_count": len(user_message.images) if user_message.images else 0,
            },
        )

        response = await self._llm.generate(
            messages=messages,
            temperature=0.3,
            max_tokens=1024,
        )

        self._logger.debug(
            "LLM response received",
            extra={
                "response_length": len(response.content),
                "model": getattr(response, "model", "unknown"),
            },
        )

        # Parse response
        content = response.content
        reasoning = None

        if include_reasoning and "reasoning:" in content.lower():
            parts = content.split("reasoning:", 1)
            if len(parts) == 2:
                content = parts[0].strip()
                reasoning = parts[1].strip()

        # Calculate confidence
        avg_score = sum(item["score"] for item in context_chunks) / len(context_chunks)
        confidence = min(avg_score, 0.95)

        self._logger.debug(
            "Answer generated",
            extra={
                "confidence": confidence,
                "content_types_used": content_types_used,
            },
        )

        return content, reasoning, confidence, content_types_used

    def _build_citations(
        self,
        context_chunks: list[dict[str, Any]],
        video: dict[str, Any],
    ) -> list[CitationDTO]:
        """Build citation DTOs from context chunks.

        Args:
            context_chunks: Chunks with relevance scores.
            video: Video metadata.

        Returns:
            List of citation DTOs.
        """
        self._logger.debug(
            "Building citation DTOs",
            extra={
                "chunk_count": len(context_chunks),
                "video_id": video.get("id"),
            },
        )

        citations: list[CitationDTO] = []
        youtube_url = video.get("youtube_url", "")

        for i, item in enumerate(context_chunks):
            chunk = item["chunk"]
            score = item["score"]

            chunk_start_time = chunk.get("start_time", 0)
            chunk_end_time = chunk.get("end_time", 0)

            # Build YouTube URL with timestamp
            yt_url = None
            if youtube_url:
                separator = "&" if "?" in youtube_url else "?"
                yt_url = f"{youtube_url}{separator}t={int(chunk_start_time)}"

            start_fmt = self._format_timestamp(chunk_start_time)
            end_fmt = self._format_timestamp(chunk_end_time)

            text_content = chunk.get("text", "")
            preview = (
                text_content[:200] + "..." if len(text_content) > 200 else text_content
            )

            citation = CitationDTO(
                id=chunk.get("id", ""),
                modality=QueryModality.TRANSCRIPT,
                timestamp_range=TimestampRangeDTO(
                    start_time=chunk_start_time,
                    end_time=chunk_end_time,
                    display=f"{start_fmt} - {end_fmt}",
                ),
                content_preview=preview,
                relevance_score=score,
                youtube_url=yt_url,
            )
            citations.append(citation)

            self._logger.debug(
                f"Citation {i + 1} created",
                extra={
                    "citation_id": citation.id,
                    "timestamp_range": citation.timestamp_range.display,
                    "relevance_score": score,
                    "preview_length": len(preview),
                    "has_youtube_url": yt_url is not None,
                },
            )

        return citations

    def _map_modalities(
        self,
        query_modalities: list[QueryModality],
    ) -> list[Modality]:
        """Map query modalities to domain modalities.

        Args:
            query_modalities: Query modality enums.

        Returns:
            Domain modality enums.
        """
        mapping = {
            QueryModality.TRANSCRIPT: Modality.TRANSCRIPT,
            QueryModality.FRAME: Modality.FRAME,
            QueryModality.AUDIO: Modality.AUDIO,
            QueryModality.VIDEO: Modality.VIDEO,
        }
        return [mapping[m] for m in query_modalities if m in mapping]

    async def get_sources(
        self,
        video_id: str,
        request: GetSourcesRequest,
    ) -> SourcesResponse:
        """Get detailed source artifacts for citations.

        Args:
            video_id: ID of the video.
            request: Request with citation IDs and artifact types.

        Returns:
            Response with detailed source information.

        Raises:
            ValueError: If video not found.
        """
        from datetime import UTC, datetime, timedelta

        self._logger.info(
            "Getting sources for citations",
            extra={
                "video_id": video_id,
                "citation_ids": request.citation_ids,
                "include_artifacts": request.include_artifacts,
                "url_expiry_minutes": request.url_expiry_minutes,
            },
        )

        with LogContext(video_id=video_id):
            # Verify video exists
            self._logger.debug(
                "Verifying video exists",
                extra={"collection": self._videos_collection},
            )
            video = await self._document_db.find_by_id(
                self._videos_collection, video_id
            )
            if not video:
                self._logger.warning("Video not found for get_sources request")
                raise ValueError(f"Video not found: {video_id}")

            self._logger.debug(
                "Video found for sources request",
                extra={"video_title": video.get("title")},
            )

            sources: list[SourceDetail] = []
            expiry_minutes = request.url_expiry_minutes

            for citation_id in request.citation_ids:
                self._logger.debug(
                    "Processing citation",
                    extra={"citation_id": citation_id},
                )

                # Try to find the chunk in transcript chunks
                chunk = await self._document_db.find_by_id(
                    self._chunks_collection,
                    citation_id,
                )

                if not chunk:
                    self._logger.debug(
                        "Chunk not found for citation",
                        extra={"citation_id": citation_id},
                    )
                    continue

                self._logger.debug(
                    "Chunk found",
                    extra={
                        "citation_id": citation_id,
                        "start_time": chunk.get("start_time"),
                        "end_time": chunk.get("end_time"),
                    },
                )

                # Build artifacts based on request
                artifacts: dict[str, SourceArtifact] = {}

                if "transcript_text" in request.include_artifacts:
                    text_content = chunk.get("text", "")
                    artifacts["transcript_text"] = SourceArtifact(
                        type="transcript_text",
                        content=text_content,
                    )
                    self._logger.debug(
                        "Added transcript_text artifact",
                        extra={"text_length": len(text_content)},
                    )

                if "thumbnail" in request.include_artifacts:
                    self._logger.debug(
                        "Fetching thumbnail for citation",
                        extra={
                            "citation_id": citation_id,
                            "timestamp": chunk.get("start_time", 0),
                        },
                    )
                    # Try to get thumbnail from frame associated with this timestamp
                    thumbnail_url = await self._get_thumbnail_url(
                        video_id,
                        chunk.get("start_time", 0),
                        expiry_minutes * 60,
                    )
                    if thumbnail_url:
                        artifacts["thumbnail"] = SourceArtifact(
                            type="thumbnail",
                            url=thumbnail_url,
                        )
                        self._logger.debug("Thumbnail artifact added")
                    else:
                        self._logger.debug("No thumbnail available for timestamp")

                chunk_start_time = chunk.get("start_time", 0)
                chunk_end_time = chunk.get("end_time", 0)

                start_fmt = self._format_timestamp(chunk_start_time)
                end_fmt = self._format_timestamp(chunk_end_time)
                source = SourceDetail(
                    citation_id=citation_id,
                    modality=QueryModality.TRANSCRIPT,
                    timestamp_range=TimestampRangeDTO(
                        start_time=chunk_start_time,
                        end_time=chunk_end_time,
                        display=f"{start_fmt} - {end_fmt}",
                    ),
                    artifacts=artifacts,
                )
                sources.append(source)

                self._logger.debug(
                    "Source detail created",
                    extra={
                        "citation_id": citation_id,
                        "artifact_types": list(artifacts.keys()),
                    },
                )

            expires_at = datetime.now(UTC) + timedelta(minutes=expiry_minutes)

            self._logger.info(
                "Sources retrieval completed",
                extra={
                    "sources_found": len(sources),
                    "citations_requested": len(request.citation_ids),
                    "expires_at": expires_at.isoformat(),
                },
            )

            return SourcesResponse(
                sources=sources,
                expires_at=expires_at,
            )

    async def _get_thumbnail_url(
        self,
        video_id: str,
        timestamp: float,
        expiry_seconds: int,
    ) -> str | None:
        """Get thumbnail URL for a timestamp.

        Finds the nearest frame to the given timestamp and generates
        a presigned URL for the thumbnail.

        Args:
            video_id: Video ID.
            timestamp: Time in seconds.
            expiry_seconds: URL expiry time.

        Returns:
            Presigned URL or None if not available.
        """
        if self._blob is None:
            self._logger.debug("Blob storage not configured, skipping thumbnail")
            return None

        try:
            self._logger.debug(
                "Searching for frame at timestamp",
                extra={
                    "video_id": video_id,
                    "timestamp": timestamp,
                    "expiry_seconds": expiry_seconds,
                },
            )

            # Find the nearest frame chunk to this timestamp
            frames = await self._document_db.find(
                self._frames_collection,
                {
                    "video_id": video_id,
                    "start_time": {"$lte": timestamp},
                    "end_time": {"$gte": timestamp},
                },
                limit=1,
            )

            if not frames:
                self._logger.debug(
                    "No exact frame match, searching for closest frame before "
                    "timestamp",
                )
                # Try to find closest frame before timestamp
                frames = await self._document_db.find(
                    self._frames_collection,
                    {
                        "video_id": video_id,
                        "start_time": {"$lte": timestamp},
                    },
                    sort=[("start_time", -1)],
                    limit=1,
                )

            if not frames:
                self._logger.debug("No frames found for timestamp")
                return None

            frame = frames[0]
            thumbnail_path = frame.get("thumbnail_path")

            self._logger.debug(
                "Frame found",
                extra={
                    "frame_id": frame.get("id"),
                    "frame_start_time": frame.get("start_time"),
                    "thumbnail_path": thumbnail_path,
                },
            )

            if not thumbnail_path:
                self._logger.debug("Frame has no thumbnail_path")
                return None

            # Check if blob exists and generate presigned URL
            blob_exists = await self._blob.exists(self._frames_bucket, thumbnail_path)
            if blob_exists:
                self._logger.debug(
                    "Generating presigned URL for thumbnail",
                    extra={
                        "bucket": self._frames_bucket,
                        "path": thumbnail_path,
                    },
                )
                url = await self._blob.generate_presigned_url(
                    self._frames_bucket,
                    thumbnail_path,
                    expiry_seconds=expiry_seconds,
                )
                self._logger.debug("Presigned URL generated successfully")
                return url
            else:
                self._logger.debug(
                    "Thumbnail blob does not exist",
                    extra={
                        "bucket": self._frames_bucket,
                        "path": thumbnail_path,
                    },
                )

            return None

        except Exception as e:
            self._logger.warning(
                "Failed to get thumbnail URL",
                extra={
                    "video_id": video_id,
                    "timestamp": timestamp,
                    "error": str(e),
                },
            )
            return None

    @staticmethod
    def _format_timestamp(seconds: float) -> str:
        """Format seconds as MM:SS or HH:MM:SS.

        Args:
            seconds: Time in seconds.

        Returns:
            Formatted timestamp string.
        """
        total_seconds = int(seconds)
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        secs = total_seconds % 60

        if hours > 0:
            return f"{hours:02d}:{minutes:02d}:{secs:02d}"
        return f"{minutes:02d}:{secs:02d}"

    # =========================================================================
    # Agentic Query Methods
    # =========================================================================

    async def query_with_decomposition(
        self,
        video_id: str,
        request: QueryVideoRequest,
    ) -> QueryVideoResponse:
        """Query using agentic decomposition for complex questions.

        Decomposes the query into subtasks, executes them, and synthesizes.

        Args:
            video_id: ID of the video to query.
            request: Query request.

        Returns:
            Response with synthesized answer and citations.
        """
        start_time = time.perf_counter()

        self._logger.info(
            "Starting decomposed query",
            extra={"video_id": video_id, "query": request.query[:100]},
        )

        # Verify video exists
        video = await self._document_db.find_by_id(self._videos_collection, video_id)
        if not video:
            raise ValueError(f"Video not found: {video_id}")
        if video.get("status") != "ready":
            raise ValueError(f"Video not ready: {video.get('status')}")

        # Decompose the query
        decomposition = await self._decomposer.decompose(request.query)

        self._logger.info(
            "Query decomposed",
            extra={
                "is_simple": decomposition.is_simple,
                "subtask_count": len(decomposition.subtasks),
            },
        )

        # Execute subtasks
        results = await self._execute_subtasks(
            video_id=video_id,
            subtasks=decomposition.subtasks,
            similarity_threshold=request.similarity_threshold,
            max_results_per_subtask=request.max_citations,
        )

        # Synthesize results
        answer, confidence = await self._synthesizer.synthesize(
            original_query=request.query,
            results=results,
            video_title=video.get("title", "Unknown"),
        )

        # Collect all chunks for citations
        all_chunks: list[dict[str, Any]] = []
        for result in results:
            if result.success:
                for i, chunk in enumerate(result.chunks):
                    score = result.scores[i] if i < len(result.scores) else 0.0
                    all_chunks.append({"chunk": chunk, "score": score})

        # Sort by score and take top N
        all_chunks.sort(key=lambda x: x["score"], reverse=True)
        top_chunks = all_chunks[: request.max_citations]

        # Build citations
        citations = self._build_citations(top_chunks, video)

        # Build decomposition info
        subtask_infos = [
            SubTaskInfo(
                id=result.subtask_id,
                sub_query=result.sub_query,
                target_modality=result.modality.value,
                chunks_found=len(result.chunks),
                success=result.success,
            )
            for result in results
        ]

        processing_time_ms = int((time.perf_counter() - start_time) * 1000)

        self._logger.info(
            "Decomposed query completed",
            extra={
                "total_time_ms": processing_time_ms,
                "subtasks_executed": len(results),
                "total_chunks": len(all_chunks),
                "confidence": confidence,
            },
        )

        return QueryVideoResponse(
            answer=answer,
            reasoning=decomposition.reasoning,
            confidence=confidence,
            citations=citations,
            query_metadata=QueryMetadata(
                video_id=video_id,
                video_title=video.get("title", "Unknown"),
                modalities_searched=[QueryModality(r.modality.value) for r in results],
                chunks_analyzed=len(all_chunks),
                processing_time_ms=processing_time_ms,
                decomposition=DecompositionInfo(
                    was_decomposed=not decomposition.is_simple,
                    subtask_count=len(decomposition.subtasks),
                    subtasks=subtask_infos,
                    reasoning=decomposition.reasoning,
                ),
            ),
        )

    async def _execute_subtasks(
        self,
        video_id: str,
        subtasks: list[SubTask],
        similarity_threshold: float,
        max_results_per_subtask: int,
    ) -> list[SubTaskResult]:
        """Execute subtasks, respecting dependencies.

        Args:
            video_id: Video to search.
            subtasks: Subtasks to execute.
            similarity_threshold: Minimum similarity score.
            max_results_per_subtask: Max results per subtask.

        Returns:
            List of subtask results.
        """
        # Get execution order (waves of parallel tasks)
        waves = self._decomposer.get_execution_order(subtasks)
        results: list[SubTaskResult] = []

        for wave in waves:
            # Execute wave in parallel
            wave_tasks = [
                self._execute_single_subtask(
                    video_id=video_id,
                    subtask=st,
                    similarity_threshold=similarity_threshold,
                    max_results=max_results_per_subtask,
                )
                for st in wave
            ]
            wave_results = await asyncio.gather(*wave_tasks)
            results.extend(wave_results)

        return results

    async def _execute_single_subtask(
        self,
        video_id: str,
        subtask: SubTask,
        similarity_threshold: float,
        max_results: int,
    ) -> SubTaskResult:
        """Execute a single subtask.

        Args:
            video_id: Video to search.
            subtask: The subtask to execute.
            similarity_threshold: Minimum similarity.
            max_results: Maximum results.

        Returns:
            SubTaskResult with chunks and scores.
        """
        self._logger.debug(
            "Executing subtask",
            extra={
                "subtask_id": subtask.id,
                "sub_query": subtask.sub_query,
                "modality": subtask.target_modality.value,
            },
        )

        try:
            # Generate embedding for subtask query
            embeddings = await self._embedder.embed_texts([subtask.sub_query])
            if not embeddings:
                return SubTaskResult(
                    subtask_id=subtask.id,
                    sub_query=subtask.sub_query,
                    modality=subtask.target_modality,
                    chunks=[],
                    scores=[],
                    success=False,
                    error="Failed to generate embedding",
                )

            query_vector = embeddings[0].vector

            # Select collection based on modality
            collection = self._get_collection_for_modality(subtask.target_modality)
            chunks_collection = self._get_chunks_collection_for_modality(
                subtask.target_modality
            )

            # Search
            search_results = await self._vector_db.search(
                collection=collection,
                query_vector=query_vector,
                limit=max_results,
                score_threshold=similarity_threshold,
                filters={"video_id": video_id},
            )

            # Fetch chunk documents
            chunks: list[dict[str, Any]] = []
            scores: list[float] = []

            for result in search_results:
                chunk_id = result.payload.get("chunk_id")
                if chunk_id:
                    chunk = await self._document_db.find_by_id(
                        chunks_collection, chunk_id
                    )
                    if chunk:
                        chunks.append(chunk)
                        scores.append(result.score)

            self._logger.debug(
                "Subtask completed",
                extra={
                    "subtask_id": subtask.id,
                    "chunks_found": len(chunks),
                },
            )

            return SubTaskResult(
                subtask_id=subtask.id,
                sub_query=subtask.sub_query,
                modality=subtask.target_modality,
                chunks=chunks,
                scores=scores,
                success=True,
            )

        except Exception as e:
            self._logger.warning(
                "Subtask failed",
                extra={"subtask_id": subtask.id, "error": str(e)},
            )
            return SubTaskResult(
                subtask_id=subtask.id,
                sub_query=subtask.sub_query,
                modality=subtask.target_modality,
                chunks=[],
                scores=[],
                success=False,
                error=str(e),
            )

    def _get_collection_for_modality(self, modality: Modality) -> str:
        """Get vector collection name for a modality."""
        collections = {
            Modality.TRANSCRIPT: self._settings.vector_db.collections.transcripts,
            Modality.FRAME: self._settings.vector_db.collections.frames,
        }
        return collections.get(modality, self._vectors_collection)

    def _get_chunks_collection_for_modality(self, modality: Modality) -> str:
        """Get document collection name for a modality."""
        collections = {
            Modality.TRANSCRIPT: self._chunks_collection,
            Modality.FRAME: self._frames_collection,
        }
        return collections.get(modality, self._chunks_collection)

    async def _get_frames_near_timestamp(
        self,
        video_id: str,
        timestamp: float,
        window_seconds: float = 5.0,
        max_frames: int = 3,
    ) -> list[dict[str, Any]]:
        """Get frames near a timestamp for vision-augmented context.

        Args:
            video_id: Video ID.
            timestamp: Center timestamp in seconds.
            window_seconds: Time window around timestamp.
            max_frames: Maximum frames to return.

        Returns:
            List of frame chunk documents.
        """
        start = max(0, timestamp - window_seconds)
        end = timestamp + window_seconds

        frames = await self._document_db.find(
            self._frames_collection,
            {
                "video_id": video_id,
                "start_time": {"$gte": start, "$lte": end},
            },
            sort=[("start_time", 1)],
            limit=max_frames,
        )

        return list(frames)

    async def _get_distributed_frames(
        self,
        video_id: str,
        duration_seconds: float,
        max_frames: int = 5,
    ) -> list[dict[str, Any]]:
        """Get frames distributed evenly across the video duration.

        Useful for visual-first queries where we need representative
        frames from the entire video, not just near a specific timestamp.

        Args:
            video_id: Video ID.
            duration_seconds: Total video duration.
            max_frames: Maximum frames to return.

        Returns:
            List of frame chunk documents distributed across the video.
        """
        if duration_seconds <= 0:
            return []

        # Calculate interval between frames
        interval = duration_seconds / (max_frames + 1)
        target_timestamps = [interval * (i + 1) for i in range(max_frames)]

        frames: list[dict[str, Any]] = []

        for timestamp in target_timestamps:
            # Find closest frame to this timestamp
            nearby = await self._document_db.find(
                self._frames_collection,
                {
                    "video_id": video_id,
                    "start_time": {"$lte": timestamp + 5.0},
                },
                sort=[("start_time", -1)],  # Get closest one before/at timestamp
                limit=1,
            )
            nearby_list = list(nearby)
            if nearby_list:
                # Avoid duplicates
                frame = nearby_list[0]
                if not any(f.get("id") == frame.get("id") for f in frames):
                    frames.append(frame)

        self._logger.debug(
            "Retrieved distributed frames",
            extra={
                "video_id": video_id,
                "requested": max_frames,
                "retrieved": len(frames),
                "target_timestamps": target_timestamps,
            },
        )

        return frames

    def _is_visual_query(self, query: str) -> bool:
        """Detect if a query is asking about visual content.

        Args:
            query: The user's query string.

        Returns:
            True if the query appears to be about visual content.
        """
        query_lower = query.lower()
        visual_keywords = self._settings.query.visual.visual_keywords

        for keyword in visual_keywords:
            if keyword.lower() in query_lower:
                self._logger.debug(
                    "Visual query detected",
                    extra={"query": query[:50], "matched_keyword": keyword},
                )
                return True

        return False

    async def _get_image_as_base64(self, blob_path: str) -> str | None:
        """Download image from blob storage and convert to base64 data URL.

        Args:
            blob_path: Path to the image in blob storage.

        Returns:
            Base64 data URL string or None if failed.
        """
        if not self._blob:
            return None

        try:
            # Download image bytes
            image_bytes = await self._blob.download(
                bucket=self._frames_bucket,
                path=blob_path,
            )

            # Convert to base64
            b64_data = base64.b64encode(image_bytes).decode("utf-8")

            # Determine mime type from extension
            ext = blob_path.lower().split(".")[-1] if "." in blob_path else "jpg"
            mime_types = {
                "jpg": "image/jpeg",
                "jpeg": "image/jpeg",
                "png": "image/png",
                "webp": "image/webp",
                "gif": "image/gif",
            }
            mime = mime_types.get(ext, "image/jpeg")

            return f"data:{mime};base64,{b64_data}"

        except Exception as e:
            self._logger.debug(
                "Failed to download and encode image",
                extra={"blob_path": blob_path, "error": str(e)},
            )
            return None

    async def _build_visual_context(
        self,
        video_id: str,
        video_title: str,
        duration_seconds: float,
        builder: MultimodalMessageBuilder,
        max_frames: int | None = None,
    ) -> list[str]:
        """Build visual context by adding distributed frames to the message.

        Downloads images from blob storage and converts to base64 to avoid
        issues with localhost URLs not being accessible by external LLM APIs.

        Args:
            video_id: Video ID.
            video_title: Video title for context.
            duration_seconds: Video duration.
            builder: Message builder to add content to.
            max_frames: Override max frames (uses settings if None).

        Returns:
            List of content types used.
        """
        content_types_used: list[str] = []
        max_frames = max_frames or self._settings.query.visual.max_frames_per_query

        if not self._blob:
            self._logger.warning("Blob storage not available for visual context")
            return content_types_used

        # Get distributed frames
        frames = await self._get_distributed_frames(
            video_id=video_id,
            duration_seconds=duration_seconds,
            max_frames=max_frames,
        )

        if not frames:
            self._logger.warning(
                "No frames available for visual context",
                extra={"video_id": video_id},
            )
            return content_types_used

        # Add context header
        builder.add_text(
            f"Visual context from video '{video_title}' "
            f"({len(frames)} frames across {duration_seconds:.0f} seconds):\n"
        )

        # Add each frame with timestamp
        for i, frame in enumerate(frames):
            blob_path = frame.get("blob_path")
            start_time = frame.get("start_time", 0)
            description = frame.get("description", "")

            if blob_path:
                try:
                    # Download and convert to base64
                    image_data = await self._get_image_as_base64(blob_path)
                    if not image_data:
                        continue

                    timestamp_fmt = self._format_timestamp(start_time)

                    # Add text label for frame
                    frame_label = f"\n[Frame {i + 1} at {timestamp_fmt}]"
                    if description:
                        frame_label += f": {description}"
                    builder.add_text(frame_label)

                    # Add the image as base64
                    builder.add_image(
                        image_data,
                        metadata={
                            "frame_id": frame.get("id"),
                            "timestamp": start_time,
                            "frame_number": frame.get("frame_number"),
                        },
                    )

                    if "image" not in content_types_used:
                        content_types_used.append("image")

                except Exception as e:
                    self._logger.debug(
                        "Failed to add frame to visual context",
                        extra={"frame_id": frame.get("id"), "error": str(e)},
                    )

        self._logger.debug(
            "Visual context built",
            extra={
                "video_id": video_id,
                "frames_added": len(frames),
            },
        )

        return content_types_used

    async def visual_query(
        self,
        video_id: str,
        request: QueryVideoRequest,
    ) -> QueryVideoResponse:
        """Query using visual-first approach with frames as primary context.

        This method is optimized for questions about visual content that
        may not be present in the transcript (e.g., text on screen,
        names in console, UI elements).

        Args:
            video_id: ID of the video to query.
            request: Query request.

        Returns:
            Response with answer based on visual analysis.
        """
        start_time = time.perf_counter()

        self._logger.info(
            "Starting visual-first query",
            extra={
                "video_id": video_id,
                "query": request.query[:100],
            },
        )

        with LogContext(video_id=video_id):
            # Verify video exists and is ready
            video = await self._document_db.find_by_id(
                self._videos_collection, video_id
            )

            if not video:
                raise ValueError(f"Video not found: {video_id}")

            if video.get("status") != "ready":
                raise ValueError(f"Video not ready: {video.get('status')}")

            video_title = video.get("title", "Unknown")
            duration_seconds = video.get("duration_seconds", 0)

            # Determine model and capabilities
            model_id = self._llm.default_model
            enabled = {ContentType.TEXT, ContentType.IMAGE}

            # Build multimodal message with visual context
            builder = MultimodalMessageBuilder(
                model_id=model_id,
                enabled_modalities=enabled,
                blob_storage=self._blob,
            )

            # Add distributed frames as primary context
            # Use request override if specified, otherwise use settings
            max_frames = (
                request.max_visual_frames
                or self._settings.query.visual.max_frames_per_query
            )
            content_types_used = await self._build_visual_context(
                video_id=video_id,
                video_title=video_title,
                duration_seconds=duration_seconds,
                builder=builder,
                max_frames=max_frames,
            )

            # Also try to get relevant transcript context if available
            try:
                query_embeddings = await self._embedder.embed_texts([request.query])
                if query_embeddings:
                    search_results = await self._vector_db.search(
                        collection=self._vectors_collection,
                        query_vector=query_embeddings[0].vector,
                        limit=3,  # Just a few for additional context
                        filters={"video_id": video_id},
                        score_threshold=request.similarity_threshold,
                    )

                    if search_results:
                        builder.add_text("\n\nRelevant transcript excerpts:\n")
                        for result in search_results:
                            chunk_id = result.payload.get("chunk_id")
                            if chunk_id:
                                chunk = await self._document_db.find_by_id(
                                    self._chunks_collection, chunk_id
                                )
                                if chunk:
                                    text = chunk.get("text", "")[:300]
                                    start = chunk.get("start_time", 0)
                                    end = chunk.get("end_time", 0)
                                    builder.add_text(
                                        f"[{self._format_timestamp(start)} - "
                                        f"{self._format_timestamp(end)}]: {text}\n"
                                    )
            except Exception as e:
                self._logger.debug(
                    "Could not add transcript context",
                    extra={"error": str(e)},
                )

            # Add the question
            builder.add_text(
                f"\n\nQuestion: {request.query}\n\n"
                "Please analyze the visual content (frames/images) carefully to "
                "answer this question. Look for any text, names, numbers, or "
                "visual elements shown on screen. If you can see the answer in "
                "the images, provide it with the timestamp where it appears."
            )

            # Build message
            user_message = builder.build_as_llm_message()

            # System prompt for visual analysis
            system_prompt = (
                "You are an assistant that analyzes video content visually.\n"
                f'You have been given frames from "{video_title}".\n'
                "IMPORTANT: Carefully examine each image for:\n"
                "- Text displayed on screen (console output, UI text, names, etc.)\n"
                "- Numbers, codes, or identifiers visible\n"
                "- Visual elements and their state\n"
                "Answer based on what you can SEE in the frames.\n"
                "Always cite the timestamp [MM:SS] where you found the information."
            )

            messages = [
                Message(role=MessageRole.SYSTEM, content=system_prompt),
                user_message,
            ]

            # Call LLM
            response = await self._llm.generate(
                messages=messages,
                temperature=0.3,
                max_tokens=1024,
            )

            elapsed_time = time.perf_counter() - start_time

            # Build response
            return QueryVideoResponse(
                answer=response.content,
                confidence=0.8,  # Visual analysis confidence
                citations=[],  # Visual queries don't have traditional citations
                query_metadata=QueryMetadata(
                    video_id=video_id,
                    video_title=video_title,
                    modalities_searched=[QueryModality.FRAME],
                    chunks_analyzed=0,  # Visual queries analyze frames directly
                    processing_time_ms=int(elapsed_time * 1000),
                    multimodal_content_used=content_types_used,
                ),
            )

    # =========================================================================
    # Confidence-Based Refinement
    # =========================================================================

    async def query_with_refinement(
        self,
        video_id: str,
        request: QueryVideoRequest,
    ) -> tuple[QueryVideoResponse, RefinementInfo]:
        """Query with automatic refinement if confidence is low.

        Args:
            video_id: Video to query.
            request: Query request.

        Returns:
            Tuple of (response, refinement_info).
        """
        # First attempt
        response = await self.query(video_id, request)
        original_confidence = response.confidence

        refinement_info = RefinementInfo(
            was_refined=False,
            original_confidence=original_confidence,
            final_confidence=original_confidence,
            iterations=1,
        )

        # Check if refinement needed
        if not self._refiner.should_refine(
            original_confidence,
            request.confidence_threshold,
            iteration=0,
        ):
            return response, refinement_info

        self._logger.info(
            "Low confidence, attempting refinement",
            extra={
                "original_confidence": original_confidence,
                "threshold": request.confidence_threshold,
            },
        )

        strategies_tried: list[RefinementStrategy] = []
        best_response = response
        best_confidence = original_confidence

        for iteration in range(self._refiner._max_iterations):
            strategy = self._refiner.select_strategy(iteration, strategies_tried)
            strategies_tried.append(strategy)

            if strategy == RefinementStrategy.EXPAND_QUERY:
                # Try expanded query
                expanded, _ = await self._refiner.expand_query(request.query)
                new_request = request.model_copy(update={"query": expanded})
                new_response = await self.query(video_id, new_request)

                if new_response.confidence > best_confidence:
                    best_response = new_response
                    best_confidence = new_response.confidence

            elif strategy == RefinementStrategy.LOWER_THRESHOLD:
                # Lower threshold and retry
                new_threshold = request.similarity_threshold * 0.7
                new_request = request.model_copy(
                    update={"similarity_threshold": new_threshold}
                )
                new_response = await self.query(video_id, new_request)

                if new_response.confidence > best_confidence:
                    best_response = new_response
                    best_confidence = new_response.confidence

            # Check if we've reached acceptable confidence
            if best_confidence >= request.confidence_threshold:
                break

        refinement_info = RefinementInfo(
            was_refined=True,
            original_confidence=original_confidence,
            final_confidence=best_confidence,
            refinement_strategy=(
                strategies_tried[-1].value if strategies_tried else None
            ),
            iterations=len(strategies_tried) + 1,
        )

        self._logger.info(
            "Refinement complete",
            extra={
                "original_confidence": original_confidence,
                "final_confidence": best_confidence,
                "strategies_tried": [s.value for s in strategies_tried],
            },
        )

        return best_response, refinement_info

    # =========================================================================
    # Cross-Video Search
    # =========================================================================

    async def query_across_videos(
        self,
        request: CrossVideoRequest,
    ) -> CrossVideoResponse:
        """Search across multiple videos and synthesize results.

        Args:
            request: Cross-video query request.

        Returns:
            Synthesized response from all videos.
        """
        start_time = time.perf_counter()

        self._logger.info(
            "Starting cross-video query",
            extra={
                "query": request.query[:100],
                "video_ids": request.video_ids,
                "max_videos": request.max_videos,
            },
        )

        # Get videos to search
        if request.video_ids:
            video_ids = request.video_ids[: request.max_videos]
        else:
            # Get all ready videos
            videos = await self._document_db.find(
                self._videos_collection,
                {"status": "ready"},
                limit=request.max_videos,
            )
            video_ids = [str(v.get("id")) for v in videos if v.get("id")]

        if not video_ids:
            return CrossVideoResponse(
                answer="No videos available to search.",
                confidence=0.0,
                video_results=[],
                videos_searched=0,
                total_citations=0,
                processing_time_ms=0,
            )

        # Search each video in parallel
        search_tasks = [
            self._search_single_video(
                video_id=vid,
                query=request.query,
                max_citations=request.max_citations_per_video,
                similarity_threshold=request.similarity_threshold,
            )
            for vid in video_ids
        ]

        video_results = await asyncio.gather(*search_tasks)

        # Filter out empty results and sort by relevance
        video_results = [r for r in video_results if r.citations]
        video_results.sort(key=lambda x: x.relevance_score, reverse=True)

        # Synthesize
        answer, confidence = await self._cross_video.synthesize_results(
            query=request.query,
            video_results=video_results,
        )

        processing_time_ms = int((time.perf_counter() - start_time) * 1000)
        total_citations = sum(len(r.citations) for r in video_results)

        self._logger.info(
            "Cross-video query complete",
            extra={
                "videos_searched": len(video_ids),
                "videos_with_results": len(video_results),
                "total_citations": total_citations,
                "processing_time_ms": processing_time_ms,
            },
        )

        return CrossVideoResponse(
            answer=answer,
            confidence=confidence,
            video_results=video_results,
            videos_searched=len(video_ids),
            total_citations=total_citations,
            processing_time_ms=processing_time_ms,
        )

    async def _search_single_video(
        self,
        video_id: str,
        query: str,
        max_citations: int,
        similarity_threshold: float,
    ) -> VideoResult:
        """Search a single video for cross-video query.

        Args:
            video_id: Video to search.
            query: Search query.
            max_citations: Maximum citations.
            similarity_threshold: Minimum similarity.

        Returns:
            VideoResult with citations.
        """
        try:
            # Get video metadata
            video = await self._document_db.find_by_id(
                self._videos_collection, video_id
            )
            if not video or video.get("status") != "ready":
                return VideoResult(
                    video_id=video_id,
                    video_title="Unknown",
                    relevance_score=0.0,
                    citations=[],
                )

            # Generate embedding
            embeddings = await self._embedder.embed_texts([query])
            if not embeddings:
                return VideoResult(
                    video_id=video_id,
                    video_title=video.get("title", "Unknown"),
                    relevance_score=0.0,
                    citations=[],
                )

            # Search
            results = await self._vector_db.search(
                collection=self._vectors_collection,
                query_vector=embeddings[0].vector,
                limit=max_citations,
                score_threshold=similarity_threshold,
                filters={"video_id": video_id},
            )

            if not results:
                return VideoResult(
                    video_id=video_id,
                    video_title=video.get("title", "Unknown"),
                    relevance_score=0.0,
                    citations=[],
                )

            # Build citations
            citations: list[CitationDTO] = []
            scores: list[float] = []

            for r in results:
                chunk_id = r.payload.get("chunk_id")
                if chunk_id:
                    chunk = await self._document_db.find_by_id(
                        self._chunks_collection, chunk_id
                    )
                    if chunk:
                        citations.append(
                            CitationDTO(
                                id=chunk.get("id", ""),
                                modality=QueryModality.TRANSCRIPT,
                                timestamp_range=TimestampRangeDTO(
                                    start_time=chunk.get("start_time", 0),
                                    end_time=chunk.get("end_time", 0),
                                    display=self._format_timestamp(
                                        chunk.get("start_time", 0)
                                    ),
                                ),
                                content_preview=chunk.get("text", "")[:300],
                                relevance_score=r.score,
                            )
                        )
                        scores.append(r.score)

            avg_score = sum(scores) / len(scores) if scores else 0.0

            return VideoResult(
                video_id=video_id,
                video_title=video.get("title", "Unknown"),
                relevance_score=avg_score,
                citations=citations,
            )

        except Exception as e:
            self._logger.warning(
                f"Failed to search video {video_id}: {e}",
            )
            return VideoResult(
                video_id=video_id,
                video_title="Error",
                relevance_score=0.0,
                citations=[],
            )

    # =========================================================================
    # Tool-Augmented Generation
    # =========================================================================

    async def query_with_tools(
        self,
        video_id: str,
        request: QueryVideoRequest,
    ) -> tuple[QueryVideoResponse, list[ToolCall]]:
        """Query with internal tool use during generation.

        The LLM can call tools to get more context during answer generation.

        Args:
            video_id: Video to query.
            request: Query request.

        Returns:
            Tuple of (response, tool_calls_made).
        """
        tool_calls: list[ToolCall] = []

        # Get initial context
        video = await self._document_db.find_by_id(self._videos_collection, video_id)
        if not video:
            raise ValueError(f"Video not found: {video_id}")

        # Generate initial embedding and search
        embeddings = await self._embedder.embed_texts([request.query])
        if not embeddings:
            raise ValueError("Failed to generate embedding")

        results = await self._vector_db.search(
            collection=self._vectors_collection,
            query_vector=embeddings[0].vector,
            limit=request.max_citations * 2,
            score_threshold=request.similarity_threshold,
            filters={"video_id": video_id},
        )

        # Fetch chunks
        context_chunks: list[dict[str, Any]] = []
        for r in results:
            chunk_id = r.payload.get("chunk_id")
            if chunk_id:
                chunk = await self._document_db.find_by_id(
                    self._chunks_collection, chunk_id
                )
                if chunk:
                    context_chunks.append({"chunk": chunk, "score": r.score})

        # Build initial context text
        context_text = self._build_context_text(context_chunks)

        # Build prompt with tools
        tools_prompt = get_tools_prompt()
        system_prompt = (
            f"You are answering questions about the video '{video.get('title')}'.\n"
            "Use the provided context. If you need more information, use the tools.\n\n"
            f"{tools_prompt}"
        )

        user_prompt = f"Context:\n{context_text}\n\nQuestion: {request.query}"

        messages = [
            Message(role=MessageRole.SYSTEM, content=system_prompt),
            Message(role=MessageRole.USER, content=user_prompt),
        ]

        # Tool context for executor
        tool_context = {
            "chunks_collection": self._chunks_collection,
            "frames_collection": self._frames_collection,
            "vectors_collection": self._vectors_collection,
        }

        # Agentic loop - allow up to 3 tool calls
        max_tool_calls = 3
        for _ in range(max_tool_calls + 1):
            response = await self._llm.generate(
                messages=messages,
                temperature=0.3,
                max_tokens=1500,
            )

            # Check for tool call
            tool, args = self._tool_executor.parse_tool_call(response.content)

            if tool is None:
                # No tool call, we have our answer
                break

            # Execute tool
            result, tool_call = await self._tool_executor.execute(
                tool=tool,
                args=args,
                video_id=video_id,
                context=tool_context,
            )
            tool_calls.append(tool_call)

            # Add tool result to conversation
            messages.append(
                Message(role=MessageRole.ASSISTANT, content=response.content)
            )
            messages.append(
                Message(role=MessageRole.USER, content=f"Tool result:\n{result}")
            )

        # Build final response
        answer = response.content
        if "TOOL_CALL:" in answer:
            # Remove incomplete tool call from answer
            answer = answer.split("TOOL_CALL:")[0].strip()

        if context_chunks:
            confidence = sum(c["score"] for c in context_chunks) / len(context_chunks)
        else:
            confidence = 0.0

        citations = self._build_citations(
            context_chunks[: request.max_citations],
            video,
        )

        query_response = QueryVideoResponse(
            answer=answer,
            reasoning=f"Used {len(tool_calls)} tool(s) during generation",
            confidence=min(confidence, 0.95),
            citations=citations,
            query_metadata=QueryMetadata(
                video_id=video_id,
                video_title=video.get("title", "Unknown"),
                modalities_searched=[QueryModality.TRANSCRIPT],
                chunks_analyzed=len(context_chunks),
                processing_time_ms=0,  # Not tracked in this method
            ),
        )

        self._logger.info(
            "Tool-augmented query complete",
            extra={
                "tool_calls": len(tool_calls),
                "tools_used": [tc.tool_name for tc in tool_calls],
            },
        )

        return query_response, tool_calls

    def _build_context_text(self, context_chunks: list[dict[str, Any]]) -> str:
        """Build context text from chunks."""
        parts = []
        for i, item in enumerate(context_chunks, 1):
            chunk = item["chunk"]
            start = chunk.get("start_time", 0)
            end = chunk.get("end_time", 0)
            text = chunk.get("text", "")
            start_fmt = self._format_timestamp(start)
            end_fmt = self._format_timestamp(end)
            parts.append(f"[{i}] ({start_fmt} - {end_fmt}): {text}")
        return "\n\n".join(parts)
