"""
Product signal extraction and matching logic.

This module contains the core algorithms for extracting product identifiers
(EAN, model numbers, brand, etc.) and scoring product matches.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any

from backend.app.utils.text import normalize_text, strip_accents, canonical_url


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Constants for Signal Extraction
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

EAN_KEYS = (
    "GTIN", "EAN-Code", "EAN", "GTIN/EAN", "ean", "gtin", "ean13", "barcode", "mpn"
)

ASIN_KEYS = ("ASIN", "asin")

BRAND_KEYS = ("Marke", "Brand", "Hersteller", "brand", "manufacturer")

MODEL_KEYS = (
    "Hersteller Modellnummer", "Hersteller Artikelnummer", "Modellnummer",
    "Modellname", "Model", "Model Number", "Herstellernummer", "Artikelnummer",
    "Modellkennzeichen",
)

SIZE_SPEC_KEYS = (
    "Bildschirmdiagonale", "Bildschirmdiagonale (cm/Zoll)",
    "Bildschirmdiagonale in cm, Zoll", "Größe", "Fassungsvermögen",
    "Kabellänge", "Länge", "Abmessungen", "Produktabmessungen",
)

MODEL_MIN_LEN = 5

NAME_STOPWORDS = {
    "and", "bei", "cm", "das", "der", "die", "ein", "eine", "fuer", "für",
    "full", "hd", "im", "in", "mit", "of", "ohne", "pro", "smart", "tv",
    "the", "und", "von", "zoll",
}

RETAILER_TOKENS = {
    "amazon", "cyberport", "electronic4you", "e-tec", "etec", "expert", "mediamarkt"
}

KNOWN_BRANDS = {
    "aeg", "apple", "beurer", "bose", "bosch", "braun", "chiq", "cosori",
    "delonghi", "delock", "dyson", "electrolux", "exquisit", "gastroback",
    "gorenje", "grundig", "haier", "hisense", "hama", "instant", "jbl", "jura",
    "jvc", "kenwood", "kitchenaid", "krups", "lg", "loewe", "medion", "melitta",
    "miele", "ninja", "nokia", "panasonic", "peaq", "philips", "remington",
    "rommelsbacher", "rowenta", "sage", "samsung", "sharp", "siemens", "silva",
    "sony", "sonero", "tcl", "tefal", "telefunken", "thomson", "valera", "wmf",
    "xiaomi",
}

MODEL_BLOCKLIST = {
    "1080P", "120HZ", "144HZ", "240HZ", "360HZ", "4K", "5G", "500ML", "60HZ",
    "8K", "AIRFRYER", "ANDROID", "BLACK", "BLUETOOTH", "CHROMECAST", "DUAL",
    "ELECTRONIC4YOU", "EXPERT", "FULLHD", "GOOGLE", "HDR", "HDR10", "HDR10PLUS",
    "HDREADY", "HEPA", "INVERTER", "IQ300", "IQ500", "IQ700", "MEMC", "MINILED",
    "OLED", "ONLINE", "QLED", "SERIE4", "SERIE6", "SERIE7", "SERIE8", "SERIE9",
    "SERIES4", "SERIES5", "SERIES6", "SERIES7", "SERIES8", "SERIES9", "SILBER",
    "SILVER", "SMARTTV", "TRIPLE", "UHD", "WASHTOWER", "WEISS", "WHITE", "WIFI",
    "WLAN",
}

GENERIC_MODEL_PATTERNS = (
    re.compile(r"^(?:IQ|SERIE|SERIES)\d{2,4}$"),
    re.compile(r"^\d{2,4}(?:SERIE|SERIES)$"),
    re.compile(r"^(?:A|X|Q)PRO$"),
    re.compile(r"^SMART(?:TV)?$"),
    re.compile(r"^FULLHD$"),
    re.compile(r"^HDR\d*PLUS?$"),
)

DEBUG_SPEC_PREFIXES = ("_search", "source_", "source_query_")

MODEL_JOIN_STOPWORDS = {
    "A", "AND", "CM", "C7", "DB", "DISPLAYPORT", "FULL", "G", "GOOGLE", "GRAMM",
    "HD", "HZ", "INCH", "KG", "L", "LED", "LITER", "M", "MIN", "ML", "MM",
    "EURO", "HDMI", "IEC", "LIGHTNING", "PRO", "RJ45", "SMART", "TV", "U",
    "UHD", "USB", "V", "W", "WATT", "ZOLL",
}

KIND_PATTERNS = {
    "air_fryer": ("airfryer", "heissluftfritteuse", "heißluftfritteuse", "fritteuse"),
    "coffee_machine": ("espresso", "kaffeemaschine", "kaffeevollautomat", "siebtraeger", "siebträger"),
    "descaler": ("descaler", "entkalker"),
    "dishwasher": ("geschirrspuler", "geschirrspüler", "dishwasher"),
    "dryer": ("trockner", "dryer"),
    "freezer": ("gefrierschrank", "freezer"),
    "fridge": ("kuhlschrank", "kühlschrank", "refrigerator"),
    "grill": ("kontaktgrill", "grill", "optigrill"),
    "hair_styler": ("haarglatter", "haarglätter", "hair straightener", "lockenstab", "hair dryer", "haartrockner"),
    "headphone": ("kopfhorer", "kopfhörer", "headset", "earbuds", "ohrhorer", "ohrhörer"),
    "hob": ("kochfeld", "glaskeramikkochfeld", "ceranfeld"),
    "kettle": ("wasserkocher", "kettle"),
    "microwave": ("mikrowelle", "microwave"),
    "mixer": ("mixer", "standmixer", "handmixer", "blender", "zerkleinerer", "kuchenmaschine", "küchenmaschine"),
    "range_hood": ("wandhaube", "dunstabzug", "abzugshaube"),
    "toaster": ("toaster",),
    "tv": ("fernseher", "smart tv", "google tv", "oled", "qled", "led tv"),
    "vacuum": ("staubsauger", "vacuum", "wischsauger"),
    "washer": ("waschmaschine", "toplader", "frontlader", "washing machine"),
    "washer_dryer": ("waschtrockner", "washer dryer"),
}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Data Classes
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@dataclass(frozen=True)
class ProductSignals:
    """Extracted signals from a product for matching."""
    brand: str | None
    eans: frozenset[str]
    asins: frozenset[str]
    strong_models: frozenset[str]
    family_models: frozenset[str]
    name_norm: str
    tokens: frozenset[str]
    kind: str | None
    screen_size_inch: float | None


@dataclass(frozen=True)
class MatchResult:
    """Result of matching two products."""
    score: float
    matched: bool
    method: str
    reasons: tuple[str, ...]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Helper Functions
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def clean_specs_for_matching(specifications: dict | None) -> dict:
    """Clean specifications dict by removing debug/internal keys."""
    if not isinstance(specifications, dict):
        return {}
    cleaned: dict = {}
    for key, value in specifications.items():
        if value in (None, "", [], {}):
            continue
        if isinstance(key, str):
            lower = key.lower()
            if lower.startswith("_"):
                continue
            if any(lower.startswith(prefix) for prefix in DEBUG_SPEC_PREFIXES):
                continue
        cleaned[key] = value
    return cleaned


def _normalized_brand_value(value: str | None) -> str | None:
    """Normalize a brand value."""
    text = normalize_text(value)
    if not text:
        return None
    parts = [p for p in text.split() if p not in {"gmbh", "inc", "ag", "ltd", "electronics"}]
    if not parts:
        return None
    brand = parts[0]
    return brand.upper() if brand not in RETAILER_TOKENS else None


def _valid_numeric_identifier(value: str | None, *, min_len: int = 8, max_len: int = 14) -> str | None:
    """Validate and extract numeric identifier (EAN, GTIN)."""
    if value is None:
        return None
    digits = re.sub(r"\D", "", str(value))
    if min_len <= len(digits) <= max_len:
        return digits
    return None


def _canonical_model(token: str | None) -> str | None:
    """Canonicalize a model number token."""
    if token is None:
        return None
    text = strip_accents(str(token)).upper().strip()
    text = re.sub(r"\s+", "", text)
    text = text.replace("/", "")
    text = re.sub(r"[^A-Z0-9.+-]", "", text)
    text = text.replace("+", "PLUS")
    canonical = re.sub(r"[^A-Z0-9]", "", text)

    if len(canonical) < MODEL_MIN_LEN:
        return None
    if canonical in MODEL_BLOCKLIST:
        return None
    if re.fullmatch(r"\d+", canonical):
        return None
    if re.fullmatch(r"\d{12,14}", canonical):
        return None
    if re.fullmatch(r"\d{2,4}X\d{2,4}(?:X\d{1,4})?", canonical):
        return None
    if re.fullmatch(r"\d+(?:ML|W|V|HZ)", canonical):
        return None
    if not re.search(r"[A-Z]", canonical) or not re.search(r"\d", canonical):
        return None
    return canonical


def _is_generic_model(canonical: str) -> bool:
    """Check if a model number is too generic."""
    if canonical in MODEL_BLOCKLIST:
        return True
    if canonical.startswith("DVB"):
        return True
    return any(pattern.fullmatch(canonical) for pattern in GENERIC_MODEL_PATTERNS)


def _family_variants(canonical: str) -> set[str]:
    """Generate family variants of a model number."""
    variants = {canonical}
    if len(canonical) > MODEL_MIN_LEN and canonical[-1].isalpha():
        variants.add(canonical[:-1])
    if re.fullmatch(r"[A-Z]{1,3}\d{3,4}[A-Z]?", canonical):
        variants.add(re.sub(r"[A-Z]$", "", canonical))
    for match in re.finditer(r"[A-Z]\d{3,4}", canonical):
        variants.add(match.group(0))
    return {v for v in variants if len(v) >= MODEL_MIN_LEN}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Extraction Functions
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def extract_brand(product: dict) -> str | None:
    """Extract and normalize brand from product."""
    specs = clean_specs_for_matching(product.get("specifications"))
    for value in [product.get("brand"), *(specs.get(k) for k in BRAND_KEYS)]:
        brand = _normalized_brand_value(str(value) if value is not None else None)
        if brand:
            return brand
    name = normalize_text(product.get("name"))
    if not name:
        return None
    first = name.split()[0]
    return first.upper() if first in KNOWN_BRANDS else None


def extract_eans(product: dict) -> set[str]:
    """Extract EAN/GTIN codes from product."""
    specs = clean_specs_for_matching(product.get("specifications"))
    values = {product.get("ean")}
    values.update(specs.get(key) for key in EAN_KEYS)
    out = set()
    for value in values:
        parsed = _valid_numeric_identifier(value)
        if parsed:
            out.add(parsed)
    return out


def extract_asins(product: dict) -> set[str]:
    """Extract Amazon ASINs from product."""
    specs = clean_specs_for_matching(product.get("specifications"))
    out = set()
    for value in [product.get("asin"), *(specs.get(k) for k in ASIN_KEYS)]:
        if value is None:
            continue
        text = str(value).strip().upper()
        if re.fullmatch(r"B[0-9A-Z]{9}", text):
            out.add(text)
    return out


def extract_models(product: dict) -> tuple[set[str], set[str]]:
    """Extract model numbers from product. Returns (strong_models, family_models)."""
    specs = clean_specs_for_matching(product.get("specifications"))
    strong: set[str] = set()
    family: set[str] = set()

    # From spec fields
    for key in MODEL_KEYS:
        value = specs.get(key)
        if value in (None, ""):
            continue
        canonical = _canonical_model(str(value))
        if not canonical:
            continue
        if _is_generic_model(canonical):
            family.add(canonical)
        else:
            strong.add(canonical)
            family.update(_family_variants(canonical))

    # From product name
    name = strip_accents(product.get("name") or "").upper()
    for raw in re.findall(r"\b[A-Z0-9]{2,}(?:[.\-/][A-Z0-9]{1,})*\b", name):
        canonical = _canonical_model(raw)
        if not canonical:
            continue
        if _is_generic_model(canonical):
            family.add(canonical)
        else:
            strong.add(canonical)
            family.update(_family_variants(canonical))

    # Handle split model numbers (e.g., "KDW 6051 B FI")
    pieces = re.findall(r"[A-Z0-9]+", name)
    for start in range(len(pieces)):
        for width in range(2, 6):
            window = pieces[start:start + width]
            if len(window) < 2:
                continue
            if any(
                token in MODEL_BLOCKLIST or token in MODEL_JOIN_STOPWORDS
                or token.lower() in RETAILER_TOKENS
                for token in window
            ):
                continue

            digit_tokens = sum(bool(re.search(r"\d", token)) for token in window)
            digit_only_tokens = sum(token.isdigit() for token in window)
            mixed_tokens = sum(
                bool(re.search(r"[A-Z]", token) and re.search(r"\d", token))
                for token in window
            )
            pure_alpha = [token for token in window if token.isalpha()]

            if digit_tokens == 0 or digit_only_tokens == 0 or not pure_alpha:
                continue
            if mixed_tokens == 0 and digit_tokens < 2 and len(pure_alpha) < 2:
                continue

            invalid_alpha = False
            for idx, token in enumerate(pure_alpha):
                if len(token) <= 3:
                    continue
                if token != window[-1] or len(token) > 6:
                    invalid_alpha = True
                    break
            if invalid_alpha:
                continue

            joined = "".join(window)
            canonical = _canonical_model(joined)
            if not canonical:
                continue
            if _is_generic_model(canonical):
                family.add(canonical)
            else:
                family.update(_family_variants(canonical))

    return strong, family - strong


def extract_name_tokens(product: dict) -> set[str]:
    """Extract meaningful tokens from product name."""
    text = normalize_text(product.get("name"))
    tokens = set()
    for token in text.split():
        if len(token) < 2 or token in NAME_STOPWORDS or token in RETAILER_TOKENS:
            continue
        if token.isdigit() and len(token) <= 3:
            continue
        tokens.add(token)
    return tokens


def _extract_screen_size_inch(product: dict) -> float | None:
    """Extract screen size in inches from product."""
    name = strip_accents(str(product.get("name") or ""))
    match = re.search(r"(\d{2,3}(?:[.,]\d+)?)\s*(?:\"|zoll|inch)", name, re.IGNORECASE)
    if match:
        try:
            return float(match.group(1).replace(",", "."))
        except ValueError:
            pass

    specs = clean_specs_for_matching(product.get("specifications"))
    for key in SIZE_SPEC_KEYS:
        value = specs.get(key)
        text = strip_accents(str(value or ""))
        if not text:
            continue
        match = re.search(r"(\d{2,3}(?:[.,]\d+)?)\s*(?:\"|zoll|inch)", text, re.IGNORECASE)
        if match:
            try:
                return float(match.group(1).replace(",", "."))
            except ValueError:
                continue
        if "bildschirm" in key.lower() or "zoll" in text.lower():
            match = re.search(r"(\d{2,3}(?:[.,]\d+)?)\s*cm", text, re.IGNORECASE)
            if match:
                try:
                    return round(float(match.group(1).replace(",", ".")) / 2.54, 1)
                except ValueError:
                    continue
    return None


def infer_product_kind(product: dict) -> str | None:
    """Infer product type/kind from name and specifications."""
    text_bits = [product.get("name") or ""]
    specs = clean_specs_for_matching(product.get("specifications"))
    text_bits.extend(str(v) for v in specs.values() if isinstance(v, (str, int, float)))
    text = normalize_text(" ".join(text_bits))
    if not text:
        return None
    for kind, patterns in KIND_PATTERNS.items():
        if any(pattern in text for pattern in patterns):
            return kind
    return None


def extract_product_signals(product: dict) -> ProductSignals:
    """Extract all matching signals from a product."""
    strong_models, family_models = extract_models(product)
    return ProductSignals(
        brand=extract_brand(product),
        eans=frozenset(extract_eans(product)),
        asins=frozenset(extract_asins(product)),
        strong_models=frozenset(strong_models),
        family_models=frozenset(family_models),
        name_norm=normalize_text(product.get("name")),
        tokens=frozenset(extract_name_tokens(product)),
        kind=infer_product_kind(product),
        screen_size_inch=_extract_screen_size_inch(product),
    )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Matching Functions
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def _sequence_ratio(a: str, b: str) -> float:
    """Calculate sequence similarity ratio."""
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def _jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    """Calculate Jaccard similarity."""
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def score_product_match(
    source: dict,
    target: dict,
    source_signals: ProductSignals | None = None,
    target_signals: ProductSignals | None = None,
    threshold: float = 0.80,
) -> MatchResult:
    """
    Score how well a target product matches a source product.

    Uses a multi-signal scoring algorithm:
    1. EAN/GTIN exact match (0.99)
    2. ASIN exact match (0.985)
    3. Model number match (0.92+)
    4. Family model match (0.38+)
    5. Text similarity (brand + kind + size + name)

    Returns MatchResult with score, matched flag, method, and reasons.
    """
    src = source_signals or extract_product_signals(source)
    tgt = target_signals or extract_product_signals(target)
    reasons: list[str] = []

    # Early rejection: brand conflict
    if src.brand and tgt.brand and src.brand != tgt.brand:
        return MatchResult(0.0, False, "brand_conflict", ("brand_conflict",))

    # Early rejection: kind conflict
    if src.kind and tgt.kind and src.kind != tgt.kind:
        return MatchResult(0.0, False, "kind_conflict", ("kind_conflict",))

    # Early rejection: size conflict
    if (
        src.screen_size_inch is not None
        and tgt.screen_size_inch is not None
        and abs(src.screen_size_inch - tgt.screen_size_inch) > 1.0
    ):
        return MatchResult(0.0, False, "size_conflict", ("size_conflict",))

    # Calculate similarity metrics
    name_ratio = _sequence_ratio(src.name_norm, tgt.name_norm)
    token_overlap = _jaccard(src.tokens, tgt.tokens)
    same_brand = bool(src.brand and tgt.brand and src.brand == tgt.brand)
    same_kind = bool(src.kind and tgt.kind and src.kind == tgt.kind)
    same_size = (
        src.screen_size_inch is not None
        and tgt.screen_size_inch is not None
        and abs(src.screen_size_inch - tgt.screen_size_inch) <= 1.0
    )

    # Identifier overlaps
    ean_overlap = src.eans & tgt.eans
    asin_overlap = src.asins & tgt.asins
    strong_model_overlap = src.strong_models & tgt.strong_models
    family_model_overlap = (src.strong_models | src.family_models) & (
        tgt.strong_models | tgt.family_models
    )
    any_src_models = src.strong_models | src.family_models
    any_tgt_models = tgt.strong_models | tgt.family_models

    # Model conflict check
    if any_src_models and any_tgt_models and not family_model_overlap and same_brand:
        return MatchResult(0.0, False, "model_conflict", ("model_conflict",))

    score = 0.0
    method = "none"

    # EAN match
    if ean_overlap:
        score = 0.99
        method = "gtin"
        reasons.append("ean_exact")

    # ASIN match
    if asin_overlap and score < 0.985:
        score = 0.985
        method = "asin"
        reasons.append("asin_exact")

    # Model number match
    if strong_model_overlap:
        model_score = 0.92
        if same_brand:
            model_score += 0.03
        if same_size:
            model_score += 0.03
        if name_ratio >= 0.7 or token_overlap >= 0.45:
            model_score += 0.02
        if model_score > score:
            score = min(model_score, 0.98)
            method = "model"
        reasons.append("model_exact")
    elif family_model_overlap:
        family_score = 0.38
        if same_brand:
            family_score += 0.12
        if same_kind:
            family_score += 0.16
        if same_size:
            family_score += 0.16
        if token_overlap >= 0.45:
            family_score += 0.12
        if name_ratio >= 0.72:
            family_score += 0.12
        if family_score > score:
            score = min(family_score, 0.86)
            method = "family_model"
        reasons.append("model_family")

    # Text similarity score
    text_score = 0.0
    if same_brand:
        text_score += 0.22
    if same_kind:
        text_score += 0.18
    if same_size:
        text_score += 0.18
    text_score += token_overlap * 0.28
    text_score += name_ratio * 0.24
    if text_score > score:
        score = min(text_score, 0.89)
        method = "name_sim"

    # Final brand conflict check for high scores
    if score >= 0.97 and not same_brand and src.brand and tgt.brand:
        return MatchResult(0.0, False, "brand_conflict", ("brand_conflict",))

    matched = score >= threshold
    if method == "none" and matched:
        method = "name_sim"

    # Add reason flags
    if same_brand:
        reasons.append("brand_match")
    if same_kind:
        reasons.append("kind_match")
    if same_size:
        reasons.append("size_match")
    if token_overlap >= 0.45:
        reasons.append("token_overlap")
    if name_ratio >= 0.72:
        reasons.append("name_close")

    return MatchResult(round(score, 4), matched, method, tuple(dict.fromkeys(reasons)))


def canonical_listing_key(product: dict) -> str:
    """Generate a canonical key for deduplicating product listings."""
    retailer = normalize_text(product.get("retailer")) or "unknown"
    url = canonical_url(product.get("url"))
    if url:
        return f"{retailer}|url|{url}"

    signals = extract_product_signals(product)
    if signals.asins:
        return f"{retailer}|asin|{sorted(signals.asins)[0]}"
    if signals.eans:
        return f"{retailer}|ean|{sorted(signals.eans)[0]}"
    if signals.strong_models:
        return f"{retailer}|model|{sorted(signals.strong_models)[0]}"
    return f"{retailer}|name|{signals.name_norm}"


def build_deterministic_query_terms(product: dict, max_terms: int = 6) -> list[str]:
    """Build deterministic search terms for a product."""
    signals = extract_product_signals(product)
    name = str(product.get("name") or "").strip()
    brand = signals.brand.title() if signals.brand else ""
    terms: list[str] = []

    terms.extend(sorted(signals.eans))
    terms.extend(sorted(signals.asins))
    for model in sorted(signals.strong_models):
        if brand:
            terms.append(f"{brand} {model}")
        terms.append(model)

    if brand and name:
        terms.append(f"{brand} {name}")
    if name:
        terms.append(name)

    tokens = [tok for tok in name.split() if len(tok) > 2][:6]
    if brand and tokens:
        terms.append(" ".join([brand, *tokens[:4]]).strip())

    # Deduplicate
    uniq: list[str] = []
    seen: set[str] = set()
    for term in terms:
        term = " ".join(str(term).split()).strip()
        if not term:
            continue
        key = term.lower()
        if key in seen:
            continue
        seen.add(key)
        uniq.append(term)
    return uniq[:max_terms]
