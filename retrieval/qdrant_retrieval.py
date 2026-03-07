from fastembed import SparseTextEmbedding
from qdrant_client import QdrantClient
from qdrant_client.models import (
    FieldCondition,
    Filter,
    IsNullCondition,
    MatchValue,
    PayloadField,
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
        sparse_vec = next(self._bm25.query_embed(chunk))

        must = []
        if category:
            must.append(FieldCondition(key="category", match=MatchValue(value=category)))
        if price_range is not None:
            must.append(FieldCondition(key="price_eur", range=Range(gte=price_range[0], lte=price_range[1])))
        combined_filter = Filter(must=must) if must else None

        sparse_obj = sparse_vec.as_object()
        # BM25-only: model number token matching outperforms dense for product IDs
        # Re-enable dense prefetch if semantic recall becomes needed
        results = self._client.query_points(
            self._collection,
            query=SparseVector(indices=sparse_obj["indices"], values=sparse_obj["values"]),
            using="bm25",
            query_filter=combined_filter,
            with_payload=True,
            limit=top_k,
        ).points

        return [(p.payload, p.score) for p in results if p.score >= min_score]

    def retrieve_multi(
        self,
        terms: list[str],
        top_k_per_term: int,
        category: str | None = None,
        product_type: str | None = None,
        price_range: tuple[float, float] | None = None,
        size_range: tuple[float, float] | None = None,
        size_unit: str | None = None,
        min_score: float = 0.0,
    ) -> list[tuple[dict, float]]:
        """
        BM25 search for each term independently, union results.
        Returns deduplicated list sorted by best score across all term queries.
        """
        must = []
        if category:
            must.append(FieldCondition(key="category", match=MatchValue(value=category)))
        if product_type:
            must.append(FieldCondition(key="product_type", match=MatchValue(value=product_type)))
        if price_range is not None:
            must.append(Filter(should=[
                FieldCondition(key="price_eur", range=Range(gte=price_range[0], lte=price_range[1])),
                IsNullCondition(is_null=PayloadField(key="price_eur")),
            ]))
        if size_range is not None:
            size_must = [FieldCondition(key="size", range=Range(gte=size_range[0], lte=size_range[1]))]
            if size_unit:
                size_must.append(FieldCondition(key="size_unit", match=MatchValue(value=size_unit)))
            must.append(Filter(should=[
                Filter(must=size_must),
                IsNullCondition(is_null=PayloadField(key="size")),
            ]))
        combined_filter = Filter(must=must) if must else None

        best: dict[str, tuple[dict, float]] = {}  # ref -> (payload, best_score)

        for term in terms:
            sparse_vec = next(self._bm25.query_embed(term))
            sparse_obj = sparse_vec.as_object()
            results = self._client.query_points(
                self._collection,
                query=SparseVector(indices=sparse_obj["indices"], values=sparse_obj["values"]),
                using="bm25",
                query_filter=combined_filter,
                with_payload=True,
                limit=top_k_per_term,
            ).points
            for p in results:
                if p.score < min_score:
                    continue
                ref = p.payload["reference"]
                if ref not in best or p.score > best[ref][1]:
                    best[ref] = (p.payload, p.score)

        return sorted(best.values(), key=lambda x: x[1], reverse=True)
