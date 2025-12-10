# Embeddings

Vector representations of chunks used for semantic search.

## Model Definition

```python
from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, Field


class EmbeddingVector(BaseModel):
    """
    A vector embedding associated with a chunk.

    Embeddings are stored in the vector database and used
    for semantic similarity search.
    """

    id: UUID = Field(description="Unique embedding identifier")
    chunk_id: UUID = Field(description="Reference to source chunk")
    video_id: UUID = Field(description="Reference to parent video (denormalized)")
    modality: ChunkModality = Field(description="Modality of the source chunk")
    vector: list[float] = Field(description="The embedding vector")
    model: str = Field(description="Model used to generate this embedding")
    dimensions: int = Field(description="Vector dimensionality")
    created_at: datetime = Field(description="When this embedding was created")

    def __len__(self) -> int:
        return len(self.vector)
```

## Embedding Dimensions

| Modality | Model | Dimensions |
|----------|-------|------------|
| **Transcript** | OpenAI text-embedding-3-small | 1536 |
| **Transcript** | OpenAI text-embedding-3-large | 3072 |
| **Frame** | CLIP ViT-B/32 | 512 |
| **Frame** | CLIP ViT-L/14 | 768 |
| **Video** | Text description embedding | 1536 |
| **Audio** | Text description embedding | 1536 |

## Example

```python
from uuid import uuid4
from datetime import datetime

embedding = EmbeddingVector(
    id=uuid4(),
    chunk_id=transcript_chunk.id,
    video_id=video.id,
    modality=ChunkModality.TRANSCRIPT,
    vector=[0.123, -0.456, 0.789, ...],  # 1536 dimensions
    model="text-embedding-3-small",
    dimensions=1536,
    created_at=datetime.utcnow()
)

print(f"Embedding has {len(embedding)} dimensions")  # 1536
```

## Storage in Qdrant

Embeddings are stored in Qdrant collections:

```python
# Create collection for transcript embeddings
await qdrant.create_collection(
    collection_name="transcript_embeddings",
    vectors_config=VectorParams(
        size=1536,
        distance=Distance.COSINE
    )
)

# Upsert embedding
await qdrant.upsert(
    collection_name="transcript_embeddings",
    points=[
        PointStruct(
            id=str(embedding.id),
            vector=embedding.vector,
            payload={
                "chunk_id": str(embedding.chunk_id),
                "video_id": str(embedding.video_id),
                "modality": embedding.modality.value,
                "start_time": chunk.start_time,
                "end_time": chunk.end_time
            }
        )
    ]
)
```

## Collections

| Collection | Modality | Dimensions | Distance |
|------------|----------|------------|----------|
| `transcript_embeddings` | Transcript | 1536 | Cosine |
| `frame_embeddings` | Frame | 512 | Cosine |
| `video_embeddings` | Video | 1536 | Cosine |
| `audio_embeddings` | Audio | 1536 | Cosine |

## Similarity Search

```python
# Search for similar transcript chunks
results = await qdrant.search(
    collection_name="transcript_embeddings",
    query_vector=query_embedding,
    query_filter=Filter(
        must=[
            FieldCondition(
                key="video_id",
                match=MatchValue(value=str(video_id))
            )
        ]
    ),
    limit=10,
    score_threshold=0.7
)

# Results contain matching chunk IDs with similarity scores
for result in results:
    print(f"Chunk {result.payload['chunk_id']}: {result.score:.3f}")
```

## Embedding Generation

### Text Embeddings

```python
from openai import AsyncOpenAI

client = AsyncOpenAI()

async def embed_text(text: str) -> list[float]:
    response = await client.embeddings.create(
        model="text-embedding-3-small",
        input=text
    )
    return response.data[0].embedding
```

### Image Embeddings

```python
import torch
from transformers import CLIPProcessor, CLIPModel
from PIL import Image

model = CLIPModel.from_pretrained("openai/clip-vit-base-patch32")
processor = CLIPProcessor.from_pretrained("openai/clip-vit-base-patch32")

def embed_image(image: Image.Image) -> list[float]:
    inputs = processor(images=image, return_tensors="pt")
    with torch.no_grad():
        features = model.get_image_features(**inputs)
    return features[0].tolist()
```

## Cross-Modal Search

Since text and image embeddings use different models, cross-modal search requires:

1. **Text-to-Text**: Query text → transcript embeddings
2. **Text-to-Image**: Query text (via CLIP) → frame embeddings
3. **Image-to-Image**: Query image → frame embeddings

```python
async def multimodal_search(
    query: str,
    video_id: UUID,
    include_transcripts: bool = True,
    include_frames: bool = True
) -> list[SearchResult]:
    results = []

    if include_transcripts:
        # Text embedding for transcripts
        text_vector = await embed_text(query)
        transcript_results = await qdrant.search(
            collection_name="transcript_embeddings",
            query_vector=text_vector,
            query_filter=video_filter(video_id),
            limit=10
        )
        results.extend(transcript_results)

    if include_frames:
        # CLIP text embedding for frames
        clip_vector = embed_text_with_clip(query)
        frame_results = await qdrant.search(
            collection_name="frame_embeddings",
            query_vector=clip_vector,
            query_filter=video_filter(video_id),
            limit=5
        )
        results.extend(frame_results)

    return sorted(results, key=lambda r: r.score, reverse=True)
```

## Related

- [Chunks](chunks.md) - Source content for embeddings
- [Citations](citations.md) - Using embeddings for retrieval
- [Infrastructure: Embeddings](../infrastructure/ai/embeddings.md) - Implementation details
