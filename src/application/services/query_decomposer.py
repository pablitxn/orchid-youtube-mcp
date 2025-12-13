"""Query decomposition service for agentic RAG."""

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from src.commons.telemetry import get_logger
from src.domain.models.chunk import Modality
from src.infrastructure.llm.base import LLMServiceBase, Message, MessageRole


class SubTaskStatus(str, Enum):
    """Status of a subtask execution."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class SubTask:
    """A decomposed subtask from a complex query."""

    id: int
    sub_query: str
    target_modality: Modality
    reasoning: str
    priority: int = 1
    depends_on: list[int] = field(default_factory=list)
    status: SubTaskStatus = SubTaskStatus.PENDING

    def is_ready(self, completed_ids: set[int]) -> bool:
        """Check if all dependencies are satisfied."""
        return all(dep_id in completed_ids for dep_id in self.depends_on)


@dataclass
class SubTaskResult:
    """Result of executing a subtask."""

    subtask_id: int
    sub_query: str
    modality: Modality
    chunks: list[dict[str, Any]]  # Retrieved chunks
    scores: list[float]  # Relevance scores
    success: bool
    error: str | None = None


@dataclass
class DecompositionResult:
    """Result of query decomposition."""

    original_query: str
    subtasks: list[SubTask]
    is_simple: bool  # True if query doesn't need decomposition
    reasoning: str


DECOMPOSITION_PROMPT = """\
Analyze this query and determine if it should be decomposed into subtasks.

Query: {query}

Available modalities for search:
- transcript: Spoken words in the video
- frame: Visual content from video frames
- audio: Audio analysis (music, sounds)
- video: Video segments with motion

Rules:
1. Simple queries → is_simple: true
2. Multi-part or multi-modal queries → decompose
3. Maximum 4 subtasks
4. Each subtask targets the most appropriate modality
5. Use depends_on when one subtask needs results from another

Return JSON:
{{"is_simple": bool, "reasoning": "...", "subtasks": [...]}}

Each subtask: {{"id": N, "sub_query": "...", "target_modality": "...", \
"reasoning": "...", "priority": N, "depends_on": []}}

Examples:
- "What does the speaker say about Python?" → simple, transcript only
- "What code is shown when discussing ML?" → decompose: transcript + frame

Respond with ONLY the JSON object:"""


class QueryDecomposer:
    """Decomposes complex queries into executable subtasks.

    Uses LLM to analyze queries and determine the optimal search strategy.
    Simple queries pass through unchanged, complex ones get split into
    subtasks targeting different modalities.
    """

    def __init__(
        self,
        llm_service: LLMServiceBase,
        max_subtasks: int = 4,
    ) -> None:
        """Initialize the decomposer.

        Args:
            llm_service: LLM for query analysis.
            max_subtasks: Maximum subtasks to generate.
        """
        self._llm = llm_service
        self._max_subtasks = max_subtasks
        self._logger = get_logger(__name__)

    async def decompose(self, query: str) -> DecompositionResult:
        """Decompose a query into subtasks if needed.

        Args:
            query: The user's original query.

        Returns:
            DecompositionResult with subtasks.
        """
        self._logger.debug(
            "Decomposing query",
            extra={"query_length": len(query)},
        )

        # Use LLM to analyze the query
        messages = [
            Message(
                role=MessageRole.SYSTEM,
                content=(
                    "You are a query analyzer. Analyze queries and decompose "
                    "them into subtasks for a video RAG system. "
                    "Respond with valid JSON only."
                ),
            ),
            Message(
                role=MessageRole.USER,
                content=DECOMPOSITION_PROMPT.format(query=query),
            ),
        ]

        try:
            response = await self._llm.generate(
                messages=messages,
                temperature=0.1,  # Low temperature for consistent output
                max_tokens=1024,
            )

            result = self._parse_decomposition(response.content, query)

            self._logger.info(
                "Query decomposition complete",
                extra={
                    "is_simple": result.is_simple,
                    "subtask_count": len(result.subtasks),
                    "modalities": [s.target_modality.value for s in result.subtasks],
                },
            )

            return result

        except Exception as e:
            self._logger.warning(
                "Query decomposition failed, using simple fallback",
                extra={"error": str(e)},
            )
            # Fallback to simple query
            return DecompositionResult(
                original_query=query,
                subtasks=[
                    SubTask(
                        id=1,
                        sub_query=query,
                        target_modality=Modality.TRANSCRIPT,
                        reasoning="Fallback to transcript search",
                        priority=1,
                    )
                ],
                is_simple=True,
                reasoning="Decomposition failed, using simple search",
            )

    def _parse_decomposition(
        self,
        llm_response: str,
        original_query: str,
    ) -> DecompositionResult:
        """Parse LLM response into DecompositionResult.

        Args:
            llm_response: Raw LLM response.
            original_query: The original query.

        Returns:
            Parsed DecompositionResult.
        """
        # Clean up response - extract JSON if wrapped in markdown
        content = llm_response.strip()
        if content.startswith("```"):
            lines = content.split("\n")
            content = "\n".join(lines[1:-1])

        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            # Try to find JSON in the response
            start = content.find("{")
            end = content.rfind("}") + 1
            if start >= 0 and end > start:
                data = json.loads(content[start:end])
            else:
                raise ValueError("No valid JSON found in response") from None

        is_simple = data.get("is_simple", True)
        reasoning = data.get("reasoning", "")

        subtasks: list[SubTask] = []
        for st_data in data.get("subtasks", [])[: self._max_subtasks]:
            modality_str = st_data.get("target_modality", "transcript")
            try:
                modality = Modality(modality_str)
            except ValueError:
                modality = Modality.TRANSCRIPT

            subtasks.append(
                SubTask(
                    id=st_data.get("id", len(subtasks) + 1),
                    sub_query=st_data.get("sub_query", original_query),
                    target_modality=modality,
                    reasoning=st_data.get("reasoning", ""),
                    priority=st_data.get("priority", 1),
                    depends_on=st_data.get("depends_on", []),
                )
            )

        # Ensure at least one subtask
        if not subtasks:
            subtasks = [
                SubTask(
                    id=1,
                    sub_query=original_query,
                    target_modality=Modality.TRANSCRIPT,
                    reasoning="Default transcript search",
                    priority=1,
                )
            ]

        return DecompositionResult(
            original_query=original_query,
            subtasks=subtasks,
            is_simple=is_simple,
            reasoning=reasoning,
        )

    def get_execution_order(self, subtasks: list[SubTask]) -> list[list[SubTask]]:
        """Get subtasks grouped by execution wave.

        Subtasks with no dependencies run first, then those depending on them, etc.

        Args:
            subtasks: List of subtasks.

        Returns:
            List of waves, each wave is a list of subtasks that can run in parallel.
        """
        waves: list[list[SubTask]] = []
        completed: set[int] = set()
        remaining = list(subtasks)

        while remaining:
            # Find subtasks that can run now
            current_wave = [st for st in remaining if st.is_ready(completed)]

            if not current_wave:
                # Circular dependency or error - just run remaining
                self._logger.warning(
                    "Circular dependency detected in subtasks",
                    extra={"remaining": [st.id for st in remaining]},
                )
                waves.append(remaining)
                break

            waves.append(current_wave)
            completed.update(st.id for st in current_wave)
            remaining = [st for st in remaining if st.id not in completed]

        return waves


SYNTHESIS_PROMPT = """\
Synthesize the results from multiple searches into a coherent answer.

Original question: {query}

Search results from different modalities:

{results_text}

Instructions:
1. Combine insights from all search results
2. Highlight connections between what was said and shown
3. Cite specific timestamps when relevant
4. If results conflict, explain the discrepancy
5. Provide a comprehensive answer using all context

Answer:"""


class ResultSynthesizer:
    """Synthesizes results from multiple subtask executions."""

    def __init__(self, llm_service: LLMServiceBase) -> None:
        """Initialize synthesizer.

        Args:
            llm_service: LLM for synthesis.
        """
        self._llm = llm_service
        self._logger = get_logger(__name__)

    async def synthesize(
        self,
        original_query: str,
        results: list[SubTaskResult],
        video_title: str,
    ) -> tuple[str, float]:
        """Synthesize subtask results into a final answer.

        Args:
            original_query: The original user query.
            results: Results from all subtasks.
            video_title: Title of the video.

        Returns:
            Tuple of (answer, confidence).
        """
        if not results:
            return (
                "No relevant information found in the video.",
                0.0,
            )

        # If only one result and it's simple, just use it directly
        if len(results) == 1 and results[0].success:
            # Format single result
            result = results[0]
            if not result.chunks:
                return (
                    "No relevant content found for your query.",
                    0.0,
                )

        # Build results text for synthesis
        results_text = self._format_results(results)

        messages = [
            Message(
                role=MessageRole.SYSTEM,
                content=(
                    f'You are answering questions about the video "{video_title}". '
                    "Use ONLY the provided search results. "
                    "Cite timestamps when referencing specific content."
                ),
            ),
            Message(
                role=MessageRole.USER,
                content=SYNTHESIS_PROMPT.format(
                    query=original_query,
                    results_text=results_text,
                ),
            ),
        ]

        response = await self._llm.generate(
            messages=messages,
            temperature=0.3,
            max_tokens=1500,
        )

        # Calculate confidence from average scores
        all_scores = []
        for result in results:
            if result.success:
                all_scores.extend(result.scores)

        confidence = sum(all_scores) / len(all_scores) if all_scores else 0.0
        confidence = min(confidence, 0.95)

        self._logger.debug(
            "Synthesis complete",
            extra={
                "answer_length": len(response.content),
                "confidence": confidence,
                "results_used": len(results),
            },
        )

        return response.content, confidence

    def _format_results(self, results: list[SubTaskResult]) -> str:
        """Format results for synthesis prompt."""
        parts = []

        for result in results:
            if not result.success:
                parts.append(
                    f"[{result.modality.value.upper()}] Search failed: {result.error}"
                )
                continue

            if not result.chunks:
                parts.append(
                    f"[{result.modality.value.upper()}] No results found for: "
                    f"{result.sub_query}"
                )
                continue

            modality_name = result.modality.value.upper()
            header = f"[{modality_name}] Results for: {result.sub_query}"
            chunks_text = []

            for i, chunk in enumerate(result.chunks[:5]):  # Limit chunks
                start_time = chunk.get("start_time", 0)
                end_time = chunk.get("end_time", 0)
                text = chunk.get("text", chunk.get("description", ""))

                # Format timestamp
                start_fmt = self._format_timestamp(start_time)
                end_fmt = self._format_timestamp(end_time)

                score = result.scores[i] if i < len(result.scores) else 0.0
                chunks_text.append(
                    f"  [{start_fmt}-{end_fmt}] (score: {score:.2f}): {text[:300]}"
                )

            parts.append(header + "\n" + "\n".join(chunks_text))

        return "\n\n".join(parts)

    @staticmethod
    def _format_timestamp(seconds: float) -> str:
        """Format seconds as MM:SS."""
        total_seconds = int(seconds)
        minutes = total_seconds // 60
        secs = total_seconds % 60
        return f"{minutes:02d}:{secs:02d}"
