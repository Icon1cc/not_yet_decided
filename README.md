# not_yet_decided

## Retrieval Pipeline

The matching pipeline identifies competitor products across retailers using a multi-stage retrieval architecture combining exact identifier matching, semantic enrichment, and LLM-guided reranking.

### Stage 0 — Semantic Enrichment (Index Time)

Before indexing, every product is enriched with structured metadata extracted via two complementary methods:

- **LLM classification** (Claude Haiku, batched): assigns a `product_type` from 16 fine-grained categories (tv, soundbar, headphone, power_cable, av_cable, speaker, hair_care, etc.)
- **Regex extraction**: `size` + `size_unit`, `model_number` (from manufacturer spec fields), `resolution` (8K/4K/FHD/HD), `brand_norm` (normalised brand name)

Enrichment tags are stored as indexed Qdrant payload fields (filterable at query time) **and** prepended to the BM25 chunk text (searchable as tokens). This dual representation ensures enrichment benefits both structured filtering and lexical retrieval.

### Stage 1 — Exact Identifier Match

Before any vector search, the pipeline performs a deterministic exact-match pass over the full target pool using high-signal identifiers:

| Field | Weight |
|-------|--------|
| EAN | 1.0 |
| GTIN (specifications) | 1.0 |
| Product name | 0.4 |

A candidate is promoted as an exact match only if its cumulative weight meets a threshold of **0.4** — requiring at minimum a name match. Pure price-based matches are excluded by design. Exact hits are prioritised in the final candidate list regardless of BM25 score.

### Stage 2 — LLM Query Expansion + BM25 Retrieval

For each source product, an LLM generates **6 discriminative search terms** — model numbers, brand+size combinations, resolution tags — targeting the most unique identifiers in the product. Each term is independently embedded with **BM25 (Qdrant/bm25 sparse vectors)** and queried against the Qdrant index. Results are unioned and deduplicated, keeping the best score per candidate across all term queries.

Retrieval is tightly scoped via payload filters applied at the Qdrant level:

- **`product_type`** — eliminates cross-category noise (e.g. power cables matching TV queries)
- **Price range** — targets within ±30% of source price; null-price targets always included
- **Size range** — targets within ±2 units (same unit) of source size; no-size targets always included

### Stage 3 — LLM Match / No-Match Filtering

The top candidates (up to 15) are passed to an LLM (Claude Sonnet) in batches of 8. The LLM receives full product details for both source and each candidate and makes a binary match/no-match decision, filtering out near-misses that share a model family but differ in model suffix, colour, or regional variant.

## Quick Start

```bash
# Clone the repository
git clone
cd not_yet_decided

# add to .env file:
OPENROUTER_API_KEY=
ANTHROPIC_BASE_URL=
ANTHROPIC_AUTH_TOKEN=OPENROUTER_API_KEY
```

Start qdrant db:

```bash
docker run -p 6333:6333 -p 6334:6334 -v "<PATH_TO_PROJECT>\qdrant_storage:/qdrant/storage:z" qdrant/qdrant
```

Initialize qdrant db from jsons:

```bash
uv run python initialize_db.py --limit 10 --fresh
```