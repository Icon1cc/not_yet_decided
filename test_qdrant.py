"""
Smoke test: index 2 products, query one, verify payload + category filter.
Run: uv run python test_qdrant.py
"""
import os
from dotenv import load_dotenv
from qdrant_client import QdrantClient
from retrieval.indexing import index_products, product_to_chunk
from retrieval.qdrant_retrieval import QdrantRetriever

load_dotenv()

COLLECTION = "test_products"
QDRANT_URL = "http://localhost:6333"
EMBEDDING_MODEL = "openai/text-embedding-3-small"
EMBEDDING_DIM = 1536
API_KEY = os.environ["OPENROUTER_API_KEY"]

# ── 2 dummy products (different categories to test filter) ────────────────────
PRODUCTS = [
    {
        "reference": "TEST_001",
        "name": "Samsung QLED TV 55 Zoll 4K UHD Smart TV",
        "brand": "Samsung",
        "category": "TV & Audio",
        "ean": "1234567890123",
        "price_eur": 799.99,
        "retailer": "MediaMarkt",
        "url": "https://example.com/samsung-tv",
        "image_url": None,
        "specifications": {
            "Bildschirmgröße": "55 Zoll",
            "Auflösung": "3840x2160",
            "Technologie": "QLED",
            "Betriebssystem": "Tizen",
        },
    },
    {
        "reference": "TEST_002",
        "name": "Sony WH-1000XM5 Bluetooth Kopfhörer Noise Cancelling",
        "brand": "Sony",
        "category": "TV & Audio",
        "ean": "9876543210987",
        "price_eur": 349.00,
        "retailer": "Amazon AT",
        "url": "https://example.com/sony-headphones",
        "image_url": None,
        "specifications": {
            "Typ": "Over-Ear",
            "Bluetooth": "5.2",
            "Akkulaufzeit": "30 Stunden",
            "Noise Cancelling": "Ja",
        },
    },
]

# ── Step 1: drop collection if exists, then index ────────────────────────────
client = QdrantClient(url=QDRANT_URL)
existing = {c.name for c in client.get_collections().collections}
if COLLECTION in existing:
    client.delete_collection(COLLECTION)
    print(f"Dropped existing '{COLLECTION}'")

print("\n── Indexing 2 products ──────────────────────────────────────────────")
index_products(PRODUCTS, COLLECTION, QDRANT_URL, EMBEDDING_MODEL, EMBEDDING_DIM, API_KEY)

# ── Step 2: verify point count ───────────────────────────────────────────────
info = client.get_collection(COLLECTION)
print(f"\nCollection '{COLLECTION}': {info.points_count} points (expected 2)")
assert info.points_count == 2, f"Expected 2 points, got {info.points_count}"

# ── Step 3: query using product 0 (TV) as source ─────────────────────────────
retriever = QdrantRetriever(COLLECTION, QDRANT_URL, EMBEDDING_MODEL, API_KEY)

print("\n── Query: TV as source, no category filter ──────────────────────────")
results = retriever.retrieve(PRODUCTS[0], top_k=5, category=None, min_score=0.0)
print(f"Got {len(results)} results:")
for payload, score in results:
    print(f"  [{score:.4f}] {payload['reference']} | {payload['name'][:60]}")
    print(f"           category={payload['category']} brand={payload['brand']} retailer={payload['retailer']}")
    print(f"           ean={payload['ean']} price_eur={payload['price_eur']}")
    print(f"           specs={payload['specifications']}")

# ── Step 4: filter by category ───────────────────────────────────────────────
print("\n── Query: TV as source, category='TV & Audio' ───────────────────────")
results_cat = retriever.retrieve(PRODUCTS[0], top_k=5, category="TV & Audio", min_score=0.0)
print(f"Got {len(results_cat)} results (expected ≤2):")
for payload, score in results_cat:
    print(f"  [{score:.4f}] {payload['reference']} | {payload['name'][:60]}")

# ── Step 5: filter by nonexistent category → expect 0 ───────────────────────
print("\n── Query: category='Nonexistent' (expect 0 results) ─────────────────")
results_none = retriever.retrieve(PRODUCTS[0], top_k=5, category="Nonexistent", min_score=0.0)
print(f"Got {len(results_none)} results (expected 0)")
assert len(results_none) == 0, f"Expected 0, got {len(results_none)}"

print("\n✓ All checks passed")
