"""
Index product data files into Qdrant.
Usage:
  uv run python initialize_db.py           # full index
  uv run python initialize_db.py --limit 10  # cap for testing
  uv run python initialize_db.py --fresh      # drop collection first
"""
import argparse
import json
import os

from dotenv import load_dotenv
from qdrant_client import QdrantClient

from constants import COLLECTION, DATA_FILES, EMBEDDING_DIM, EMBEDDING_MODEL, QDRANT_URL
from retrieval.indexing import index_products, product_to_chunk

load_dotenv()


def load_products(limit: int | None) -> list[dict]:
    products = []
    for path in DATA_FILES:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        print(f"  Loaded {len(data)} products from {path}")
        products.extend(data)
    if limit is not None:
        products = products[:limit]
        print(f"  Capped to {limit} products for testing")
    return products


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None, help="Max products to index (testing)")
    parser.add_argument("--fresh", action="store_true", help="Drop and recreate collection first")
    args = parser.parse_args()

    api_key = os.environ["OPENROUTER_API_KEY"]

    if args.fresh:
        client = QdrantClient(url=QDRANT_URL)
        existing = {c.name for c in client.get_collections().collections}
        if COLLECTION in existing:
            client.delete_collection(COLLECTION)
            print(f"Dropped collection '{COLLECTION}'")

    print(f"\nLoading products from {len(DATA_FILES)} file(s)...")
    products = load_products(args.limit)
    print(f"Total to index: {len(products)}\n")

    print("Sample chunk (first product):")
    print("─" * 60)
    print(product_to_chunk(products[0]))
    print("─" * 60)
    print()

    index_products(products, COLLECTION, QDRANT_URL, EMBEDDING_MODEL, EMBEDDING_DIM, api_key)

    client = QdrantClient(url=QDRANT_URL)
    info = client.get_collection(COLLECTION)
    print(f"\nCollection '{COLLECTION}' now has {info.points_count} points")

    print("\nIndexed references:")
    for p in products:
        print(f"  {p['reference']} | {p.get('name', '')[:70]}")


if __name__ == "__main__":
    main()
