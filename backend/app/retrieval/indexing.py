"""
Qdrant indexing module for product vector storage.
"""

import argparse
import hashlib
import json
from pathlib import Path

from fastembed import SparseTextEmbedding
from qdrant_client import QdrantClient

from backend.app.services.matching import clean_specs_for_matching, extract_product_signals
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    FloatIndexParams,
    FloatIndexType,
    KeywordIndexParams,
    KeywordIndexType,
    MatchValue,
    Modifier,
    PointStruct,
    SparseIndexParams,
    SparseVector,
    SparseVectorParams,
    TextIndexParams,
    TextIndexType,
    TokenizerType,
    VectorParams,
)

from backend.app.retrieval.embeddings import embed_texts
from backend.app.retrieval.enrichment import enrich_products


def product_to_chunk(product: dict) -> str:
    lines = []
    signals = extract_product_signals(product)

    name = product.get("name")
    if name:
        lines.append(f"Product name: {name}.")

    # enrichment tags (present after enrich_products() has been called)
    tag_parts = []
    if product.get("product_type"):
        tag_parts.append(f"Product type: {product['product_type']}")
    if product.get("brand_norm"):
        tag_parts.append(f"Brand: {product['brand_norm']}")
    if product.get("size") is not None:
        unit = product.get("size_unit") or ""
        tag_parts.append(f"Size: {product['size']} {unit}".strip())
    if product.get("resolution"):
        tag_parts.append(f"Resolution: {product['resolution']}")
    if product.get("model_number"):
        tag_parts.append(f"Model number: {product['model_number']}")
    for model in sorted(signals.strong_models)[:2]:
        tag_parts.append(f"Normalized model: {model}")
    if signals.kind:
        tag_parts.append(f"Product kind: {signals.kind}")
    if signals.screen_size_inch is not None:
        tag_parts.append(f"Screen size inch: {signals.screen_size_inch}")
    if tag_parts:
        lines.append("\n".join(tag_parts))

    meta_parts = []
    for key, label in [
        ("category", "Category"),
        ("brand", "Brand"),
        ("ean", "EAN"),
        ("price_eur", "Price EUR"),
        ("retailer", "Retailer"),
    ]:
        val = product.get(key)
        if val is not None and val != "":
            meta_parts.append(f"{label}: {val}")
    if meta_parts:
        lines.append("\n".join(meta_parts))

    specs = clean_specs_for_matching(product.get("specifications"))
    if isinstance(specs, dict):
        spec_parts = [f"{k}: {v}" for k, v in specs.items() if v is not None and v != ""]
        if spec_parts:
            lines.append("Specifications:\n" + "\n".join(spec_parts))

    return "\n".join(lines)


def ensure_collection(client: QdrantClient, collection: str, dim: int) -> None:
    existing = {c.name for c in client.get_collections().collections}
    if collection in existing:
        return
    client.create_collection(
        collection_name=collection,
        vectors_config={"dense": VectorParams(size=dim, distance=Distance.COSINE)},
        sparse_vectors_config={
            "bm25": SparseVectorParams(
                index=SparseIndexParams(on_disk=False),
                modifier=Modifier.IDF,
            )
        },
    )
    for field in ("category", "brand", "retailer", "ean", "reference", "product_type", "resolution", "model_number", "brand_norm", "size_unit"):
        client.create_payload_index(collection, field, field_schema=KeywordIndexParams(type=KeywordIndexType.KEYWORD))
    client.create_payload_index(
        collection,
        "name",
        field_schema=TextIndexParams(
            type=TextIndexType.TEXT,
            tokenizer=TokenizerType.WORD,
            lowercase=True,
        ),
    )
    client.create_payload_index(
        collection,
        "price_eur",
        field_schema=FloatIndexParams(type=FloatIndexType.FLOAT),
    )
    client.create_payload_index(
        collection,
        "size",
        field_schema=FloatIndexParams(type=FloatIndexType.FLOAT),
    )


def index_products(
    products: list[dict],
    collection: str,
    qdrant_url: str,
    embedding_model: str,
    embedding_dim: int,
    api_key: str,
) -> None:
    client = QdrantClient(url=qdrant_url)
    ensure_collection(client, collection, embedding_dim)

    print("Running product enrichment (product_type, brand_norm, screen_size_inch, model_number, resolution)...")
    products = enrich_products(products, api_key)

    bm25_model = SparseTextEmbedding("Qdrant/bm25")

    batch_size = 50
    for i in range(0, len(products), batch_size):
        batch = products[i : i + batch_size]
        chunks = [product_to_chunk(p) for p in batch]

        dense_vecs = embed_texts(chunks, embedding_model, api_key)
        sparse_vecs = list(bm25_model.embed(chunks))

        points = []
        for product, dense, sparse in zip(batch, dense_vecs, sparse_vecs):
            ref = product["reference"]
            point_id = int(hashlib.md5(ref.encode()).hexdigest(), 16) % (2**63)
            clean_specs = clean_specs_for_matching(product.get("specifications"))
            payload = {
                "reference": ref,
                "name": product.get("name"),
                "brand": product.get("brand") or None,
                "brand_norm": product.get("brand_norm"),
                "category": product.get("category"),
                "ean": product.get("ean"),
                "price_eur": product.get("price_eur"),
                "retailer": product.get("retailer"),
                "url": product.get("url"),
                "image_url": product.get("image_url"),
                "specifications": clean_specs,
                # enrichment tags
                "product_type": product.get("product_type"),
                "size": product.get("size"),
                "size_unit": product.get("size_unit"),
                "model_number": product.get("model_number"),
                "resolution": product.get("resolution"),
                "chunk_text": product_to_chunk({**product, "specifications": clean_specs}),
            }
            sparse_obj = sparse.as_object()
            points.append(
                PointStruct(
                    id=point_id,
                    vector={
                        "dense": dense,
                        "bm25": SparseVector(
                            indices=sparse_obj["indices"],
                            values=sparse_obj["values"],
                        ),
                    },
                    payload=payload,
                )
            )

        client.upsert(collection_name=collection, points=points)
        print(f"  Upserted batch {i // batch_size + 1} ({len(points)} products)")

    print(f"Indexed {len(products)} products into '{collection}'")


if __name__ == "__main__":
    import os
    from dotenv import load_dotenv

    load_dotenv()

    parser = argparse.ArgumentParser()
    parser.add_argument("--data", required=True)
    parser.add_argument("--collection", default="products")
    parser.add_argument("--qdrant-url", default="http://localhost:6333")
    parser.add_argument("--embedding-model", default="openai/text-embedding-3-small")
    parser.add_argument("--embedding-dim", type=int, default=1536)
    args = parser.parse_args()

    api_key = os.environ["OPENROUTER_API_KEY"]
    with open(args.data, encoding="utf-8") as f:
        products = json.load(f)

    index_products(
        products,
        args.collection,
        args.qdrant_url,
        args.embedding_model,
        args.embedding_dim,
        api_key,
    )
