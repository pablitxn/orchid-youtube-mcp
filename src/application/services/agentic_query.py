"""Advanced agentic query features.

This module contains:
- Confidence-based query refinement
- Cross-video search and synthesis
- Internal tool use during answer generation
"""

import json
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any

from src.application.dtos.query import (
    ToolCall,
    VideoResult,
)
from src.commons.telemetry import get_logger
from src.infrastructure.llm.base import LLMServiceBase, Message, MessageRole

logger = get_logger(__name__)


# =============================================================================
# Confidence-Based Query Refinement
# =============================================================================


class RefinementStrategy(str, Enum):
    """Strategies for refining low-confidence queries."""

    EXPAND_QUERY = "expand_query"
    ADJACENT_CHUNKS = "adjacent_chunks"
    LOWER_THRESHOLD = "lower_threshold"
    MULTI_QUERY = "multi_query"


@dataclass
class RefinementResult:
    """Result of a refinement attempt."""

    success: bool
    strategy: RefinementStrategy
    new_confidence: float
    additional_chunks: list[dict[str, Any]]
    expanded_query: str | None = None


QUERY_EXPANSION_PROMPT = """\
Expand this search query with synonyms and related terms to find more results.

Original query: {query}

Context: We're searching video transcripts and got low relevance results.

Return a JSON object with:
{{
    "expanded_query": "the expanded query with synonyms",
    "alternative_queries": ["alt query 1", "alt query 2"]
}}

Respond with ONLY valid JSON:"""


class QueryRefiner:
    """Refines queries when confidence is below threshold.

    Implements multiple strategies:
    1. Query expansion with synonyms
    2. Fetching adjacent chunks for more context
    3. Lowering similarity threshold
    4. Multi-query decomposition
    """

    def __init__(
        self,
        llm_service: LLMServiceBase,
        max_iterations: int = 2,
    ) -> None:
        """Initialize refiner.

        Args:
            llm_service: LLM for query expansion.
            max_iterations: Maximum refinement attempts.
        """
        self._llm = llm_service
        self._max_iterations = max_iterations
        self._logger = get_logger(__name__)

    async def expand_query(self, query: str) -> tuple[str, list[str]]:
        """Expand a query with synonyms and alternatives.

        Args:
            query: Original query.

        Returns:
            Tuple of (expanded_query, alternative_queries).
        """
        messages = [
            Message(
                role=MessageRole.USER,
                content=QUERY_EXPANSION_PROMPT.format(query=query),
            )
        ]

        try:
            response = await self._llm.generate(
                messages=messages,
                temperature=0.3,
                max_tokens=256,
            )

            content = response.content.strip()
            if content.startswith("```"):
                lines = content.split("\n")
                content = "\n".join(lines[1:-1])

            data = json.loads(content)
            expanded = data.get("expanded_query", query)
            alternatives = data.get("alternative_queries", [])

            self._logger.debug(
                "Query expanded",
                extra={
                    "original": query,
                    "expanded": expanded,
                    "alternatives_count": len(alternatives),
                },
            )

            return expanded, alternatives

        except Exception as e:
            self._logger.warning(f"Query expansion failed: {e}")
            return query, []

    def should_refine(
        self,
        confidence: float,
        threshold: float,
        iteration: int,
    ) -> bool:
        """Check if refinement should be attempted.

        Args:
            confidence: Current confidence score.
            threshold: Minimum acceptable confidence.
            iteration: Current iteration number.

        Returns:
            True if refinement should be attempted.
        """
        return confidence < threshold and iteration < self._max_iterations

    def select_strategy(
        self,
        iteration: int,  # noqa: ARG002
        previous_strategies: list[RefinementStrategy],
    ) -> RefinementStrategy:
        """Select refinement strategy for current iteration.

        Args:
            iteration: Current iteration number.
            previous_strategies: Strategies already tried.

        Returns:
            Strategy to try next.
        """
        # Priority order of strategies
        strategy_order = [
            RefinementStrategy.EXPAND_QUERY,
            RefinementStrategy.ADJACENT_CHUNKS,
            RefinementStrategy.LOWER_THRESHOLD,
            RefinementStrategy.MULTI_QUERY,
        ]

        for strategy in strategy_order:
            if strategy not in previous_strategies:
                return strategy

        # Fallback to expand_query if all tried
        return RefinementStrategy.EXPAND_QUERY


# =============================================================================
# Cross-Video Search
# =============================================================================


CROSS_VIDEO_SYNTHESIS_PROMPT = """\
Synthesize information from multiple videos to answer this question.

Question: {query}

Results from each video:
{video_summaries}

Instructions:
1. Combine insights from all videos
2. Note agreements and disagreements between sources
3. Cite which video each piece of information comes from
4. Provide a comprehensive answer

Answer:"""


class CrossVideoSearcher:
    """Searches across multiple videos and synthesizes results."""

    def __init__(self, llm_service: LLMServiceBase) -> None:
        """Initialize searcher.

        Args:
            llm_service: LLM for synthesis.
        """
        self._llm = llm_service
        self._logger = get_logger(__name__)

    async def synthesize_results(
        self,
        query: str,
        video_results: list[VideoResult],
    ) -> tuple[str, float]:
        """Synthesize results from multiple videos.

        Args:
            query: Original query.
            video_results: Results from each video.

        Returns:
            Tuple of (synthesized_answer, confidence).
        """
        if not video_results:
            return "No relevant information found in any video.", 0.0

        # Build summaries for each video
        summaries = []
        for result in video_results:
            citations_text = []
            for c in result.citations[:3]:  # Top 3 per video
                citations_text.append(
                    f"  - [{c.timestamp_range.display}]: {c.content_preview[:200]}"
                )

            summary = (
                f"**{result.video_title}** (relevance: {result.relevance_score:.2f})\n"
                + "\n".join(citations_text)
            )
            summaries.append(summary)

        video_summaries = "\n\n".join(summaries)

        messages = [
            Message(
                role=MessageRole.SYSTEM,
                content=(
                    "You synthesize information from multiple video sources. "
                    "Always cite which video information comes from."
                ),
            ),
            Message(
                role=MessageRole.USER,
                content=CROSS_VIDEO_SYNTHESIS_PROMPT.format(
                    query=query,
                    video_summaries=video_summaries,
                ),
            ),
        ]

        response = await self._llm.generate(
            messages=messages,
            temperature=0.3,
            max_tokens=1500,
        )

        # Calculate confidence from average video relevance
        avg_relevance = sum(r.relevance_score for r in video_results) / len(
            video_results
        )
        confidence = min(avg_relevance, 0.95)

        self._logger.info(
            "Cross-video synthesis complete",
            extra={
                "videos_count": len(video_results),
                "answer_length": len(response.content),
                "confidence": confidence,
            },
        )

        return response.content, confidence


# =============================================================================
# Internal Tool Use
# =============================================================================


class InternalTool(str, Enum):
    """Tools available during answer generation."""

    GET_MORE_CONTEXT = "get_more_context"
    ANALYZE_FRAME = "analyze_frame"
    COMPARE_SEGMENTS = "compare_segments"
    SEARCH_RELATED = "search_related"


@dataclass
class ToolDefinition:
    """Definition of an internal tool."""

    name: InternalTool
    description: str
    parameters: dict[str, str]


AVAILABLE_TOOLS = [
    ToolDefinition(
        name=InternalTool.GET_MORE_CONTEXT,
        description="Get more context around a specific timestamp",
        parameters={
            "timestamp": "float - center timestamp in seconds",
            "window": "float - seconds before/after to include",
        },
    ),
    ToolDefinition(
        name=InternalTool.ANALYZE_FRAME,
        description="Get detailed analysis of a specific frame",
        parameters={
            "timestamp": "float - timestamp of frame to analyze",
        },
    ),
    ToolDefinition(
        name=InternalTool.COMPARE_SEGMENTS,
        description="Compare two segments of the video",
        parameters={
            "timestamp1": "float - first segment timestamp",
            "timestamp2": "float - second segment timestamp",
        },
    ),
    ToolDefinition(
        name=InternalTool.SEARCH_RELATED,
        description="Search for related content in the video",
        parameters={
            "topic": "str - topic or concept to search for",
        },
    ),
]


def get_tools_prompt() -> str:
    """Generate prompt section describing available tools."""
    lines = ["You have access to these tools:\n"]

    for tool in AVAILABLE_TOOLS:
        params = ", ".join(f"{k}: {v}" for k, v in tool.parameters.items())
        lines.append(f"- {tool.name.value}({params})")
        lines.append(f"  {tool.description}\n")

    lines.append(
        "\nTo use a tool, respond with:\n"
        "TOOL_CALL: tool_name(param1=value1, param2=value2)\n"
        "Then wait for the result before continuing."
    )

    return "\n".join(lines)


class ToolExecutor:
    """Executes internal tools during answer generation."""

    def __init__(
        self,
        document_db: Any,
        blob_storage: Any,
        llm_service: LLMServiceBase,
        embedder: Any,
        vector_db: Any,
    ) -> None:
        """Initialize executor with required services."""
        self._document_db = document_db
        self._blob = blob_storage
        self._llm = llm_service
        self._embedder = embedder
        self._vector_db = vector_db
        self._logger = get_logger(__name__)

    async def execute(
        self,
        tool: InternalTool,
        args: dict[str, Any],
        video_id: str,
        context: dict[str, Any],
    ) -> tuple[str, ToolCall]:
        """Execute a tool and return result.

        Args:
            tool: Tool to execute.
            args: Tool arguments.
            video_id: Current video ID.
            context: Additional context (collections, etc).

        Returns:
            Tuple of (result_text, tool_call_record).
        """
        start = time.perf_counter()

        try:
            if tool == InternalTool.GET_MORE_CONTEXT:
                result = await self._get_more_context(
                    video_id=video_id,
                    timestamp=float(args.get("timestamp", 0)),
                    window=float(args.get("window", 30)),
                    context=context,
                )
            elif tool == InternalTool.ANALYZE_FRAME:
                result = await self._analyze_frame(
                    video_id=video_id,
                    timestamp=float(args.get("timestamp", 0)),
                    context=context,
                )
            elif tool == InternalTool.COMPARE_SEGMENTS:
                result = await self._compare_segments(
                    video_id=video_id,
                    timestamp1=float(args.get("timestamp1", 0)),
                    timestamp2=float(args.get("timestamp2", 0)),
                    context=context,
                )
            elif tool == InternalTool.SEARCH_RELATED:
                result = await self._search_related(
                    video_id=video_id,
                    topic=str(args.get("topic", "")),
                    context=context,
                )
            else:
                result = f"Unknown tool: {tool}"

            elapsed_ms = int((time.perf_counter() - start) * 1000)

            tool_call = ToolCall(
                tool_name=tool.value,
                arguments=args,
                result_summary=result[:200] if len(result) > 200 else result,
                timestamp_ms=elapsed_ms,
            )

            self._logger.debug(
                "Tool executed",
                extra={
                    "tool": tool.value,
                    "elapsed_ms": elapsed_ms,
                    "result_length": len(result),
                },
            )

            return result, tool_call

        except Exception as e:
            self._logger.warning(f"Tool execution failed: {e}")
            return f"Tool error: {e}", ToolCall(
                tool_name=tool.value,
                arguments=args,
                result_summary=f"Error: {e}",
                timestamp_ms=0,
            )

    async def _get_more_context(
        self,
        video_id: str,
        timestamp: float,
        window: float,
        context: dict[str, Any],
    ) -> str:
        """Get transcript chunks around a timestamp."""
        start = max(0, timestamp - window)
        end = timestamp + window

        chunks = await self._document_db.find(
            context.get("chunks_collection", "transcript_chunks"),
            {
                "video_id": video_id,
                "start_time": {"$gte": start},
                "end_time": {"$lte": end},
            },
            sort=[("start_time", 1)],
            limit=10,
        )

        if not chunks:
            return f"No content found around timestamp {timestamp}"

        texts = []
        for chunk in chunks:
            t = chunk.get("start_time", 0)
            text = chunk.get("text", "")
            texts.append(f"[{t:.1f}s] {text}")

        return "\n".join(texts)

    async def _analyze_frame(
        self,
        video_id: str,
        timestamp: float,
        context: dict[str, Any],
    ) -> str:
        """Get frame analysis at timestamp."""
        # Find nearest frame
        frames = await self._document_db.find(
            context.get("frames_collection", "frame_chunks"),
            {
                "video_id": video_id,
                "start_time": {"$lte": timestamp + 2},
            },
            sort=[("start_time", -1)],
            limit=1,
        )

        if not frames:
            return f"No frame found near timestamp {timestamp}"

        frame = next(iter(frames))
        description = frame.get("description", "No description available")

        return f"Frame at {frame.get('start_time', 0):.1f}s: {description}"

    async def _compare_segments(
        self,
        video_id: str,
        timestamp1: float,
        timestamp2: float,
        context: dict[str, Any],
    ) -> str:
        """Compare two segments of the video."""
        # Get content around both timestamps
        ctx1 = await self._get_more_context(video_id, timestamp1, 15, context)
        ctx2 = await self._get_more_context(video_id, timestamp2, 15, context)

        return (
            f"Segment 1 ({timestamp1:.0f}s):\n{ctx1}\n\n"
            f"Segment 2 ({timestamp2:.0f}s):\n{ctx2}"
        )

    async def _search_related(
        self,
        video_id: str,
        topic: str,
        context: dict[str, Any],
    ) -> str:
        """Search for related content."""
        # Generate embedding for topic
        embeddings = await self._embedder.embed_texts([topic])
        if not embeddings:
            return "Could not search for topic"

        # Search
        results = await self._vector_db.search(
            collection=context.get("vectors_collection", "transcript_embeddings"),
            query_vector=embeddings[0].vector,
            limit=5,
            score_threshold=0.3,
            filters={"video_id": video_id},
        )

        if not results:
            return f"No content found related to '{topic}'"

        # Fetch chunks
        texts = []
        for r in results[:3]:
            chunk_id = r.payload.get("chunk_id")
            if chunk_id:
                chunk = await self._document_db.find_by_id(
                    context.get("chunks_collection", "transcript_chunks"),
                    chunk_id,
                )
                if chunk:
                    t = chunk.get("start_time", 0)
                    text = chunk.get("text", "")[:200]
                    texts.append(f"[{t:.1f}s] (score: {r.score:.2f}) {text}")

        return f"Related to '{topic}':\n" + "\n".join(texts)

    def parse_tool_call(self, text: str) -> tuple[InternalTool | None, dict[str, Any]]:
        """Parse a tool call from LLM response.

        Args:
            text: LLM response text.

        Returns:
            Tuple of (tool, arguments) or (None, {}) if no tool call.
        """
        if "TOOL_CALL:" not in text:
            return None, {}

        try:
            # Extract tool call line
            for line in text.split("\n"):
                if line.strip().startswith("TOOL_CALL:"):
                    call = line.split("TOOL_CALL:")[1].strip()

                    # Parse tool_name(args)
                    paren_idx = call.index("(")
                    tool_name = call[:paren_idx].strip()
                    args_str = call[paren_idx + 1 : -1]

                    # Parse arguments
                    args: dict[str, Any] = {}
                    for arg in args_str.split(","):
                        if "=" in arg:
                            key, val = arg.split("=", 1)
                            args[key.strip()] = val.strip().strip("\"'")

                    return InternalTool(tool_name), args

        except Exception as e:
            self._logger.debug(f"Failed to parse tool call: {e}")

        return None, {}
