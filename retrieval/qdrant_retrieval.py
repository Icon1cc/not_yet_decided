from fastembed import SparseTextEmbedding
from qdrant_client import QdrantClient
from qdrant_client.models import (
    FieldCondition,
    Filter,
    Fusion,
    FusionQuery,
    MatchValue,
    Prefetch,
    Range,
    SparseVector,
)

from retrieval.embeddings import embed_texts
from retrieval.indexing import product_to_chunk


class QdrantRetriever:
    def __init__(self, collection: str, qdrant_url: str, embedding_model: str, api_key: str):
        self._client = QdrantClient(url=qdrant_url)
        self._bm25 = SparseTextEmbedding("Qdrant/bm25")
        self._collection = collection
        self._model = embedding_model
        self._api_key = api_key

    def fetch_all(self, category: str | None = None) -> list[dict]:
        """Scroll entire collection with pagination, return all payloads (for exact_match)."""
        cat_filter = (
            Filter(must=[FieldCondition(key="category", match=MatchValue(value=category))])
            if category
            else None
        )
        payloads = []
        offset = None
        while True:
            results, offset = self._client.scroll(
                self._collection,
                scroll_filter=cat_filter,
                with_payload=True,
                limit=1_000,
                offset=offset,
            )
            payloads.extend(p.payload for p in results)
            if offset is None:
                break
        return payloads

    def retrieve(
        self,
        source: dict,
        top_k: int,
        category: str | None = None,
        min_score: float = 0.0,
        price_range: tuple[float, float] | None = None,
    ) -> list[tuple[dict, float]]:
        chunk = product_to_chunk(source)
        dense_vec = embed_texts([chunk], self._model, self._api_key)[0]
        sparse_vec = next(self._bm25.query_embed(chunk))

        must = []
        if category:
            must.append(FieldCondition(key="category", match=MatchValue(value=category)))
        if price_range is not None:
            must.append(FieldCondition(key="price_eur", range=Range(gte=price_range[0], lte=price_range[1])))
        combined_filter = Filter(must=must) if must else None

        sparse_obj = sparse_vec.as_object()
        prefetch = [
            Prefetch(query=dense_vec, using="dense", limit=top_k * 2, filter=combined_filter),
            Prefetch(
                query=SparseVector(indices=sparse_obj["indices"], values=sparse_obj["values"]),
                using="bm25",
                limit=top_k * 2,
                filter=combined_filter,
            ),
        ]
        results = self._client.query_points(
            self._collection,
            prefetch=prefetch,
            query=FusionQuery(fusion=Fusion.RRF),
            with_payload=True,
            limit=top_k,
        ).points

        return [(p.payload, p.score) for p in results if p.score >= min_score]
