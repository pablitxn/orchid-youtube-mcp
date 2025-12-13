# Agentic RAG Upgrades Roadmap

> Objetivo: Transformar el RAG de "request-response" a una experiencia inteligente y autónoma.

## Estado Actual

El sistema tiene bases sólidas:
- Chunking multimodal (transcript, frame, audio, video)
- Citations temporales precisas con timestamps
- Embeddings por modalidad (text + CLIP)
- LLM con soporte vision y function-calling

**Limitación**: La query es single-shot, solo texto al LLM, sin razonamiento iterativo.

---

## Upgrades Prioritarios

### 1. Query Decomposition (Agentic Subtasks)

**Status**: ✅ Implementado (`src/application/services/query_decomposer.py`)

**Problema**: Una query compleja se resuelve con una sola búsqueda vectorial.

**Solución**: El agente descompone queries en subtareas, ejecuta cada una, y sintetiza.

```
Query: "¿Qué dice sobre ML y cómo se relaciona con lo que muestra en pantalla?"

Decomposition:
  ├── subtask_1: "conceptos machine learning mencionados" → transcript search
  ├── subtask_2: "frames con código o diagramas" → frame search
  └── synthesis: fusionar contextos + reasoning
```

**Implementación**:

```python
# src/application/services/query_decomposer.py

class QueryDecomposer:
    """Descompone queries complejas en subtareas ejecutables."""

    async def decompose(self, query: str) -> list[SubTask]:
        """
        Usa LLM para analizar la query y generar subtareas.

        Returns:
            Lista de SubTask con:
            - sub_query: la query específica
            - target_modality: transcript | frame | audio | video | all
            - priority: orden de ejecución
            - depends_on: IDs de subtareas previas (para síntesis)
        """
        pass

    async def execute_subtasks(
        self,
        subtasks: list[SubTask],
        video_id: str
    ) -> list[SubTaskResult]:
        """Ejecuta subtareas en paralelo o secuencial según dependencias."""
        pass

    async def synthesize(
        self,
        results: list[SubTaskResult],
        original_query: str
    ) -> SynthesizedResponse:
        """Combina resultados de subtareas en respuesta coherente."""
        pass
```

**Prompt de descomposición**:
```
Analiza esta query y descomponla en subtareas de búsqueda:

Query: {query}

Para cada subtarea indica:
1. sub_query: búsqueda específica
2. modality: transcript | frame | audio | video
3. reasoning: por qué esta subtarea es necesaria

Reglas:
- Máximo 4 subtareas
- Si la query es simple, retorna una sola subtarea
- Considera qué modalidad tiene más chances de responder cada parte
```

---

### 2. Multimodal Message Builder

**Status**: ✅ Implementado (`src/application/services/multimodal_message.py`)

**Problema**: El LLM solo recibe texto de los chunks, no ve frames ni escucha audio.

**Solución**: Builder de mensajes que puede incluir múltiples content types según el modelo.

```python
# Configuración por modelo
ModelCapabilities:
  claude-sonnet-4-20250514:
    text: true
    image: true      # hasta 20 imágenes
    audio: false
    video: false

  claude-opus-4-20250514:
    text: true
    image: true
    audio: false
    video: false

  gpt-4o:
    text: true
    image: true
    audio: true      # con audio preview
    video: false

  gemini-2.0:
    text: true
    image: true
    audio: true
    video: true      # nativo
```

**Implementación**:

```python
# src/application/services/multimodal_message_builder.py

from enum import Enum
from dataclasses import dataclass

class ContentType(Enum):
    TEXT = "text"
    IMAGE = "image"
    AUDIO = "audio"
    VIDEO = "video"

@dataclass
class ContentBlock:
    """Bloque de contenido para mensaje multimodal."""
    type: ContentType
    content: str | bytes  # texto o URL/base64
    metadata: dict  # timestamp, source_chunk_id, etc.

@dataclass
class MultimodalMessage:
    """Mensaje con múltiples tipos de contenido."""
    role: str  # user | assistant
    blocks: list[ContentBlock]

    def to_anthropic_format(self) -> dict:
        """Convierte a formato de Anthropic Messages API."""
        pass

    def to_openai_format(self) -> dict:
        """Convierte a formato de OpenAI Chat API."""
        pass


class MultimodalMessageBuilder:
    """
    Construye mensajes multimodales según capacidades del modelo.

    Por defecto solo incluye texto.
    Se pueden habilitar modalidades adicionales.
    """

    def __init__(
        self,
        model_id: str,
        enabled_modalities: set[ContentType] | None = None
    ):
        self.model_id = model_id
        self.capabilities = self._get_model_capabilities(model_id)

        # Default: solo texto
        self.enabled = enabled_modalities or {ContentType.TEXT}

        # Validar que el modelo soporta las modalidades habilitadas
        self._validate_modalities()

    def add_text(self, text: str, metadata: dict = None) -> "MultimodalMessageBuilder":
        """Agrega bloque de texto."""
        pass

    def add_image(
        self,
        image_url: str | None = None,
        image_base64: bytes | None = None,
        metadata: dict = None
    ) -> "MultimodalMessageBuilder":
        """Agrega imagen si está habilitado y el modelo lo soporta."""
        if ContentType.IMAGE not in self.enabled:
            return self  # Skip silently
        if not self.capabilities.image:
            return self  # Model doesn't support
        # Add image block
        pass

    def add_audio(
        self,
        audio_url: str | None = None,
        audio_base64: bytes | None = None,
        metadata: dict = None
    ) -> "MultimodalMessageBuilder":
        """Agrega audio si está habilitado y el modelo lo soporta."""
        pass

    def add_video(
        self,
        video_url: str | None = None,
        metadata: dict = None
    ) -> "MultimodalMessageBuilder":
        """Agrega video si está habilitado y el modelo lo soporta."""
        pass

    def add_chunk_context(
        self,
        chunk: BaseChunk,
        include_modalities: set[ContentType] | None = None
    ) -> "MultimodalMessageBuilder":
        """
        Agrega contexto de un chunk según su tipo.

        - TranscriptChunk → texto
        - FrameChunk → imagen (si habilitado)
        - AudioChunk → audio (si habilitado)
        - VideoChunk → video (si habilitado)
        """
        modalities = include_modalities or self.enabled

        if isinstance(chunk, TranscriptChunk):
            self.add_text(chunk.text, {"timestamp": chunk.timestamp_range})

        elif isinstance(chunk, FrameChunk) and ContentType.IMAGE in modalities:
            self.add_image(chunk.blob_url, metadata={"frame_number": chunk.frame_number})

        # ... etc

        return self

    def build(self) -> MultimodalMessage:
        """Construye el mensaje final."""
        pass
```

**Uso en QueryService**:

```python
# En query_video:

async def query_video(self, request: QueryRequest) -> QueryResponse:
    # ... búsqueda vectorial ...

    # Construir mensaje multimodal con contexto
    builder = MultimodalMessageBuilder(
        model_id=self.settings.llm.model,
        enabled_modalities=request.enabled_modalities  # Nuevo campo
    )

    for chunk in context_chunks:
        builder.add_chunk_context(chunk)

    builder.add_text(f"\n\nPregunta: {request.query}")

    message = builder.build()

    # Enviar al LLM
    response = await self.llm.generate(message)
```

---

## Upgrades Secundarios

### 3. Vision-Augmented Responses

**Status**: ✅ Implementado (en `_generate_answer`)

Cuando `enabled_content_types.image=True`:
- Para chunks de tipo frame: agrega la imagen directamente
- Para chunks de transcript: busca frames cercanos (±3s) y los incluye
- El LLM "ve" lo que el video muestra mientras responde

### 4. Confidence Loop (Iterative Refinement)

**Status**: ✅ Implementado (`query_with_refinement`)

```python
async def query_with_refinement(self, query: str, video_id: str) -> QueryResponse:
    response = await self.query_video(query, video_id)

    if response.confidence < 0.7:
        # Estrategia 1: Expandir query
        expanded = await self.expand_query(query)
        response = await self.query_video(expanded, video_id)

    if response.confidence < 0.7:
        # Estrategia 2: Buscar en chunks adyacentes
        neighbors = await self.get_temporal_neighbors(response.citations)
        response = await self.requery_with_context(query, neighbors)

    return response
```

### 4. Vision-Augmented Responses

**Status**: 🔲 Pendiente (depende de #2)

- Enviar frames relevantes junto con texto
- El LLM "ve" lo que el video muestra
- Respuestas que integran contexto visual

### 5. Cross-Video Synthesis

**Status**: ✅ Implementado (`query_across_videos`)

```python
async def query_across_videos(
    self,
    query: str,
    video_ids: list[str] | None = None  # None = todos
) -> CrossVideoResponse:
    """Busca y sintetiza información de múltiples videos."""
    pass
```

### 6. Tool-Use Interno (Agentic RAG)

**Status**: ✅ Implementado (`query_with_tools`)

El LLM puede llamar herramientas durante la generación:
- `get_more_context(timestamp, window=30s)`
- `analyze_frame(frame_id)`
- `detect_speaker(chunk_id)`
- `compare_segments(chunk1, chunk2)`

### 7. Active Re-ranking con LLM

**Status**: 🔲 Pendiente

```
Vector search → Top 20 candidatos
LLM re-ranks → "¿Cuáles son realmente relevantes para esta query?"
Final → Top 5 más precisas
```

### 8. Follow-up Suggestions

**Status**: 🔲 Pendiente

```python
@dataclass
class QueryResponse:
    answer: str
    citations: list[Citation]
    confidence: float
    suggested_followups: list[str]  # Nuevo
```

---

## Orden de Implementación

| # | Feature | Depende de | Impacto | Status |
|---|---------|------------|---------|--------|
| 1 | Multimodal Message Builder | - | 🔥🔥🔥 | ✅ Done |
| 2 | Query Decomposition | - | 🔥🔥🔥 | ✅ Done |
| 3 | Vision-Augmented | #1 | 🔥🔥🔥 | ✅ Done |
| 4 | Confidence Loop | - | 🔥🔥 | ✅ Done |
| 5 | Cross-Video | #2 | 🔥🔥 | ✅ Done |
| 6 | Tool-Use Interno | #1, #2 | 🔥🔥🔥🔥 | ✅ Done |

---

## Notas Técnicas

### Model Capabilities Registry

Mantener un registro de qué soporta cada modelo:

```python
# src/commons/model_capabilities.py

MODEL_CAPABILITIES = {
    "claude-sonnet-4-20250514": {
        "text": True,
        "image": True,
        "max_images": 20,
        "audio": False,
        "video": False,
        "context_window": 200_000,
    },
    "gpt-4o": {
        "text": True,
        "image": True,
        "max_images": 10,
        "audio": True,  # Preview
        "video": False,
        "context_window": 128_000,
    },
    "gemini-2.0-flash": {
        "text": True,
        "image": True,
        "audio": True,
        "video": True,  # Nativo
        "context_window": 1_000_000,
    },
}
```

### Request Schema Update

```python
class QueryRequest(BaseModel):
    query: str
    video_id: str
    max_citations: int = 5
    similarity_threshold: float = 0.5

    # Nuevos campos para agentic features
    enable_decomposition: bool = False
    enabled_modalities: list[ContentType] = [ContentType.TEXT]
    enable_refinement: bool = False
```
