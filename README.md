# Competitor Price Intelligence — Austrian Electronics Retail

Automated pipeline for discovering competitor listings of electronics products across Austrian retail websites. Given a catalog of source products, the system finds the same products on competitor sites, extracts their prices, and surfaces them through a retrieval interface backed by Qdrant.

The two main concerns are: **data collection** (scraping competitor product pages) and **retrieval** (matching source products to competitor listings with high precision).

---

## Interface

The system now runs as a real frontend + backend chat application:

- Frontend: React + Vite + Tailwind (`frontend/`)
- Backend API: FastAPI (`backend/api.py`)
- Matching engine: deterministic scorer shared by CLI + API (`matching_utils.py`)

Runtime target DB loading behavior:
- Loads every `data/target_pool_*.json` file (visible retailers)
- Loads every `matched_*.json` file from `output/` or `data/` (hidden retailers), with `output/` taking precedence per filename
- If no local target files are available, the backend can use Brave web search fallback when `BRAVE_SEARCH_API_KEY` (or `BRAVE_API_KEY`) is set
- Target files are refreshed automatically on each query (no backend restart needed after adding files)
- Query intent parsing is product-agnostic: it extracts dynamic anchor tokens and product-type hints (e.g. microwave, television, dishwasher) to narrow results for any product query

### Start backend

```bash
uv sync
uv run uvicorn backend.api:app --reload --host 0.0.0.0 --port 8000
```

Health check:

```bash
curl -sS http://127.0.0.1:8000/api/v1/health
```

### Start frontend

```bash
cd frontend
npm install
npm run dev
```

The frontend runs on `http://localhost:8080` and proxies `/api/*` to `http://127.0.0.1:8000`.

### User flow

**Home screen**

![Home screen](docs/Home%20Page.png)

When the app first loads, the user sees a landing screen with two interaction paths:

1. **Upload a JSON catalog** — drag-and-drop or click the file zone to upload a `source_products_*.json` file. The file name is attached to a new session and acknowledged by the assistant.
2. **Type a natural language query** — free-text input at the bottom, or click one of the four suggested prompts ("Find competitors for cleaning products", "Match kitchen appliances under €50", etc.) to start immediately without uploading.

**Session model**

Every interaction creates a named session stored in the browser (IndexedDB via `lib/db`). Previous sessions appear in the left sidebar and can be resumed or deleted. A session tracks:

- uploaded file name
- uploaded source catalog JSON
- full chat history
- backend response payloads (cards + submission JSON)

**Inside a session**

Once a session is active, the layout switches to a chat feed:

- User messages appear as right-aligned bubbles.
- If no file has been uploaded yet, the drop zone is shown inline in the chat feed.
- After sending a message, the assistant processes the query through the retrieval pipeline (exact match → Qdrant hybrid BM25+dense → LLM filtering) and responds.

**Response rendering**

The assistant response is inspected before rendering:

- Backend responses include:
  - `answer` (summary text)
  - `cards` (UI card grid payload)
  - `submission` (scoring-ready output format)
- Cards are rendered directly in chat.
- Submission JSON is shown in an expandable block per assistant response.

![Product page](docs/Product%20Page.png)

Each product card shows:
- Product image (square crop, object-fit contain)
- Product name
- Retailer name (e.g. `AMAZON AT`, `EXPERT AT`) in small caps
- Price in EUR (`€9.88`)
- A full-width "View Product" button that opens the competitor listing in a new tab

The match count is shown above the card grid ("1 MATCH FOUND", "3 MATCHES FOUND") so the user immediately knows how many competitor listings were identified. Continuing to type in the input bar at the bottom allows follow-up queries within the same session. Filter-only follow-ups like "only under €500" reuse prior user context automatically.

**End-to-end flow summary**

```
User uploads source_products.json  or  types a query
        │
        ▼
Session created, query sent to backend
        │
        ▼
Backend: Qdrant payload prefiltering + exact identifier match (EAN / GTIN / name, additional enrichment fields (product_type, size...))
        │
        ▼
Backend: Qdrant BM25 sparse
        ▼
Backend: LLM match / no-match filter (Claude Sonnet, batched)
        │
        ▼
Response:
  answer: text summary
  cards: [{reference, source_reference, name, retailer, price_eur, image_url, url}, ...]
  submission: [{source_reference, competitors:[...]}]
  persisted output file: data/matched_ui_output.json
        │
        ▼
Frontend renders product cards + scoring-format JSON
```

### Scoring output format

The backend returns and the UI stores matches in this format:

```json
[
  {
    "source_reference": "P_49A0DBE2",
    "competitors": [
      {
        "reference": "P_0243A3DB",
        "competitor_retailer": "Visible Retailer A",
        "competitor_product_name": "Bosch Geschirrspüler Serie 4",
        "competitor_url": "https://www.retailer-a.at/product/12345",
        "competitor_price": 449.99
      }
    ]
  }
]
```

Scoring keys:

- Visible retailers: `source_reference` + `competitors[].reference`
- Hidden retailers: `source_reference` + `competitors[].competitor_url`

---

## The Problem

Austrian electronics retailers sell largely overlapping product catalogs, but tracking competitor pricing manually is impractical at scale. This system takes a list of source products — each with a name, brand, EAN, and specifications — and automatically:

1. Locates the same product on up to six competitor sites
2. Extracts structured data: name, price, EAN, brand, image, specifications
3. Indexes everything into Qdrant for fast retrieval
4. Runs a multi-stage matching pipeline to confirm which candidates are genuine matches

**Retailers covered**

| Retailer | Type | Discovery method |
|---|---|---|
| Expert AT | Hidden | Brave Search + Playwright |
| Cyberport AT | Hidden | Brave Search + Playwright |
| electronic4you.at | Hidden | Brave Search + Playwright |
| E-Tec | Hidden | Brave Search + Playwright |
| Amazon AT | Visible | Pre-supplied target pool JSON |
| MediaMarkt AT | Visible | Pre-supplied target pool JSON |

"Hidden" retailers have no structured data feed, so their product pages are scraped. "Visible" retailers supply a target pool that can be matched directly.

---

## Project Structure

```
backend/
  api.py                          # FastAPI chat endpoint (/api/v1/chat, /api/v1/health)

frontend/
  src/pages/Index.tsx           # Main chat + session UI
  src/components/
    DropZone.tsx                # JSON file upload zone
    ChatMessage.tsx             # Message renderer (text bubble or product card grid)
    ProductCard.tsx             # Single competitor match card
    SessionSidebar.tsx          # Session list + navigation
    ChatInput.tsx               # Text input bar
  src/lib/db.ts                 # IndexedDB session persistence

data/
  source_products_*.json        # Source products to match (input)
  target_pool_*.json            # Visible-retailer product pools (Amazon, MediaMarkt)

scrape/
  run_all_categories_brave.py   # Primary: auto-discover all source categories and scrape each
  scraper_brave.py              # Phase 1a: Brave Search API → product URLs + snippets
  merge_brave_to_matched.py     # Build matched_cyberport/electronic4you from Brave raw outputs
  scraper_playwright.py         # Optional Phase 1b: Playwright → full page JSON extraction
  parser_raw.py                 # Optional Phase 2: Raw page JSON → structured product records
  match_targets.py              # Deterministic matching against visible-retailer pool
  build_submission.py           # Format final output for submission

output/
  raw_brave_*.json              # Category-wise Brave discovery output (all hidden retailers)
  raw_*.json                    # Optional raw Playwright page data (per retailer)
  matched_*.json                # Final structured product records (per retailer)
  scraped_*.json                # Legacy Brave-only outputs

retrieval/
  indexing.py                   # Qdrant collection setup + product upsert (dense + BM25)
  qdrant_retrieval.py           # Hybrid retrieval: dense + BM25 with RRF fusion
  exact_match.py                # Deterministic field-weight exact match
  generation.py                 # LLM-based match / no-match filtering
  embeddings.py                 # Embedding API calls (OpenRouter)

initialize_db.py                # CLI: load JSON files and index into Qdrant
constants.py                    # Paths, model names, Qdrant config
matching_utils.py               # Shared deterministic matcher used by CLI + API
```

---

## Data Collection and Clearance

We invested explicit engineering time in repeated scrape → audit → clean cycles, not one-pass scraping. In practice, we ran category-level collections, inspected false positives and blocked pages, tightened rules (URL validators, model blocklists, dedupe, field guards), and reran with resumable outputs until the matched files contained only usable records.

### Source data format

Each source product JSON has the following shape:

```json
{
  "reference": "P_C2CA4D4D",
  "name": "Samsung QE55Q7FAAUXXN QLED 4K TV",
  "brand": "Samsung",
  "ean": "8806097123057",
  "price_eur": 799.00,
  "specifications": {
    "GTIN": "8806097123057",
    "Hersteller Modellnummer": "QE55Q7FAAUXXN",
    "Bildschirmdiagonale": "55 Zoll"
  }
}
```

`source_products_*.json` files are auto-discovered by the pipeline. Multiple category files (`tv_&_audio`, `small_appliances`, `large_appliances`) are processed category-by-category and then merged at output stage.

### Production pipeline (all categories)

The default production flow is:

1. `run_all_categories_brave.py` auto-discovers all `data/source_products_*.json` files.
2. Each category is scraped to `output/raw_brave_<category>.json`.
3. `merge_brave_to_matched.py` merges all raw category files into:
   - `output/matched_cyberport.json`
   - `output/matched_electronic4you.json`

This path is used to increase coverage even when direct page extraction is partially blocked.

### Phase 1a — Brave Search API (`scraper_brave.py`)

For each source product × each hidden retailer, the scraper constructs targeted `site:` queries and calls the Brave Search API. Query construction follows a strict priority:

1. **EAN/GTIN** — globally unique, used verbatim: `site:expert.at 8806097123057`
2. **Brand + model number** — extracted from spec fields or the product name: `site:cyberport.at Samsung QE55Q7FAAUXXN`
3. **Brand + meaningful name tokens** — fallback when no model number is available: `site:electronic4you.at Samsung QLED 4K TV`

Up to three query variants are tried per retailer per product, stopping once enough product URLs have been found. Results are deduplicated by URL and written to a resumable JSON output file — already-processed source references are skipped on re-run.

**Model number extraction** is validated against a blocklist of tokens that match model-number patterns but are not model numbers: capacity values (`500ML`, `1000ML`), wattage (`800W`, `1300W`), voltage/frequency (`230V`, `50HZ`), technology terms (`QLED`, `OLED`, `SMART`), and retailer names. Pure-digit strings are rejected as internal SKUs, and 12+ digit numbers are rejected as EAN look-alikes. A valid model token must contain both letters and digits.

Brave Search result metadata (title, description, price snippets, thumbnail) is preserved alongside each URL — this provides a price signal even when the page itself is later blocked.

**Product URL validation** is per-retailer. Each retailer has a URL shape rule:

| Retailer | URL pattern |
|---|---|
| Expert AT | contains `~pNNNN` |
| Cyberport AT | contains `/pdp/` |
| electronic4you.at | ends with `-NNNNN.html` (5–7 digits) |
| E-Tec | `/shop/produkt/NNN/` or `details.php?artnr=NNN` |

URLs that match category pages, promotional pages, or service pages are excluded before any page visit is attempted.

### Phase 1b — Optional Playwright scraper (`scraper_playwright.py`)

The Playwright scraper builds on the same Brave Search discovery but visits each product URL with a headless Chromium browser (via `playwright-stealth` to reduce bot detection). For each page it extracts:

- **ld+json blocks** — schema.org Product, BreadcrumbList, and other structured data embedded in `<script type="application/ld+json">` tags
- **`__NEXT_DATA__`** — Next.js server-rendered page props
- **Hydration variables** — `__NUXT__`, `__STORE__`, `__INITIAL_STATE__`, `__APP_DATA__`, `__PRELOADED_STATE__`

The browser context is configured with an Austrian locale, timezone, and accept-language header to match the expected visitor profile for each site. Rate limiting is applied between Brave API calls (1.2s) and between page visits (2.5s). The scraper is fully resumable: already-visited URLs are tracked by MD5 hash and skipped on re-run.

### Phase 2 — Optional parsing (`parser_raw.py`)

The parser converts raw page data from Phase 1b into structured product records. For each page entry it runs a series of field extractors in priority order:

**Name**: schema.org `Product.name` → deep search across all embedded JSON blobs → page title (stripped of retailer suffixes) → search result title → URL slug

**Price**: schema.org `offers.price` / `lowPrice` → deep search for price keys across all blobs → regex extraction from Brave search snippets (handles European decimal format: `1.299,00 €`)

**EAN**: schema.org `gtin13` / `gtin` → deep search for `ean`, `gtin`, `barcode`, `EAN-Code`, `GTIN/EAN` → must be all-digits, 8+ characters

**Brand**: schema.org `Product.brand` → deep search for `brand`, `manufacturer`, `marke`, `hersteller` → source brand from original query → first token of product name

**Specifications**: collected from schema.org `additionalProperty` arrays, named containers (`attributes`, `specs`, `technicalDetails`, etc.), plus fallback search metadata (`_search_query`, `_search_rank`, `_search_snippets`). Nothing is filtered — the intent is to preserve as much structured data as possible for downstream matching.

Pages that returned an HTTP error or contain no extractable fields are dropped. All others are written to `matched_*.json`.

### Clearance rules (quality gates)

Before writing final matched records, we apply strict acceptance rules:

- **Domain allowlist per retailer**: records are kept only if URL host matches the retailer domain (`expert.at`, `e-tec.at`, `cyberport.at`, `electronic4you.at`).
- **Retailer-specific product URL validators**: non-product pages (category, promo, service pages) are excluded.
- **Hard dedupe**: unique key is `(retailer, url)`; duplicates are removed across category files.
- **Blocked/empty extraction filtering**: entries with no usable fields or clear block/forbidden responses are dropped.
- **URL-derived mode for Cloudflare-sensitive outputs** (`matched_cyberport.json`, `matched_electronic4you.json`): name/brand/category are inferred from URL structure only; unverifiable fields remain `null` (`ean`, `price_eur`, `image_url`).
- **Minimum record validity**: if URL is invalid, source reference is missing, or both inferred name and brand are empty, the row is excluded.

### Matching against visible retailers (`match_targets.py`)

For Amazon AT and MediaMarkt AT, the target pool is available as structured JSON. Matching runs deterministically in priority order:

1. **Direct reference** — `source.reference == target.reference` (score 1.0)
2. **EAN/GTIN** — exact string match (score 0.99)
3. **ASIN** — exact string match (score 0.98)
4. **Model number** — pool index lookup, model ≥ 5 chars with both letters and digits (score 0.90)
5. **Name similarity** — Jaccard overlap of token sets ≥ 0.55, only used when no higher-confidence match exists

Name similarity uses step 5 only as a fallback to avoid the class of false positives where a model prefix (e.g. `QA10`) appears across dozens of unrelated products. A per-retailer cap of 5 results prevents Amazon from dominating the match list.

---

## Retrieval Pipeline

The retrieval system identifies competitor products for a given source product using a four-stage pipeline. The target pool (visible retailers) is indexed into Qdrant.

### Stage 0 — Semantic Enrichment (Index Time)

Before indexing, every product is enriched with structured metadata extracted via two complementary methods:

- **LLM classification** (Claude Haiku, batched): assigns a `product_type` from 16 fine-grained categories (tv, soundbar, headphone, power_cable, av_cable, speaker, hair_care, etc.)
- **Regex extraction**: `size` + `size_unit`, `model_number` (from manufacturer spec fields), `resolution` (8K/4K/FHD/HD), `brand_norm` (normalised brand name)

Enrichment tags are stored as indexed Qdrant payload fields (filterable at query time) and prepended to the BM25 chunk text (searchable as tokens). This dual representation ensures enrichment benefits both structured filtering and lexical retrieval.

### Stage 1 — Exact Identifier Match

Before any vector search, the pipeline performs a deterministic exact-match pass over the full target pool using high-signal identifiers:

| Field | Weight |
|---|---|
| EAN | 1.0 |
| GTIN (specifications) | 1.0 |
| Product name | 0.4 |

A candidate is promoted as an exact match only if its cumulative weight meets a threshold of **0.4** — requiring at minimum a name match. Exact hits are prioritised in the final candidate list regardless of BM25 score.

### Stage 2 — LLM Query Expansion + BM25 Retrieval

For each source product, an LLM generates **6 discriminative search terms** — model numbers, brand+size combinations, resolution tags — targeting the most unique identifiers in the product. Each term is independently embedded with **BM25 (Qdrant/bm25 sparse vectors)** and queried against the Qdrant index. Results are unioned and deduplicated, keeping the best score per candidate across all term queries.

The Qdrant collection stores both dense vectors (`text-embedding-3-small`, 1536 dimensions) and sparse BM25 vectors. Retrieval uses Reciprocal Rank Fusion (RRF) over prefetched dense and BM25 results, combining lexical precision with semantic recall.

Retrieval is tightly scoped via payload filters applied at the Qdrant level:

- **`product_type`** — eliminates cross-category noise (e.g. power cables matching TV queries)
- **Price range** — targets within ±30% of source price; null-price targets always included
- **Size range** — targets within ±2 units (same unit) of source size; no-size targets always included

### Stage 3 — LLM Match / No-Match Filtering

The top candidates (up to 15) are passed to an LLM (Claude Sonnet) in batches of 8. The LLM receives full product details for both source and each candidate and makes a binary match/no-match decision, filtering out near-misses that share a model family but differ in model suffix, colour, or regional variant.

The LLM outputs one decision per line in the format:

```
P_XXXXX: MATCH
P_YYYYY: NO_MATCH
```

Decisions are parsed and validated — unknown references or malformed output raise an assertion error rather than silently passing bad data.

---

## Setup

**Requirements**: Python 3.13, Docker (for Qdrant), a Brave Search API key, an OpenRouter API key.

```bash
git clone <repo>
cd <repo>

# Install dependencies
uv sync

# Install Playwright browser
uv run playwright install chromium
```

Create `scrape/.env`:

```
BRAVE_API_KEY=BSAxxxx...
```

Create `.env` in the project root:

```
OPENROUTER_API_KEY=sk-or-...
ANTHROPIC_BASE_URL=https://openrouter.ai/api/v1
ANTHROPIC_AUTH_TOKEN=sk-or-...
```

Start Qdrant:

```bash
docker run -p 6333:6333 -p 6334:6334 \
  -v "$(pwd)/qdrant_storage:/qdrant/storage:z" \
  qdrant/qdrant
```

---

## Usage

### Hidden retailers (all categories, primary flow)

```bash
cd scrape

# Full all-category run
python3 run_all_categories_brave.py

# Quick test run (limits sources per category)
python3 run_all_categories_brave.py --limit 10
```

This generates category raw files (`output/raw_brave_*.json`) and merged matched files for Cyberport/electronic4you.

### Optional deep extraction for accessible pages

```bash
cd scrape

# Full page extraction (ld+json, next/hydration blobs)
python3 scraper_playwright.py

# Parse raw page data into matched_*.json
python3 parser_raw.py
```

### Matching visible-retailer pools

```bash
cd scrape

python3 match_targets.py \
  --source "../data/source_products_tv_&_audio.json" \
  --pool   "../data/target_pool_tv_&_audio.json" \
  --output "../output/matches_tv_audio.json"

python3 match_targets.py \
  --source "../data/source_products_small_appliances.json" \
  --pool   "../data/target_pool_small_appliances.json" \
  --output "../output/matches_small_appliances.json"

python3 match_targets.py \
  --source "../data/source_products_large_appliances.json" \
  --pool   "../data/target_pool_large_appliances.json" \
  --output "../output/matches_large_appliances.json"
```

### Indexing into Qdrant

```bash
# Index all configured data files
uv run python initialize_db.py

# Test with 10 products, drop and recreate collection first
uv run python initialize_db.py --limit 10 --fresh
```

Data files to index are configured in `constants.py` (example):

```python
DATA_FILES = [
    "data/target_pool_tv_&_audio.json",
    "data/target_pool_small_appliances.json",
    "data/target_pool_large_appliances.json",
    "output/matched_expert.json",
    "output/matched_etec.json",
    "output/matched_cyberport.json",
    "output/matched_electronic4you.json",
]
```

---

## Data Format Reference

**Source product** (`data/source_products_*.json`):

```json
{
  "reference": "P_C2CA4D4D",
  "name": "Samsung QE55Q7FAAUXXN QLED 4K TV",
  "brand": "Samsung",
  "ean": "8806097123057",
  "price_eur": 799.00,
  "retailer": "MediaMarkt",
  "specifications": { "Hersteller Modellnummer": "QE55Q7FAAUXXN" }
}
```

**Matched competitor record** (`output/matched_*.json`):

```json
{
  "reference": "P_SC_A1B2C3D4",
  "retailer": "Expert AT",
  "url": "https://www.expert.at/shop/...",
  "ean": "8806097123057",
  "name": "Samsung QE55Q7FAAUXXN",
  "brand": "Samsung",
  "price_eur": 819.00,
  "image_url": "https://...",
  "specifications": { ... }
}
```
