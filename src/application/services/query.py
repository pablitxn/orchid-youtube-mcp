"""Video query service for semantic search and RAG."""

import time
from typing import Any

from src.application.dtos.query import (
    CitationDTO,
    GetSourcesRequest,
    QueryMetadata,
    QueryModality,
    QueryVideoRequest,
    QueryVideoResponse,
    SourceArtifact,
    SourceDetail,
    SourcesResponse,
    TimestampRangeDTO,
)
from src.commons.infrastructure.blob.base import BlobStorageBase
from src.commons.infrastructure.documentdb.base import DocumentDBBase
from src.commons.infrastructure.vectordb.base import VectorDBBase
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

            # Generate answer with LLM
            self._logger.debug(
                "Generating answer with LLM",
                extra={
                    "context_chunks_count": len(context_chunks),
                    "video_title": video.get("title", "Unknown"),
                    "include_reasoning": request.include_reasoning,
                },
            )
            llm_start = time.perf_counter()
            answer, reasoning, confidence = await self._generate_answer(
                query=request.query,
                context_chunks=context_chunks,
                video_title=video.get("title", "Unknown"),
                include_reasoning=request.include_reasoning,
            )
            llm_time_ms = int((time.perf_counter() - llm_start) * 1000)

            self._logger.debug(
                "LLM answer generated",
                extra={
                    "answer_length": len(answer),
                    "has_reasoning": reasoning is not None,
                    "confidence": confidence,
                    "llm_time_ms": llm_time_ms,
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
                ),
            )

    async def _generate_answer(
        self,
        query: str,
        context_chunks: list[dict[str, Any]],
        video_title: str,
        include_reasoning: bool,
    ) -> tuple[str, str | None, float]:
        """Generate answer using LLM.

        Args:
            query: User's question.
            context_chunks: Relevant chunks with scores.
            video_title: Title of the video.
            include_reasoning: Whether to include reasoning.

        Returns:
            Tuple of (answer, reasoning, confidence).
        """
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
            )

        # Build context from chunks
        self._logger.debug(
            "Building context text from chunks",
            extra={"chunk_count": len(context_chunks)},
        )
        context_parts: list[str] = []
        total_context_chars = 0

        for i, item in enumerate(context_chunks, 1):
            chunk = item["chunk"]
            chunk_start_time = chunk.get("start_time", 0)
            chunk_end_time = chunk.get("end_time", 0)
            text = chunk.get("text", "")
            total_context_chars += len(text)

            # Format timestamp
            start_fmt = self._format_timestamp(chunk_start_time)
            end_fmt = self._format_timestamp(chunk_end_time)

            context_parts.append(f"[{i}] ({start_fmt} - {end_fmt}): {text}")

            self._logger.debug(
                f"Context chunk {i}",
                extra={
                    "chunk_id": chunk.get("id"),
                    "start_time": chunk_start_time,
                    "end_time": chunk_end_time,
                    "text_length": len(text),
                    "score": item["score"],
                },
            )

        context_text = "\n\n".join(context_parts)

        self._logger.debug(
            "Context text prepared",
            extra={
                "total_chars": total_context_chars,
                "context_text_length": len(context_text),
            },
        )

        # Build prompt
        system_prompt = (
            "You are an assistant that answers questions about video content.\n"
            f'You have been given transcript excerpts from "{video_title}".\n'
            "Answer the question based ONLY on the provided context.\n"
            "If the context doesn't contain enough information, say so.\n"
            "Always cite the relevant timestamps in your answer."
        )

        user_prompt = f"""Context from the video:

{context_text}

Question: {query}

Please provide a clear, concise answer based on the context above."""

        if include_reasoning:
            user_prompt += "\n\nAlso briefly explain your reasoning."

        self._logger.debug(
            "Prompt prepared for LLM",
            extra={
                "system_prompt_length": len(system_prompt),
                "user_prompt_length": len(user_prompt),
                "include_reasoning": include_reasoning,
            },
        )

        # Generate response
        messages = [
            Message(role=MessageRole.SYSTEM, content=system_prompt),
            Message(role=MessageRole.USER, content=user_prompt),
        ]

        self._logger.debug(
            "Calling LLM service",
            extra={
                "temperature": 0.3,
                "max_tokens": 1024,
                "message_count": len(messages),
            },
        )

        response = await self._llm.generate(
            messages=messages,
            temperature=0.3,  # Lower temperature for factual answers
            max_tokens=1024,
        )

        self._logger.debug(
            "LLM response received",
            extra={
                "response_length": len(response.content),
                "model": getattr(response, "model", "unknown"),
                "tokens_used": getattr(response, "usage", None),
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
                self._logger.debug(
                    "Reasoning extracted from response",
                    extra={
                        "answer_length": len(content),
                        "reasoning_length": len(reasoning),
                    },
                )

        # Calculate confidence based on average relevance scores
        avg_score = sum(item["score"] for item in context_chunks) / len(context_chunks)
        confidence = min(avg_score, 0.95)  # Cap at 0.95

        self._logger.debug(
            "Confidence calculated",
            extra={
                "avg_score": avg_score,
                "capped_confidence": confidence,
                "score_range": {
                    "min": min(item["score"] for item in context_chunks),
                    "max": max(item["score"] for item in context_chunks),
                },
            },
        )

        return content, reasoning, confidence

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
