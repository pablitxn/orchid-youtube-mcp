"""Test Qdrant search using an existing vector."""

import json
import urllib.request

BASE = "http://localhost:6333"

# 1. Get an existing point with its vector
print("1. Obteniendo un vector existente...")
req = urllib.request.Request(
    f"{BASE}/collections/transcript_embeddings/points/scroll",
    data=json.dumps({"limit": 1, "with_vector": True}).encode(),
    headers={"Content-Type": "application/json"},
    method="POST",
)
with urllib.request.urlopen(req) as resp:
    data = json.load(resp)

point = data["result"]["points"][0]
vector = point["vector"]
point_id = point["id"]
print(f"   Usando vector del punto: {point_id}")
print(f"   Preview: {point['payload'].get('text_preview', '')[:60]}...")

# 2. Search WITHOUT filters or threshold
print("\n2. Búsqueda SIN filtros...")
search_req = urllib.request.Request(
    f"{BASE}/collections/transcript_embeddings/points/search",
    data=json.dumps({"vector": vector, "limit": 5, "with_payload": True}).encode(),
    headers={"Content-Type": "application/json"},
    method="POST",
)
with urllib.request.urlopen(search_req) as resp:
    results = json.load(resp)

print(f"   Resultados: {len(results['result'])}")
for r in results["result"]:
    print(
        f"   - Score: {r['score']:.4f} | {r['payload'].get('text_preview', '')[:50]}..."
    )

# 3. Search WITH threshold 0.7
print("\n3. Búsqueda CON score_threshold=0.7...")
search_req2 = urllib.request.Request(
    f"{BASE}/collections/transcript_embeddings/points/search",
    data=json.dumps(
        {"vector": vector, "limit": 5, "with_payload": True, "score_threshold": 0.7}
    ).encode(),
    headers={"Content-Type": "application/json"},
    method="POST",
)
with urllib.request.urlopen(search_req2) as resp:
    results2 = json.load(resp)

print(f"   Resultados: {len(results2['result'])}")
for r in results2["result"]:
    print(f"   - Score: {r['score']:.4f}")

# 4. Search WITH video_id filter
print("\n4. Búsqueda CON filtro video_id...")
video_id = "8e959d6f-c703-40d5-92f9-654fd373e12a"
search_req3 = urllib.request.Request(
    f"{BASE}/collections/transcript_embeddings/points/search",
    data=json.dumps(
        {
            "vector": vector,
            "limit": 5,
            "with_payload": True,
            "filter": {"must": [{"key": "video_id", "match": {"value": video_id}}]},
        }
    ).encode(),
    headers={"Content-Type": "application/json"},
    method="POST",
)
with urllib.request.urlopen(search_req3) as resp:
    results3 = json.load(resp)

print(f"   Resultados: {len(results3['result'])}")
for r in results3["result"]:
    print(f"   - Score: {r['score']:.4f} | ID: {r['id']}")

print("\n" + "=" * 50)
print("La búsqueda en Qdrant funciona correctamente!")
print("=" * 50)
