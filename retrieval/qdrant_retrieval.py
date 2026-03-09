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

from constants import SCRAPED_CATEGORY
from retrieval.embeddings import embed_texts
from retrieval.indexing import product_to_chunk

_VALID_TARGET_MODES = ("visible", "scraped", "all")


def _category_condition(target_mode: str, category: str | None) -> Filter | None:
    """Build a Qdrant filter clause for the target mode + category."""
    if target_mode == "scraped":
        return Filter(must=[FieldCondition(key="category", match=MatchValue(value=SCRAPED_CATEGORY))])
    if target_mode == "visible":
        if category:
            return Filter(must=[FieldCondition(key="category", match=MatchValue(value=category))])
        return None
    # all
    if category:
        return Filter(should=[
            FieldCondition(key="category", match=MatchValue(value=category)),
            FieldCondition(key="category", match=MatchValue(value=SCRAPED_CATEGORY)),
        ])
    return None


class QdrantRetriever:
    def __init__(self, collection: str, qdrant_url: str, embedding_model: str, api_key: str,
                 target_mode: str = "visible"):
        assert target_mode in _VALID_TARGET_MODES, f"target_mode must be one of {_VALID_TARGET_MODES}"
        self._client = QdrantClient(url=qdrant_url)
        self._bm25 = SparseTextEmbedding("Qdrant/bm25")
        self._collection = collection
        self._model = embedding_model
        self._api_key = api_key
        self._target_mode = target_mode

    def fetch_all(self, category: str | None = None) -> list[dict]:
        """Scroll entire collection with pagination, return all payloads (for exact_match)."""
        cat_filter = _category_condition(self._target_mode, category)
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
        cat_cond = _category_condition(self._target_mode, category)
        if cat_cond:
            must.append(cat_cond)
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
        brand_norm: str | None = None,
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
        cat_cond = _category_condition(self._target_mode, category)
        if cat_cond:
            must.append(cat_cond)
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

        # brand-filtered variant: same filter + brand constraint (soft boost, not hard exclusion)
        brand_filter = None
        if brand_norm:
            brand_must = list(must) + [FieldCondition(key="brand_norm", match=MatchValue(value=brand_norm))]
            brand_filter = Filter(must=brand_must)

        BRAND_BOOST = 2.0  # additive score bonus for brand-matching hits

        best: dict[str, tuple[dict, float]] = {}  # ref -> (payload, best_score)

        for term in terms:
            sparse_vec = next(self._bm25.query_embed(term))
            sparse_obj = sparse_vec.as_object()

            # pass 1: unfiltered (or category/type filtered) — full pool
            results = self._client.query_points(
                self._collection,
                query=SparseVector(indices=sparse_obj["indices"], values=sparse_obj["values"]),
                using="bm25",
                query_filter=combined_filter,
                with_payload=True,
                limit=top_k_per_term,
            ).points

            # pass 2: brand-boosted — smaller pool, same top_k, scores get a bonus
            brand_results = []
            if brand_filter is not None:
                brand_results = self._client.query_points(
                    self._collection,
                    query=SparseVector(indices=sparse_obj["indices"], values=sparse_obj["values"]),
                    using="bm25",
                    query_filter=brand_filter,
                    with_payload=True,
                    limit=top_k_per_term,
                ).points

            brand_refs = {p.payload["reference"] for p in brand_results}

            new_hits = 0
            for p in list(results) + list(brand_results):
                if p.score < min_score:
                    continue
                ref = p.payload["reference"]
                score = p.score + (BRAND_BOOST if ref in brand_refs else 0.0)
                is_new = ref not in best
                if is_new or score > best[ref][1]:
                    best[ref] = (p.payload, score)
                if is_new:
                    new_hits += 1
            print(f"    [bm25] term={term!r:40s} hits={len(results):3d} brand_hits={len(brand_results):3d}  new_unique={new_hits:3d}  total_pool={len(best):3d}")

        ranked = sorted(best.values(), key=lambda x: x[1], reverse=True)
        print(f"    [bm25] final pool: {len(ranked)} candidates")
        for doc, score in ranked[:5]:
            print(f"      {score:.3f} {doc['reference']} | {(doc.get('name') or '')[:60]}")
        return ranked
