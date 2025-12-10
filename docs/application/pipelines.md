# Processing Pipelines

The pipelines module provides multi-step processing workflows for complex operations that span multiple services.

**Source**: `src/application/pipelines/`

## Overview

Pipelines orchestrate multiple application services to complete complex workflows. They provide:

- Coordinated multi-step processing
- Progress tracking and reporting
- Error handling and rollback
- Resource cleanup

## Current Status

The pipelines module is currently a placeholder for future implementations. The main processing logic is currently handled directly by the `VideoIngestionService`.

```python
# src/application/pipelines/__init__.py
"""Processing pipelines."""
```

## Planned Pipelines

### IngestionPipeline

A dedicated pipeline class for video ingestion:

```python
class IngestionPipeline:
    """Orchestrates the complete video ingestion workflow."""

    def __init__(
        self,
        downloader: YouTubeDownloaderBase,
        transcriber: TranscriptionServiceBase,
        chunker: ChunkingService,
        embedder: EmbeddingOrchestrator,
        storage: VideoStorageService,
    ) -> None:
        self._downloader = downloader
        self._transcriber = transcriber
        self._chunker = chunker
        self._embedder = embedder
        self._storage = storage

    async def run(
        self,
        request: IngestVideoRequest,
        progress_callback: ProgressCallback | None = None,
    ) -> IngestVideoResponse:
        """Execute the full ingestion pipeline."""
        ...
```

### ReprocessingPipeline

Re-process existing videos with new settings:

```python
class ReprocessingPipeline:
    """Re-process videos with updated chunking/embedding settings."""

    async def run(
        self,
        video_id: str,
        new_settings: ChunkingSettings,
    ) -> ReprocessResult:
        """Re-chunk and re-embed an existing video."""
        # 1. Load existing video metadata
        # 2. Delete old chunks and embeddings
        # 3. Re-run chunking with new settings
        # 4. Re-generate embeddings
        # 5. Update metadata
        ...
```

### BatchIngestionPipeline

Ingest multiple videos in parallel:

```python
class BatchIngestionPipeline:
    """Ingest multiple videos with parallel processing."""

    async def run(
        self,
        urls: list[str],
        max_concurrent: int = 3,
        progress_callback: BatchProgressCallback | None = None,
    ) -> list[IngestVideoResponse]:
        """Ingest multiple videos with concurrency control."""
        semaphore = asyncio.Semaphore(max_concurrent)

        async def ingest_one(url: str) -> IngestVideoResponse:
            async with semaphore:
                return await self._ingestion.ingest(
                    IngestVideoRequest(url=url)
                )

        return await asyncio.gather(*[
            ingest_one(url) for url in urls
        ])
```

### CleanupPipeline

Clean up orphaned resources:

```python
class CleanupPipeline:
    """Clean up orphaned blobs, chunks, and embeddings."""

    async def run(self) -> CleanupResult:
        """Find and remove orphaned resources."""
        # 1. Find blobs without video metadata
        # 2. Find chunks without parent video
        # 3. Find embeddings without chunks
        # 4. Remove orphaned resources
        # 5. Report cleanup stats
        ...
```

## Pipeline Design Patterns

### Progress Reporting

```python
@dataclass
class PipelineProgress:
    """Progress information for pipeline execution."""

    pipeline_name: str
    current_step: str
    step_progress: float  # 0.0 to 1.0
    overall_progress: float  # 0.0 to 1.0
    message: str
    started_at: datetime
    errors: list[str]

ProgressCallback = Callable[[PipelineProgress], None]
```

### Error Handling

```python
class PipelineError(Exception):
    """Base exception for pipeline errors."""

    def __init__(
        self,
        message: str,
        step: str,
        partial_result: Any | None = None,
    ) -> None:
        self.step = step
        self.partial_result = partial_result
        super().__init__(message)


class RollbackablePipeline:
    """Pipeline with rollback capability."""

    async def run(self, request: Request) -> Result:
        completed_steps: list[str] = []

        try:
            for step in self.steps:
                await step.execute()
                completed_steps.append(step.name)
        except Exception as e:
            # Rollback completed steps in reverse order
            for step_name in reversed(completed_steps):
                await self.rollback_step(step_name)
            raise PipelineError(str(e), step.name)
```

### Resource Management

```python
class ManagedPipeline:
    """Pipeline with resource cleanup."""

    async def run(self, request: Request) -> Result:
        temp_dir = tempfile.mkdtemp()

        try:
            # Execute pipeline steps using temp_dir
            result = await self._execute(request, temp_dir)
            return result
        finally:
            # Always cleanup temp resources
            shutil.rmtree(temp_dir, ignore_errors=True)
```

## Future Enhancements

### Pipeline Registry

```python
class PipelineRegistry:
    """Registry for available pipelines."""

    _pipelines: dict[str, type[Pipeline]] = {}

    @classmethod
    def register(cls, name: str, pipeline: type[Pipeline]) -> None:
        cls._pipelines[name] = pipeline

    @classmethod
    def get(cls, name: str) -> type[Pipeline]:
        return cls._pipelines[name]

    @classmethod
    def list(cls) -> list[str]:
        return list(cls._pipelines.keys())


# Register pipelines
PipelineRegistry.register("ingest", IngestionPipeline)
PipelineRegistry.register("reprocess", ReprocessingPipeline)
PipelineRegistry.register("batch", BatchIngestionPipeline)
```

### Pipeline Middleware

```python
class PipelineMiddleware(Protocol):
    """Middleware for pipeline execution."""

    async def before_step(self, step: str, context: dict) -> None:
        ...

    async def after_step(self, step: str, context: dict, result: Any) -> None:
        ...


class LoggingMiddleware(PipelineMiddleware):
    """Log pipeline step execution."""

    async def before_step(self, step: str, context: dict) -> None:
        logger.info(f"Starting step: {step}")

    async def after_step(self, step: str, context: dict, result: Any) -> None:
        logger.info(f"Completed step: {step}")


class MetricsMiddleware(PipelineMiddleware):
    """Collect metrics for pipeline execution."""

    async def before_step(self, step: str, context: dict) -> None:
        context["step_start"] = time.perf_counter()

    async def after_step(self, step: str, context: dict, result: Any) -> None:
        duration = time.perf_counter() - context["step_start"]
        metrics.record(f"pipeline.step.{step}.duration", duration)
```

## Migration Path

The current ingestion logic in `VideoIngestionService` can be refactored to use the pipeline pattern:

```python
# Current: Logic in service
class VideoIngestionService:
    async def ingest(self, request: IngestVideoRequest) -> IngestVideoResponse:
        # All logic in one method
        ...

# Future: Service delegates to pipeline
class VideoIngestionService:
    def __init__(self, pipeline: IngestionPipeline) -> None:
        self._pipeline = pipeline

    async def ingest(self, request: IngestVideoRequest) -> IngestVideoResponse:
        return await self._pipeline.run(request)
```

This separation provides:

- Better testability (mock pipeline for service tests)
- Reusable pipeline for different entry points (REST, MCP, CLI)
- Cleaner separation of orchestration and business logic
