"""Video query service for semantic search and RAG."""

import asyncio
import time
from typing import Any

from src.application.dtos.query import (
    CitationDTO,
    DecompositionInfo,
    GetSourcesRequest,
    QueryMetadata,
    QueryModality,
    QueryVideoRequest,
    QueryVideoResponse,
    SourceArtifact,
    SourceDetail,
    SourcesResponse,
    SubTaskInfo,
    TimestampRangeDTO,
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
from src.commons.settings.models import Settings
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

    async def query(  # noqa: PLR0915
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
            self._logger.debug(
                "Searching vector database for relevant chunks",
                extra={
                    "collection": self._vectors_collection,
                    "limit": request.max_citations * 2,
                    "score_threshold": request.similarity_threshold,
                    "filter_video_id": video_id,
                },
            )
            search_start = time.perf_counter()
            search_results = await self._vector_db.search(
                collection=self._vectors_collection,
                query_vector=query_vector,
                limit=request.max_citations * 2,  # Get extra for filtering
                score_threshold=request.similarity_threshold,
                filters={"video_id": video_id},
            )
            search_time_ms = int((time.perf_counter() - search_start) * 1000)

            top_scores = [r.score for r in search_results[:5]] if search_results else []
            self._logger.debug(
                "Vector search completed",
                extra={
                    "results_count": len(search_results),
                    "search_time_ms": search_time_ms,
                    "top_scores": top_scores,
                },
            )

            # Build context from search results
            self._logger.debug("Building context from search results")
            context_chunks: list[dict[str, Any]] = []
            chunks_fetched = 0
            chunks_not_found = 0

            for result in search_results:
                chunk_id = result.payload.get("chunk_id")
                if chunk_id:
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
                            }
                        )
                        chunks_fetched += 1
                    else:
                        chunks_not_found += 1
                        self._logger.debug(
                            "Chunk not found in document DB",
                            extra={"chunk_id": chunk_id},
                        )

            self._logger.debug(
                "Context chunks retrieved",
                extra={
                    "chunks_fetched": chunks_fetched,
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

            # Convert dict to TranscriptChunk for the builder
            chunk_start_time = chunk_data.get("start_time", 0)
            chunk_end_time = chunk_data.get("end_time", 0)
            text = chunk_data.get("text", "")

            # Format as numbered context
            start_fmt = self._format_timestamp(chunk_start_time)
            end_fmt = self._format_timestamp(chunk_end_time)

            builder.add_text(
                f"[{i}] ({start_fmt} - {end_fmt}): {text}",
                metadata={
                    "chunk_id": chunk_data.get("id"),
                    "score": score,
                },
            )

            # Vision-augmented: add frames when images enabled
            if ContentType.IMAGE in enabled and self._blob:
                modality = chunk_data.get("modality", "transcript")

                if modality == "frame":
                    # Direct frame chunk - add its image
                    blob_path = chunk_data.get("blob_path")
                    if blob_path:
                        try:
                            url = await self._blob.generate_presigned_url(
                                bucket=self._frames_bucket,
                                path=blob_path,
                                expiry_seconds=3600,
                            )
                            builder.add_image(
                                url,
                                metadata={
                                    "chunk_id": chunk_data.get("id"),
                                    "timestamp": chunk_start_time,
                                },
                            )
                            if "image" not in content_types_used:
                                content_types_used.append("image")
                        except Exception as e:
                            self._logger.debug(
                                "Failed to add frame image",
                                extra={"error": str(e)},
                            )
                else:
                    # Transcript chunk - find nearby frames for visual context
                    video_id = chunk_data.get("video_id")
                    if video_id:
                        nearby_frames = await self._get_frames_near_timestamp(
                            video_id=video_id,
                            timestamp=chunk_start_time,
                            window_seconds=3.0,
                            max_frames=1,  # 1 frame per transcript chunk
                        )
                        for frame in nearby_frames:
                            blob_path = frame.get("blob_path")
                            if blob_path:
                                try:
                                    url = await self._blob.generate_presigned_url(
                                        bucket=self._frames_bucket,
                                        path=blob_path,
                                        expiry_seconds=3600,
                                    )
                                    builder.add_image(
                                        url,
                                        metadata={
                                            "source": "nearby_frame",
                                            "transcript_chunk": chunk_data.get("id"),
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
                    "text_length": len(text),
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
