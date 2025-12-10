"""Video query service for semantic search and RAG."""

import time
from typing import Any

from src.application.dtos.query import (
    CitationDTO,
    QueryMetadata,
    QueryModality,
    QueryVideoRequest,
    QueryVideoResponse,
    TimestampRangeDTO,
)
from src.commons.infrastructure.documentdb.base import DocumentDBBase
from src.commons.infrastructure.vectordb.base import VectorDBBase
from src.commons.settings.models import Settings
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
    ) -> None:
        """Initialize query service.

        Args:
            text_embedding_service: Service for generating query embeddings.
            llm_service: LLM for generating answers.
            vector_db: Vector database for similarity search.
            document_db: Document database for metadata.
            settings: Application settings.
        """
        self._embedder = text_embedding_service
        self._llm = llm_service
        self._vector_db = vector_db
        self._document_db = document_db
        self._settings = settings

        self._vectors_collection = settings.vector_db.collections.transcripts
        self._videos_collection = settings.document_db.collections.videos
        self._chunks_collection = settings.document_db.collections.transcript_chunks

    async def query(
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

        # Verify video exists and is ready
        video = await self._document_db.find_by_id(self._videos_collection, video_id)
        if not video:
            raise ValueError(f"Video not found: {video_id}")

        if video.get("status") != "ready":
            raise ValueError(f"Video not ready for querying: {video.get('status')}")

        # Generate query embedding
        query_embeddings = await self._embedder.embed_texts([request.query])
        if not query_embeddings:
            raise ValueError("Failed to generate query embedding")

        query_vector = query_embeddings[0].vector

        # Search for relevant chunks
        search_results = await self._vector_db.search(
            collection=self._vectors_collection,
            query_vector=query_vector,
            limit=request.max_citations * 2,  # Get extra for filtering
            score_threshold=request.similarity_threshold,
            filters={"video_id": video_id},
        )

        # Build context from search results
        context_chunks: list[dict[str, Any]] = []
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

        # Generate answer with LLM
        answer, reasoning, confidence = await self._generate_answer(
            query=request.query,
            context_chunks=context_chunks,
            video_title=video.get("title", "Unknown"),
            include_reasoning=request.include_reasoning,
        )

        # Build citations
        citations = self._build_citations(
            context_chunks=context_chunks[: request.max_citations],
            video=video,
        )

        # Calculate processing time
        processing_time_ms = int((time.perf_counter() - start_time) * 1000)

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
        context_parts: list[str] = []
        for i, item in enumerate(context_chunks, 1):
            chunk = item["chunk"]
            start_time = chunk.get("start_time", 0)
            end_time = chunk.get("end_time", 0)
            text = chunk.get("text", "")

            # Format timestamp
            start_fmt = self._format_timestamp(start_time)
            end_fmt = self._format_timestamp(end_time)

            context_parts.append(f"[{i}] ({start_fmt} - {end_fmt}): {text}")

        context_text = "\n\n".join(context_parts)

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

        # Generate response
        messages = [
            Message(role=MessageRole.SYSTEM, content=system_prompt),
            Message(role=MessageRole.USER, content=user_prompt),
        ]

        response = await self._llm.generate(
            messages=messages,
            temperature=0.3,  # Lower temperature for factual answers
            max_tokens=1024,
        )

        # Parse response
        content = response.content
        reasoning = None

        if include_reasoning and "reasoning:" in content.lower():
            parts = content.split("reasoning:", 1)
            if len(parts) == 2:
                content = parts[0].strip()
                reasoning = parts[1].strip()

        # Calculate confidence based on average relevance scores
        avg_score = sum(item["score"] for item in context_chunks) / len(context_chunks)
        confidence = min(avg_score, 0.95)  # Cap at 0.95

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
        citations: list[CitationDTO] = []
        youtube_url = video.get("youtube_url", "")

        for item in context_chunks:
            chunk = item["chunk"]
            score = item["score"]

            start_time = chunk.get("start_time", 0)
            end_time = chunk.get("end_time", 0)

            # Build YouTube URL with timestamp
            yt_url = None
            if youtube_url:
                separator = "&" if "?" in youtube_url else "?"
                yt_url = f"{youtube_url}{separator}t={int(start_time)}"

            start_fmt = self._format_timestamp(start_time)
            end_fmt = self._format_timestamp(end_time)

            citation = CitationDTO(
                id=chunk.get("id", ""),
                modality=QueryModality.TRANSCRIPT,
                timestamp_range=TimestampRangeDTO(
                    start_time=start_time,
                    end_time=end_time,
                    display=f"{start_fmt} - {end_fmt}",
                ),
                content_preview=chunk.get("text", "")[:200] + "...",
                relevance_score=score,
                youtube_url=yt_url,
            )
            citations.append(citation)

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
