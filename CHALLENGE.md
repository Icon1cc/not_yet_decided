# Electronics Competitor Product Matching Challenge

**Duration: 8 hours | Teams of 2-4**

**Web App: [hackathon-production-49ca.up.railway.app](https://hackathon-production-49ca.up.railway.app/)**

---

## The Business Problem

You work for an electronics retailer operating in the Austrian market. Your catalog contains **91 branded products** (from manufacturers like Bosch, Samsung, LG, Philips, etc.) across three categories.

The challenge: **Match your source products to equivalent products sold by competitor retailers** — both from a provided target pool and by scraping additional retailer websites.

Why does this matter?
- **Pricing intelligence**: Know how your prices compare across the market
- **Market coverage**: Understand which competitors carry which products
- **Competitive analysis**: Track product availability and pricing across retailers

---

## Overview

You receive **91 source products** and a **target pool of ~5,800 products** from two visible Austrian retailers. Your job:

1. **Match** source products to the correct target products in the provided pool
2. **Scrape** four additional retailer websites to find more matches

```
Source Product (yours)          Target Products (find the matches)
========================        ===================================
Bosch Dishwasher X100    --->   Retailer A: Bosch Dishwasher X100 (match!)
                          --->   Retailer B: Bosch Dishwasher X100 (match!)
                          --->   Retailer C: Bosch Dishwasher X100 (scrape & match!)
                          --->   Retailer D: Bosch X100 (scrape & match!)
```

---

## Categories

Products are organized into three categories, released progressively during the challenge:

| Category | Source Products | Target Pool Size |
|----------|---------------|-----------------|
| **Large Appliances** | 44 | ~3,500 |
| **Small Appliances** | 30 | ~1,700 |
| **TV & Audio** | 17 | ~560 |

Categories are released by the organizers during the event. When a category is released, you can browse and download the data in the web app.

---

## Retailers

### Visible Retailers (target pool provided)

Target products from two Austrian electronics retailers are available in the web app for download. Match source products against them. The retailer names are visible in the data once you log in.

### Hidden Retailers (you must scrape)

These retailers are NOT in the provided data. You must scrape their websites to discover matching products.

| Retailer | Website |
|----------|---------|
| **Expert AT** | [expert.at](https://www.expert.at) |
| **Cyberport AT** | [cyberport.at](https://www.cyberport.at) |
| **electronic4you.at** | [electronic4you.at](https://www.electronic4you.at) |
| **E-Tec** | [e-tec.at](https://www.e-tec.at) |

---

## Web App

**URL: [hackathon-production-49ca.up.railway.app](https://hackathon-production-49ca.up.railway.app/)**

Log in with your GitHub account. The organizers will assign you to a team.

### Pages

| Page | What it does |
|------|-------------|
| **Challenge** | Overview of the task, retailers, and scoring breakdown |
| **Data Explorer** | Browse source products and target pool per category. Download JSON files. See sample solutions. |
| **Submit** | Upload your results per category. Get instant scoring feedback. |
| **Leaderboard** | Live rankings. Total score = sum of best score per category. |

### Data Explorer

Each released category tab shows:
- **Sample Solutions** at the top — example correct matches so you understand the expected format
- **Source Products** — the products you need to find matches for (collapsible, with search)
- **Target Pool** — all visible retailer products in that category (collapsible, with search)

Both tables have **Download** buttons to export JSON for use in your scripts.

---

## Evaluation

### Automated Scoring (100 points)

Submit **one JSON file per category** containing all your matched links. The system automatically scores against both visible and hidden retailer ground truth.

#### Matching Score (50 points) — Visible Retailers

How well did you match source products to the provided target pool (visible retailers)?

| Component | Points | Description |
|-----------|--------|-------------|
| Recall | 30 | How many correct links did you find? (correct / total ground truth) |
| Precision | 10 | How accurate are your submissions? (correct / total submitted) |
| Coverage | 10 | How many source products have at least one correct match? |

#### Scraping Score (50 points) — Hidden Retailers

How well did you find and match products from the scraped retailers (Expert AT, Cyberport AT, electronic4you.at, E-Tec)?

| Component | Points | Description |
|-----------|--------|-------------|
| Recall | 30 | How many correct hidden links did you find? |
| Precision | 10 | How accurate are your scraped matches? |
| Coverage | 10 | How many source products have at least one correct scraped match? |

#### Leaderboard

Your total score is the **sum of your best score per category**. So if you score 80/100 on Large Appliances and 60/100 on Small Appliances, your total is 140.

### System Demo (Jury Evaluation)

**This challenge is not just about the matching score.** The jury will also evaluate the **system you build**. Think of it as building a real product matching tool that could be used in production. Be creative!

#### System Maturity
- How mature is the overall architecture? Authentication, proper database, vector/RAG search?
- Which technologies do you use to properly search for and match products?
- How do you deal with generic, messy, or inconsistent product attributes?

#### User Experience
- Is there a UI? Chat-based interface? Smart attribute entry?
- Can you search for any product by any criteria?
- How fast is the experience? Start typing and immediately see results? Can you iterate back and forth with results?

#### Reusability & Flexibility
- Can you easily upload a new batch of data points and scrape again?
- Can the scraping/matching flow be adjusted? E.g. "Only look for products of Brand X"
- Is the system generic enough to work with different product categories or retailers?

#### Creativity
- Surprise us! There is no single right approach.
- Novel matching strategies, clever UX, smart automation — anything goes.
- Think like you're building a real product for a real user.

---

## Submission Format

Upload a JSON file per category via the **Submit** page. Select the category, choose your file, and click Score.

```json
[
  {
    "source_reference": "P_01B794CD",
    "competitors": [
      {
        "reference": "P_43E3D659",
        "competitor_retailer": "Retailer A",
        "competitor_product_name": "KHG Mikrowelle MW-20GSD mit Grill 20l",
        "competitor_url": "https://www.retailer-a.at/product/12345",
        "competitor_price": 49.99
      },
      {
        "reference": "P_F44B8CBC",
        "competitor_retailer": "Expert AT",
        "competitor_product_name": "Caso Pro Gourmet 3500 Doppel-Induktion",
        "competitor_url": "https://www.expert.at/...",
        "competitor_price": 139.00
      }
    ]
  }
]
```

**Required fields** for scoring:
- `source_reference` — the source product reference (from the Source Products table)
- `competitors[].reference` — the target product reference (from the Target Pool, or a new reference for scraped products)

Additional fields (`competitor_retailer`, `competitor_product_name`, `competitor_url`, `competitor_price`) are optional but recommended for your own tracking.

---

## Matching Strategies

### For Visible Retailers (Target Pool)

You have the full target pool data. Strategies:

1. **EAN/GTIN matching** — If both products have the same EAN barcode, they're the same product. Highest confidence.
2. **Name similarity** — Fuzzy string matching on product names (brand + model number).
3. **Brand + specs** — Match by brand, category, and key specifications (e.g., wattage, capacity).
4. **Price proximity** — Similar products are often similarly priced. Use as a secondary signal.

### For Hidden Retailers (Scraping)

You need to discover products by scraping the retailer websites:

1. **EAN search** — Search the retailer site by EAN barcode. Highest hit rate.
2. **Name search** — Search by product name or model number.
3. **Category browsing** — Browse the retailer's category pages and match by attributes.
4. **Google search** — `site:expert.at "Bosch Serie 4 Geschirrspueler"` can find product pages.

### Tips

- **Start with EAN matching** — it's the most reliable signal (~80% hit rate)
- **Study the sample solutions** in the Data Explorer to understand what correct matches look like
- **LLMs can help** — use them for fuzzy name matching, spec extraction, or generating search queries
- **Be respectful when scraping** — rate limit to 1-2 requests/second, set a proper User-Agent
- **Submit early and often** — you get instant feedback, so iterate on your approach

---

## Getting Started

```bash
# 1. Log in to the web app
# https://hackathon-production-49ca.up.railway.app/
# Sign in with GitHub, get assigned to a team

# 2. Go to Data Explorer, download the data for your released category
# - source_products_<category>.json
# - target_pool_<category>.json

# 3. Build your matching pipeline
# - Match source products to target pool (visible retailers)
# - Scrape hidden retailer websites for additional matches

# 4. Format your results as JSON (see Submission Format above)

# 5. Go to Submit, select your category, upload your JSON
# - You'll get instant scoring feedback
# - Iterate and improve!
```

---

## Challenge Timeline

```
HOUR 0:     First category released
            Download data, start building your matching system

HOURS 1-3:  Build & iterate on first category
            Submit early for feedback, improve your approach

HOURS 3-5:  Additional categories released
            Apply your system to new categories

HOURS 5-7:  Optimize and expand
            Improve scraping, increase coverage

HOUR 7-8:   Final submissions
            Last chance to submit improved results

HOUR 8:     DEADLINE — Final scores locked
```

---

## Rules

- You may use any programming language, library, or API
- You may use LLMs (OpenAI, Gemini, Claude, local models)
- You may NOT manually look up and enter product matches — the process must be automated/scripted
- Web scraping must be respectful (rate limiting, proper User-Agent)
- The leaderboard is live — check your ranking throughout the day

---

## API Keys (provided by organizers)

| Service | Key |
|---------|-----|
| OpenAI | _(provided at event)_ |
| Brave Search | _(provided at event)_ |

---

Good luck! Find those competitors!