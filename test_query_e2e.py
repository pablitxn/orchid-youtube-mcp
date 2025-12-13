"""Test end-to-end query flow."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

# Load .env file
from dotenv import load_dotenv

load_dotenv()


async def test_query() -> None:  # noqa: PLR0912, PLR0915
    """Test the query service end-to-end."""
    from src.application.dtos.query import QueryModality, QueryVideoRequest
    from src.application.services.query import VideoQueryService
    from src.commons.settings.loader import get_settings
    from src.infrastructure.factory import InfrastructureFactory

    print("=" * 60)
    print("TEST END-TO-END DE QUERY")
    print("=" * 60)

    # Load settings
    print("\n1. Cargando settings...")
    settings = get_settings()
    print(f"   Vector collection: {settings.vector_db.collections.transcripts}")
    print(f"   Videos collection: {settings.document_db.collections.videos}")

    # Check API keys from settings
    openai_key = settings.embeddings.text.api_key
    if not openai_key:
        print("\n   ERROR: OPENAI API KEY no encontrada en settings")
        print("   Configura: YOUTUBE_RAG__EMBEDDINGS__TEXT__API_KEY=sk-...")
        return
    print(f"   API Key encontrada: {openai_key[:15]}...")

    # Initialize services using Factory
    print("\n2. Inicializando servicios via Factory...")
    factory = InfrastructureFactory(settings)

    vector_db = factory.get_vector_db()
    document_db = factory.get_document_db()
    embedder = factory.get_text_embedding_service()
    llm = factory.get_llm_service()

    query_service = VideoQueryService(
        text_embedding_service=embedder,
        llm_service=llm,
        vector_db=vector_db,
        document_db=document_db,
        settings=settings,
    )

    # Find video
    print("\n3. Buscando videos en MongoDB...")
    videos = await document_db.find(
        settings.document_db.collections.videos,
        {},
        limit=5,
    )
    print(f"   Videos encontrados: {len(videos)}")

    if not videos:
        print("   ERROR: No hay videos en la base de datos")
        return

    for v in videos:
        title = v.get("title", "Sin título")[:50]
        print(f"   - {v.get('id')}: {title}... (status: {v.get('status')})")

    # Select ready video
    ready_videos = [v for v in videos if v.get("status") == "ready"]
    if not ready_videos:
        print("\n   ERROR: No hay videos con status='ready'")
        print("   Los videos deben tener status='ready' para hacer queries")
        return

    video = ready_videos[0]
    video_id = video["id"]
    print(f"\n4. Usando video: {video_id}")
    print(f"   Título: {video.get('title', 'N/A')}")

    # Check vectors for this video
    print("\n5. Verificando vectores para este video...")
    vector_count = await vector_db.count(
        settings.vector_db.collections.transcripts,
        {"video_id": video_id},
    )
    print(f"   Vectores encontrados: {vector_count}")

    if vector_count == 0:
        print("   ERROR: No hay vectores para este video")
        print("   El video no tiene embeddings generados")
        return

    # Test query embedding first
    print("\n6. Probando generación de embedding...")
    query_text = "never gonna give you up"
    print(f"   Query: '{query_text}'")

    try:
        embeddings = await embedder.embed_texts([query_text])
        if embeddings:
            print(f"   Embedding generado: {len(embeddings[0].vector)} dimensiones")
            print(f"   Primeros 5 valores: {embeddings[0].vector[:5]}")
        else:
            print("   ERROR: No se generó embedding")
            return
    except Exception as e:
        print(f"   ERROR al generar embedding: {e}")
        return

    # Test direct search in vector DB
    print("\n7. Probando búsqueda directa en Qdrant...")
    try:
        results = await vector_db.search(
            collection=settings.vector_db.collections.transcripts,
            query_vector=embeddings[0].vector,
            limit=5,
            filters={"video_id": video_id},
            score_threshold=None,  # sin threshold primero
        )
        print(f"   Resultados SIN threshold: {len(results)}")
        for r in results:
            preview = r.payload.get("text_preview", "")[:40]
            print(f"   - Score: {r.score:.4f} | {preview}...")

        results_threshold = await vector_db.search(
            collection=settings.vector_db.collections.transcripts,
            query_vector=embeddings[0].vector,
            limit=5,
            filters={"video_id": video_id},
            score_threshold=0.5,
        )
        print(f"   Resultados CON threshold 0.5: {len(results_threshold)}")
    except Exception as e:
        print(f"   ERROR en búsqueda directa: {e}")
        import traceback

        traceback.print_exc()

    print("\n8. Ejecutando query via VideoQueryService...")

    request = QueryVideoRequest(
        query=query_text,
        modalities=[QueryModality.TRANSCRIPT],
        max_citations=5,
        include_reasoning=True,
        similarity_threshold=0.5,  # threshold más bajo para pruebas
    )

    try:
        response = await query_service.query(video_id, request)
        print("\n7. RESULTADOS:")
        print("-" * 50)
        print(f"Answer: {response.answer[:200]}...")
        print(f"\nConfidence: {response.confidence:.2f}")
        print(f"Chunks analizados: {response.query_metadata.chunks_analyzed}")
        print(f"Tiempo: {response.query_metadata.processing_time_ms}ms")

        print("\nCitations:")
        for i, citation in enumerate(response.citations, 1):
            ts = citation.timestamp_range.display
            score = citation.relevance_score
            print(f"  {i}. [{ts}] Score: {score:.3f}")
            print(f"     {citation.content_preview[:60]}...")

    except ValueError as e:
        print(f"\n   ERROR: {e}")
    except Exception as e:
        print(f"\n   ERROR inesperado: {type(e).__name__}: {e}")
        import traceback

        traceback.print_exc()

    print("\n" + "=" * 60)
    print("TEST COMPLETADO")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(test_query())
