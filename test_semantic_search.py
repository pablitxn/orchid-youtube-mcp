"""Diagnóstico de búsqueda semántica."""

import asyncio
import os
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))


async def test_search() -> None:  # noqa: PLR0915
    """Test semantic search step by step."""
    import openai
    from qdrant_client import QdrantClient

    print("=" * 60)
    print("DIAGNÓSTICO DE BÚSQUEDA SEMÁNTICA")
    print("=" * 60)

    # 1. Conectar a Qdrant
    print("\n1. Conectando a Qdrant...")
    qdrant = QdrantClient(host="localhost", port=6333)
    collections = qdrant.get_collections()
    print(f"   Colecciones: {[c.name for c in collections.collections]}")

    # 2. Verificar colección
    collection_name = "transcript_embeddings"
    print(f"\n2. Info de colección '{collection_name}'...")
    info = qdrant.get_collection(collection_name)
    print(f"   - Puntos: {info.points_count}")
    print(f"   - Vectores indexados: {info.indexed_vectors_count}")
    print(f"   - Dimensiones: {info.config.params.vectors.size}")
    print(f"   - Distancia: {info.config.params.vectors.distance}")

    # 3. Ver algunos puntos
    print("\n3. Puntos en la colección:")
    points = qdrant.scroll(collection_name, limit=3, with_vectors=False)[0]
    for p in points:
        print(f"   - ID: {p.id}")
        print(f"     video_id: {p.payload.get('video_id')}")
        print(f"     preview: {p.payload.get('text_preview', '')[:80]}...")

    # 4. Generar embedding para query
    print("\n4. Generando embedding para query de prueba...")
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("   ERROR: OPENAI_API_KEY no encontrada")
        return

    client = openai.OpenAI(api_key=api_key)
    query = "never gonna give you up"
    print(f"   Query: '{query}'")

    response = client.embeddings.create(model="text-embedding-3-small", input=query)
    query_vector = response.data[0].embedding
    print(f"   Vector generado: {len(query_vector)} dimensiones")

    # 5. Buscar SIN filtros
    print("\n5. Búsqueda SIN filtros...")
    results = qdrant.search(
        collection_name=collection_name,
        query_vector=query_vector,
        limit=5,
    )
    print(f"   Resultados: {len(results)}")
    for r in results:
        print(f"   - Score: {r.score:.4f}")
        print(f"     Preview: {r.payload.get('text_preview', '')[:60]}...")

    # 6. Buscar CON filtro de video_id
    video_id = "8e959d6f-c703-40d5-92f9-654fd373e12a"
    print(f"\n6. Búsqueda CON filtro video_id='{video_id}'...")
    from qdrant_client.models import FieldCondition, Filter, MatchValue

    results_filtered = qdrant.search(
        collection_name=collection_name,
        query_vector=query_vector,
        limit=5,
        query_filter=Filter(
            must=[FieldCondition(key="video_id", match=MatchValue(value=video_id))]
        ),
    )
    print(f"   Resultados: {len(results_filtered)}")
    for r in results_filtered:
        print(f"   - Score: {r.score:.4f}")
        print(f"     Preview: {r.payload.get('text_preview', '')[:60]}...")

    # 7. Buscar CON threshold
    threshold = 0.7
    print(f"\n7. Búsqueda CON score_threshold={threshold}...")
    results_threshold = qdrant.search(
        collection_name=collection_name,
        query_vector=query_vector,
        limit=5,
        score_threshold=threshold,
    )
    print(f"   Resultados: {len(results_threshold)}")
    for r in results_threshold:
        print(f"   - Score: {r.score:.4f}")
        print(f"     Preview: {r.payload.get('text_preview', '')[:60]}...")

    # 8. Probar con threshold más bajo
    threshold_low = 0.3
    print(f"\n8. Búsqueda CON score_threshold={threshold_low}...")
    results_low = qdrant.search(
        collection_name=collection_name,
        query_vector=query_vector,
        limit=5,
        score_threshold=threshold_low,
    )
    print(f"   Resultados: {len(results_low)}")
    for r in results_low:
        print(f"   - Score: {r.score:.4f}")

    print("\n" + "=" * 60)
    print("RESUMEN:")
    print("=" * 60)
    print(f"- Sin filtros: {len(results)} resultados")
    print(f"- Con video_id filter: {len(results_filtered)} resultados")
    print(f"- Con threshold 0.7: {len(results_threshold)} resultados")
    print(f"- Con threshold 0.3: {len(results_low)} resultados")

    if len(results) > 0 and len(results_threshold) == 0:
        print("\n⚠️  PROBLEMA DETECTADO: El threshold de 0.7 es muy alto!")
        min_score = results[-1].score
        max_score = results[0].score
        print(f"   Los scores están entre {min_score:.4f} y {max_score:.4f}")
        print("   Solución: Reducir similarity_threshold en config o en la query")


if __name__ == "__main__":
    asyncio.run(test_search())
