"""Product enrichment: structured tags extracted at indexing time.

- product_type: LLM classification (Haiku, batched)
- screen_size_inch: regex on name + specs
- model_number: extracted from spec fields
- resolution: regex on name + specs
"""
import re
import requests

PRODUCT_TYPES = (
    "tv", "headphone", "power_cable", "av_cable", "speaker", "soundbar",
    "coffee_machine", "coffee_accessory", "air_fryer", "air_fryer_accessory",
    "hair_care", "kitchen_appliance", "refrigerator", "vacuum", "accessory", "other",
)

ENRICHMENT_SYSTEM = f"""Classify each product into exactly one product type.
Output format: <reference>: <type>

Valid types: {" | ".join(PRODUCT_TYPES)}

Rules:
- tv: any television / Fernseher
- power_cable: Netzkabel, Stromkabel, Eurostecker cord — even if name lists compatible devices after "für"
- av_cable: HDMI, USB, audio, video, optical, antenna cables
- headphone: in-ear, over-ear, earbuds, Kopfhörer, Ohrhörer
- speaker / soundbar: standalone audio output device
- accessory: mounting hardware, cleaning products, filters, covers, cases for another product
- coffee_accessory: Kapseln, pods, filters, descaler for coffee machines
- air_fryer_accessory: pans, racks, liners for air fryers
- hair_care: Haartrockner, Haarglätter, Lockenstab, Haarschneider
- kitchen_appliance: microwave, toaster, blender, kettle (not coffee machine or air fryer)
- streaming_device: Chromecast, Fire Stick, Apple TV box — classify as "other"
- remote / Fernbedienung — classify as "accessory"

No explanations. One line per product. Unknown = other."""


def _call_openrouter(system: str, user: str, model: str, api_key: str) -> str:
    resp = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        },
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()


def classify_product_types(
    products: list[dict],
    api_key: str,
    model: str = "anthropic/claude-haiku-4-5",
    batch_size: int = 48,
) -> dict[str, str]:
    """Returns {reference: product_type} for all products."""
    result: dict[str, str] = {}

    for i in range(0, len(products), batch_size):
        batch = products[i : i + batch_size]
        lines = [f"{p['reference']} | {(p.get('name') or '')[:120]}" for p in batch]
        raw = _call_openrouter(ENRICHMENT_SYSTEM, "\n".join(lines), model, api_key)

        for line in raw.splitlines():
            line = line.strip()
            if ":" not in line:
                continue
            ref, _, ptype = line.partition(":")
            ref = ref.strip()
            ptype = ptype.strip().lower()
            if ptype not in PRODUCT_TYPES:
                ptype = "other"
            result[ref] = ptype

        for p in batch:
            result.setdefault(p["reference"], "other")

        n_batches = (len(products) + batch_size - 1) // batch_size
        print(f"  Classified types batch {i // batch_size + 1}/{n_batches} ({len(batch)} products)")

    return result


# ── Regex-based extractors ────────────────────────────────────────────────────

_MODEL_NUMBER_SPEC_KEYS = (
    "Hersteller Artikelnummer", "Hersteller Modellnummer",
    "Herstellernummer", "Modellnummer", "Artikelnummer",
)

_BRAND_SPEC_KEYS = ("Marke", "Hersteller", "Brand")

# Known brands for first-word matching (lowercase)
_KNOWN_BRANDS = {
    "samsung", "lg", "sony", "philips", "sharp", "tcl", "hisense", "xiaomi",
    "grundig", "telefunken", "panasonic", "toshiba", "jvc", "metz", "loewe",
    "nokia", "peaq", "chiq", "dyon", "ok", "ok.", "thomson", "strong",
    "jbl", "bose", "sonos", "harman", "sennheiser", "jabra", "apple",
    "remington", "braun", "philips", "rowenta", "dyson", "bosch", "siemens",
    "delonghi", "nespresso", "krups", "melitta", "jura", "saeco",
    "tefal", "wmf", "sage", "ninja", "cosori", "instant",
    "miele", "aeg", "electrolux", "gorenje", "haier", "arçelik",
    "hama", "goobay", "deleycon", "ancable", "sonero", "mcbazel",
}

_RESOLUTION_PATTERNS = [
    (re.compile(r"\b8K\b", re.I), "8K"),
    (re.compile(r"\b4K\b|\bUHD\b", re.I), "4K"),
    (re.compile(r"\bFull[\s\-]?HD\b|\bFHD\b|\b1080[pi]\b", re.I), "FHD"),
    (re.compile(r"\bHD[\s\-]?Ready\b|\b720[pi]\b", re.I), "HD"),
]

# Ordered by specificity — first match wins
_SIZE_PATTERNS = [
    (re.compile(r"(\d+(?:[.,]\d+)?)\s*(Zoll|\")", re.I), "Zoll"),
    (re.compile(r"(\d+(?:[.,]\d+)?)\s*(cm)\b", re.I), "cm"),
    (re.compile(r"(\d+(?:[.,]\d+)?)\s*(mm)\b", re.I), "mm"),
    (re.compile(r"(\d+(?:[.,]\d+)?)\s*(m)\b(?!\w)", re.I), "m"),
    (re.compile(r"(\d+(?:[.,]\d+)?)\s*(l|liter|litre)\b", re.I), "L"),
    (re.compile(r"(\d+(?:[.,]\d+)?)\s*(ml)\b", re.I), "ml"),
    (re.compile(r"(\d+(?:[.,]\d+)?)\s*(kg)\b", re.I), "kg"),
    (re.compile(r"(\d+(?:[.,]\d+)?)\s*(g)\b(?!\w)", re.I), "g"),
    (re.compile(r"(\d+(?:[.,]\d+)?)\s*(w)\b(?!\w)", re.I), "W"),
]


def extract_structured_fields(product: dict) -> dict:
    """Extract screen_size_inch, model_number, resolution via regex/spec lookup.
    Returns dict with those keys (values may be None if not found).
    """
    name = product.get("name") or ""
    specs = product.get("specifications") or {}
    combined = name + " " + " ".join(str(v) for v in specs.values())

    # size + size_unit — try name first, then key spec fields
    size: float | None = None
    size_unit: str | None = None

    def _find_size(text: str) -> tuple[float, str] | None:
        for pattern, unit in _SIZE_PATTERNS:
            m = pattern.search(text)
            if m:
                try:
                    return float(m.group(1).replace(",", ".")), unit
                except ValueError:
                    pass
        return None

    result_size = _find_size(name)
    if not result_size:
        for key in ("Bildschirmdiagonale in cm, Zoll", "Bildschirmdiagonale (cm/Zoll)", "Größe", "Kabellänge", "Länge"):
            if key in specs:
                result_size = _find_size(str(specs[key]))
                if result_size:
                    break
    if result_size:
        size, size_unit = result_size

    # model_number — prefer spec fields over regex
    model_number = None
    for key in _MODEL_NUMBER_SPEC_KEYS:
        val = specs.get(key)
        if val and str(val).strip():
            model_number = str(val).strip()
            break
    # fallback: also check top-level ean/gtin
    if not model_number:
        for key in ("ean", "gtin"):
            val = product.get(key)
            if val:
                model_number = str(val).strip()
                break

    # resolution
    resolution = None
    for pattern, label in _RESOLUTION_PATTERNS:
        if pattern.search(combined):
            resolution = label
            break

    # brand_norm — prefer spec fields, fallback to first known word in name
    brand_norm = None
    for key in _BRAND_SPEC_KEYS:
        val = specs.get(key) or product.get(key.lower())
        if val and str(val).strip():
            brand_norm = str(val).strip().upper()
            break
    if not brand_norm:
        first_word = name.split()[0].lower().rstrip("®™") if name.split() else ""
        if first_word in _KNOWN_BRANDS:
            brand_norm = first_word.upper()

    return {
        "size": size,
        "size_unit": size_unit,
        "model_number": model_number,
        "resolution": resolution,
        "brand_norm": brand_norm,
    }


def enrich_products(
    products: list[dict],
    api_key: str,
    model: str = "anthropic/claude-haiku-4-5",
) -> list[dict]:
    """Enrich each product with product_type, screen_size_inch, model_number, resolution.
    Returns new list with enrichment fields added (original dicts not mutated).
    """
    print(f"Classifying product types for {len(products)} products...")
    type_map = classify_product_types(products, api_key, model)

    enriched = []
    for p in products:
        e = dict(p)
        e["product_type"] = type_map[p["reference"]]
        e.update(extract_structured_fields(p))
        enriched.append(e)
    return enriched
