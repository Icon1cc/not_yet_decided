# Competitor Price Intelligence — Austrian Electronics Retail

Automated pipeline for discovering competitor listings of electronics products across Austrian retail websites. Given a catalog of source products, the system finds the same products on competitor sites, extracts their prices, and surfaces them through a retrieval interface backed by Qdrant.

The two main concerns are: **data collection** (scraping competitor product pages) and **retrieval** (matching source products to competitor listings with high precision).

---

## Interface

The front-end is a chat-style web application built with React, Vite, and Tailwind CSS. It is the primary entry point for querying the system.

### Starting the frontend

```bash
cd frontend
bun install
bun run dev
```

The app runs at `http://localhost:5173` by default.

### User flow

**Home screen**

![Home screen](docs/Home%20Page.png)

When the app first loads, the user sees a landing screen with two interaction paths:

1. **Upload a JSON catalog** — drag-and-drop or click the file zone to upload a `source_products_*.json` file. The file name is attached to a new session and acknowledged by the assistant.
2. **Type a natural language query** — free-text input at the bottom, or click one of the four suggested prompts ("Find competitors for cleaning products", "Match kitchen appliances under €50", etc.) to start immediately without uploading.

**Session model**

Every interaction creates a named session stored in the browser (IndexedDB via `lib/db`). Previous sessions appear in the left sidebar and can be resumed or deleted. A session tracks the uploaded file name and the full message history.

**Inside a session**

Once a session is active, the layout switches to a chat feed:

- User messages appear as right-aligned bubbles.
- If no file has been uploaded yet, the drop zone is shown inline in the chat feed.
- After sending a message, the assistant processes the query through the retrieval pipeline (exact match → Qdrant hybrid BM25+dense → LLM filtering) and responds.

**Response rendering**

The assistant response is inspected before rendering:

- If the response body parses as a JSON array where each element has `image_url` and `url` fields, it is rendered as a **product card grid** — one card per competitor match, showing the product image, name, retailer label, price in EUR, and a "View Product" link to the original retailer page.
- Otherwise the response is rendered as a plain text bubble.

![Product page](docs/Product%20Page.png)

Each product card shows:
- Product image (square crop, object-fit contain)
- Product name
- Retailer name (e.g. `AMAZON AT`, `EXPERT AT`) in small caps
- Price in EUR (`€9.88`)
- A full-width "View Product" button that opens the competitor listing in a new tab

The match count is shown above the card grid ("1 MATCH FOUND", "3 MATCHES FOUND") so the user immediately knows how many competitor listings were identified. Continuing to type in the input bar at the bottom allows follow-up queries within the same session.

**End-to-end flow summary**

```
User uploads source_products.json  or  types a query
        │
        ▼
Session created, query sent to backend
        │
        ▼
Backend: exact identifier match (EAN / GTIN / name)
        │
        ▼
Backend: Qdrant hybrid retrieval (BM25 sparse + dense, RRF fusion)
        │
        ▼
Backend: LLM match / no-match filter (Claude Sonnet, batched)
        │
        ▼
Response: [{name, retailer, price_eur, image_url, url}, ...]
        │
        ▼
Frontend renders product card grid with prices and direct links
```

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
  scraper_brave.py              # Phase 1a: Brave Search API → product URLs + snippets
  scraper_playwright.py         # Phase 1b: Playwright → full page JSON extraction
  parser_raw.py                 # Phase 2: Raw page JSON → structured product records
  match_targets.py              # Deterministic matching against visible-retailer pool
  merge_brave_to_matched.py     # Merge Brave-only results into matched output
  build_submission.py           # Format final output for submission

output/
  raw_*.json                    # Raw Playwright page data (per retailer)
  matched_*.json                # Parsed, structured product records (per retailer)
  scraped_*.json                # Brave-only scrape results

retrieval/
  indexing.py                   # Qdrant collection setup + product upsert (dense + BM25)
  qdrant_retrieval.py           # Hybrid retrieval: dense + BM25 with RRF fusion
  exact_match.py                # Deterministic field-weight exact match
  generation.py                 # LLM-based match / no-match filtering
  embeddings.py                 # Embedding API calls (OpenRouter)

initialize_db.py                # CLI: load JSON files and index into Qdrant
constants.py                    # Paths, model names, Qdrant config
```

---

## Data Collection

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

`source_products_*.json` files are auto-discovered by the scrapers. Multiple category files (tv_audio, small_appliances, large_appliances) can coexist and are merged before processing.

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

### Phase 1b — Playwright scraper (`scraper_playwright.py`)

The Playwright scraper builds on the same Brave Search discovery but visits each product URL with a headless Chromium browser (via `playwright-stealth` to reduce bot detection). For each page it extracts:

- **ld+json blocks** — schema.org Product, BreadcrumbList, and other structured data embedded in `<script type="application/ld+json">` tags
- **`__NEXT_DATA__`** — Next.js server-rendered page props
- **Hydration variables** — `__NUXT__`, `__STORE__`, `__INITIAL_STATE__`, `__APP_DATA__`, `__PRELOADED_STATE__`

The browser context is configured with an Austrian locale, timezone, and accept-language header to match the expected visitor profile for each site. Rate limiting is applied between Brave API calls (1.2s) and between page visits (2.5s). The scraper is fully resumable: already-visited URLs are tracked by MD5 hash and skipped on re-run.

### Phase 2 — Parsing (`parser_raw.py`)

The parser converts raw page data from Phase 1b into structured product records. For each page entry it runs a series of field extractors in priority order:

**Name**: schema.org `Product.name` → deep search across all embedded JSON blobs → page title (stripped of retailer suffixes) → search result title → URL slug

**Price**: schema.org `offers.price` / `lowPrice` → deep search for price keys across all blobs → regex extraction from Brave search snippets (handles European decimal format: `1.299,00 €`)

**EAN**: schema.org `gtin13` / `gtin` → deep search for `ean`, `gtin`, `barcode`, `EAN-Code`, `GTIN/EAN` → must be all-digits, 8+ characters

**Brand**: schema.org `Product.brand` → deep search for `brand`, `manufacturer`, `marke`, `hersteller` → source brand from original query → first token of product name

**Specifications**: collected from schema.org `additionalProperty` arrays, named containers (`attributes`, `specs`, `technicalDetails`, etc.), plus fallback search metadata (`_search_query`, `_search_rank`, `_search_snippets`). Nothing is filtered — the intent is to preserve as much structured data as possible for downstream matching.

Pages that returned an HTTP error or contain no extractable fields are dropped. All others are written to `matched_*.json`.

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

### Scraping hidden retailers

```bash
cd scrape

# Brave Search only (lightweight, no page visit)
python3 scraper_brave.py --input "../data/source_products_tv_&_audio.json" \
                          --output "../output/scraped_tv_audio.json"

# Brave Search + Playwright (full page extraction)
python3 scraper_playwright.py

# Parse raw Playwright output into structured records
python3 parser_raw.py
```

### Matching visible-retailer pool

```bash
cd scrape

python3 match_targets.py \
  --source "../data/source_products_tv_&_audio.json" \
  --pool   "../data/target_pool_tv_&_audio.json" \
  --output "../output/matches_tv_audio.json"
```

### Indexing into Qdrant

```bash
# Index all configured data files
uv run python initialize_db.py

# Test with 10 products, drop and recreate collection first
uv run python initialize_db.py --limit 10 --fresh
```

Data files to index are configured in `constants.py`:

```python
DATA_FILES = [
    "data/target_pool_tv_&_audio.json",
    "data/target_pool_small_appliances.json",
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
  "source_reference": "P_C2CA4D4D",
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
