"""
Catalog Matcher Service.

The core service for matching source products against target competitor products.
Handles query parsing, source selection, and product matching.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any

from backend.app.core.config import get_settings
from backend.app.services.matching import (
    ProductSignals,
    canonical_listing_key,
    canonical_url,
    extract_product_signals,
    normalize_text,
    score_product_match,
)

logger = logging.getLogger(__name__)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Query Parsing Constants
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

SOURCE_REF_PATTERN = re.compile(r"\bP_[A-Z0-9]{8}\b", re.IGNORECASE)

QUERY_STOPWORDS = {
    "a", "about", "all", "and", "any", "bitte", "can", "compare", "der", "die",
    "ein", "eine", "find", "for", "from", "fur", "für", "get", "gib", "give",
    "ich", "in", "is", "kannst", "me", "match", "matching", "mir", "mit", "of",
    "on", "please", "show", "to", "und", "what", "with",
}

FOLLOW_UP_FILTER_TOKENS = {
    *QUERY_STOPWORDS,
    "all", "alles", "allesamt", "below", "between", "billig", "cheapest",
    "competitor", "competitors", "filter", "from", "hidden", "higher", "less",
    "lower", "max", "maximum", "min", "minimum", "more", "most", "only", "over",
    "price", "retailer", "show", "than", "under", "visible",
    "amazon", "cyberport", "electronic", "electronic4you", "etec", "expert",
    "e tec", "mediamarkt", "media", "markt",
}

RETAILER_KEYWORDS = {
    "expert at": "Expert AT", "expert": "Expert AT",
    "cyberport": "Cyberport AT",
    "electronic4you": "electronic4you.at", "electronic 4 you": "electronic4you.at",
    "e-tec": "E-Tec", "etec": "E-Tec",
    "amazon": "Amazon AT",
    "mediamarkt": "MediaMarkt AT", "media markt": "MediaMarkt AT",
}

CATEGORY_KEYWORDS = {
    "TV & Audio": {"tv", "audio", "fernseher", "qled", "oled", "soundbar", "headphone", "kopfh", "lautsprecher"},
    "Small Appliances": {
        "small", "appliance", "airfryer", "heissluft", "toaster", "coffee",
        "espresso", "kettle", "haargl", "mixer", "vacuum", "staubsauger",
    },
    "Large Appliances": {
        "large", "washing", "washer", "dishwasher", "geschirr", "kuehlschrank",
        "kühlschrank", "kuhlschrank", "gefrier", "dryer", "toplader", "frontlader",
    },
}

KIND_QUERY_KEYWORDS = {
    "air_fryer": {"airfryer", "air fryers", "air fryer", "heissluftfritteuse", "heissluftfritteusen"},
    "coffee_machine": {"espresso", "espressomaschine", "kaffeemaschine", "coffee machine", "coffee machines"},
    "dishwasher": {"dishwasher", "dishwashers", "geschirrspuler", "geschirrspulers"},
    "dryer": {"dryer", "dryers", "trockner", "trocknern"},
    "freezer": {"freezer", "freezers", "gefrierschrank", "gefrierschraenke"},
    "fridge": {"fridge", "fridges", "kuehlschrank", "kuehlschranke"},
    "headphone": {"headphone", "headphones", "headset", "headsets", "kopfhorer", "kopfhorern"},
    "hob": {"kochfeld", "kochfelder", "hob", "hobs", "cooktop", "cooktops"},
    "kettle": {"kettle", "kettles", "wasserkocher", "wasserkochern"},
    "microwave": {"microwave", "microwaves", "mikrowelle", "mikrowellen"},
    "mixer": {"mixer", "mixers", "blender", "blenders", "kuechenmaschine", "kuchenmaschine"},
    "toaster": {"toaster", "toasters"},
    "tv": {"tv", "tvs", "television", "televisions", "fernseher", "fernsehern", "qled", "oled"},
    "vacuum": {"vacuum", "vacuums", "staubsauger", "staubsaugern"},
    "washer": {"washer", "washers", "washing machine", "washing machines", "waschmaschine", "waschmaschinen"},
    "washer_dryer": {"washer dryer", "washer dryers", "waschtrockner", "waschtrocknern"},
}

NON_ANCHOR_QUERY_TOKENS = {
    "again", "are", "bad", "better", "different", "any", "detail", "details",
    "dont", "else", "for", "from", "good", "have", "has", "item", "items",
    "list", "like", "me", "more", "next", "no", "not", "only", "ones", "other",
    "others", "product", "products", "regarding", "related", "result", "results",
    "search", "show", "similar", "that", "there", "the", "these", "those",
    "which", "with",
}

FOLLOW_UP_EXPAND_PATTERNS = (
    "any more", "anything else", "different ones", "dont like", "don't like",
    "else", "more results", "next ones", "no more", "other ones", "others",
)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Data Classes
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@dataclass(frozen=True)
class TargetRecord:
    """A target product with precomputed signals for efficient matching."""
    product: dict[str, Any]
    signals: ProductSignals
    visible: bool
    category_norm: str
    canonical_url: str | None


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Catalog Matcher Service
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class CatalogMatcher:
    """
    Main service for matching source products against competitor catalogs.

    Reads all data from PostgreSQL (DATABASE_URL required).
    Sources are loaded once at startup; targets are fetched per request
    with server-side pre-filtering so nothing is held in RAM.
    """

    def __init__(self) -> None:
        from backend.app.db.repository import ProductRepository
        self._repo = ProductRepository()
        self.default_sources: list[dict[str, Any]] = self._repo.get_all_sources()
        logger.info("CatalogMatcher ready – %d source products loaded from DB.", len(self.default_sources))

    # ── Query Parsing ─────────────────────────────────────────────────────────

    def _query_tokens(self, query: str) -> set[str]:
        """Extract meaningful tokens from query."""
        tokens = set(normalize_text(query).split())
        return {t for t in tokens if len(t) > 1 and t not in QUERY_STOPWORDS}

    def _extract_source_refs(self, query: str) -> list[str]:
        """Extract product references from query."""
        refs = []
        for match in SOURCE_REF_PATTERN.findall(query or ""):
            ref = match.upper()
            if ref not in refs:
                refs.append(ref)
        return refs

    def _extract_retailer_filter(self, query: str) -> set[str]:
        """Extract retailer filter from query."""
        q = normalize_text(query)
        allowed = set()
        for key, retailer in RETAILER_KEYWORDS.items():
            if normalize_text(key) in q:
                allowed.add(retailer)
        return allowed

    def _extract_price_bounds(self, query: str) -> tuple[float | None, float | None]:
        """Extract price bounds from query."""
        q = normalize_text(query)
        min_price = None
        max_price = None

        below = re.search(r"(?:under|below|unter|max|bis|<=)\s*([0-9]+(?:[.,][0-9]{1,2})?)", q)
        above = re.search(r"(?:over|above|mehr als|ab|>=)\s*([0-9]+(?:[.,][0-9]{1,2})?)", q)
        between = re.search(
            r"(?:between|zwischen)\s*([0-9]+(?:[.,][0-9]{1,2})?)\s*(?:and|und|-)\s*([0-9]+(?:[.,][0-9]{1,2})?)",
            q,
        )

        if below:
            max_price = float(below.group(1).replace(",", "."))
        if above:
            min_price = float(above.group(1).replace(",", "."))
        if between:
            min_price = float(between.group(1).replace(",", "."))
            max_price = float(between.group(2).replace(",", "."))

        return min_price, max_price

    def _extract_category_filter(self, query: str) -> set[str]:
        """Extract category filter from query."""
        tokens = self._query_tokens(query)
        categories: set[str] = set()
        for category, keywords in CATEGORY_KEYWORDS.items():
            if tokens & keywords:
                categories.add(category)
        return categories

    def _extract_kind_filter(self, query: str) -> set[str]:
        """Extract product kind filter from query."""
        q = normalize_text(query)
        tokens = set(q.split())
        kinds: set[str] = set()
        for kind, keywords in KIND_QUERY_KEYWORDS.items():
            for raw_kw in keywords:
                kw = normalize_text(raw_kw)
                if not kw:
                    continue
                if " " in kw:
                    if kw in q:
                        kinds.add(kind)
                        break
                elif kw in tokens:
                    kinds.add(kind)
                    break
        return kinds

    def _query_anchor_tokens(self, query: str, allowed_kinds: set[str]) -> set[str]:
        """Extract anchor tokens (significant search terms) from query."""
        tokens = self._query_tokens(query)
        retailer_tokens = {
            part for key in RETAILER_KEYWORDS
            for part in normalize_text(key).split() if part
        }
        kind_tokens = {
            part for kind in allowed_kinds
            for keyword in KIND_QUERY_KEYWORDS.get(kind, set())
            for part in normalize_text(keyword).split() if part
        }
        anchors = {
            token for token in tokens
            if len(token) >= 3
            and token not in NON_ANCHOR_QUERY_TOKENS
            and token not in retailer_tokens
            and token not in kind_tokens
            and not re.fullmatch(r"[0-9]+(?:[.,][0-9]+)?", token)
        }
        return anchors

    def _matches_anchor_tokens(self, text: str, anchors: set[str]) -> bool:
        """Check if text matches any anchor tokens."""
        if not anchors:
            return True
        text_norm = normalize_text(text)
        if not text_norm:
            return False
        tokens = set(text_norm.split())
        return any(anchor in tokens or anchor in text_norm for anchor in anchors)

    def _source_matches_query_anchor(self, source: dict[str, Any], anchors: set[str]) -> bool:
        """Check if source product matches anchor tokens."""
        if not anchors:
            return True
        fields = [
            str(source.get("reference") or ""),
            str(source.get("name") or ""),
            str(source.get("brand") or ""),
            str(source.get("category") or ""),
        ]
        return any(self._matches_anchor_tokens(field, anchors) for field in fields if field)

    def _structured_query_signal(
        self,
        query: str,
        allowed_kinds: set[str] | None = None,
    ) -> dict[str, Any]:
        """Extract structured signals from query."""
        kinds = allowed_kinds if allowed_kinds is not None else self._extract_kind_filter(query)
        categories = self._extract_category_filter(query)
        refs = self._extract_source_refs(query)
        retailers = self._extract_retailer_filter(query)
        min_price, max_price = self._extract_price_bounds(query)
        anchors = self._query_anchor_tokens(query, kinds)
        return {
            "kinds": kinds,
            "categories": categories,
            "refs": refs,
            "retailers": retailers,
            "has_price_filter": min_price is not None or max_price is not None,
            "anchors": anchors,
        }

    def _looks_like_expand_follow_up(self, query: str) -> bool:
        """Check if query is a follow-up for more results."""
        q = normalize_text(query)
        if not q:
            return False
        if any(pattern in q for pattern in FOLLOW_UP_EXPAND_PATTERNS):
            return True
        tokens = set(q.split())
        return bool(tokens & {"again", "another", "different", "else", "extra", "more", "next", "remaining"})

    def _last_anchor_query(self, history: list[str] | None) -> str | None:
        """Find the last query with meaningful anchors in history."""
        if not history:
            return None
        for previous in reversed(history):
            if not isinstance(previous, str):
                continue
            previous = previous.strip()
            if not previous:
                continue
            signals = self._structured_query_signal(previous)
            if (
                signals["refs"] or signals["categories"] or signals["kinds"]
                or signals["retailers"] or signals["has_price_filter"] or signals["anchors"]
            ):
                return previous
        return None

    def _previous_submission_map(
        self,
        previous_submission: list[dict[str, Any]] | None,
    ) -> dict[str, set[str]]:
        """Build map of previously shown results for deduplication."""
        shown: dict[str, set[str]] = {}
        if not previous_submission:
            return shown

        for entry in previous_submission:
            if not isinstance(entry, dict):
                continue
            source_ref = str(entry.get("source_reference") or "")
            if not source_ref:
                continue
            bucket = shown.setdefault(source_ref, set())
            competitors = entry.get("competitors")
            if not isinstance(competitors, list):
                continue
            for competitor in competitors:
                if not isinstance(competitor, dict):
                    continue
                reference = str(competitor.get("reference") or "").strip()
                url = canonical_url(competitor.get("competitor_url"))
                if reference:
                    bucket.add(f"ref:{reference}")
                if url:
                    bucket.add(f"url:{url}")

        return shown

    def _target_result_key(self, target: TargetRecord) -> str:
        """Generate key for deduplicating target results."""
        reference = str(target.product.get("reference") or "").strip()
        if target.visible and reference:
            return f"ref:{reference}"
        url = canonical_url(target.product.get("url"))
        if url:
            return f"url:{url}"
        if reference:
            return f"ref:{reference}"
        return f"anon:{id(target)}"

    def _query_has_anchor(self, query: str) -> bool:
        """Check if query has meaningful anchor content."""
        if not query.strip():
            return False
        if self._extract_source_refs(query):
            return True
        if self._extract_category_filter(query):
            return True
        if self._extract_kind_filter(query):
            return True

        tokens = self._query_tokens(query)
        anchor_tokens = {
            t for t in tokens
            if t not in FOLLOW_UP_FILTER_TOKENS
            and not re.fullmatch(r"[0-9]+(?:[.,][0-9]+)?", t)
        }
        return bool(anchor_tokens)

    def _effective_query(self, query: str, history: list[str] | None) -> str:
        """Compute effective query, potentially combining with history."""
        current = (query or "").strip()
        if not current:
            return current
        if not history:
            return current
        if self._query_has_anchor(current):
            return current

        has_retailer_filter = bool(self._extract_retailer_filter(current))
        has_price_filter = self._extract_price_bounds(current) != (None, None)
        tokens = self._query_tokens(current)
        is_short = len(tokens) <= 4
        if not (has_retailer_filter or has_price_filter or is_short):
            return current

        for previous in reversed(history):
            if not isinstance(previous, str):
                continue
            previous = previous.strip()
            if not previous:
                continue
            if self._query_has_anchor(previous):
                return f"{previous} {current}"
        return current

    def _source_score(self, source: dict[str, Any], query_norm: str, query_tokens: set[str]) -> float:
        """Score a source product against query."""
        if not query_norm:
            return 0.0

        source_ref = str(source.get("reference") or "")
        source_name = normalize_text(source.get("name"))
        source_brand = normalize_text(source.get("brand"))
        source_category = normalize_text(source.get("category"))
        source_text = " ".join(part for part in [source_ref.lower(), source_name, source_brand, source_category] if part)

        source_tokens = {t for t in source_text.split() if t and t not in QUERY_STOPWORDS}
        overlap = len(source_tokens & query_tokens) / max(1, len(query_tokens))
        ratio = SequenceMatcher(None, query_norm, source_name).ratio() if source_name else 0.0

        score = (0.62 * overlap) + (0.38 * ratio)
        if source_ref and source_ref.lower() in query_norm:
            score += 0.8
        return score

    # ── Source Selection ──────────────────────────────────────────────────────

    def _select_sources(
        self,
        query: str,
        provided: list[dict[str, Any]] | None,
        max_sources: int,
        allowed_kinds: set[str],
        anchor_tokens: set[str],
    ) -> list[dict[str, Any]]:
        """Select source products matching the query."""
        sources = provided or self.default_sources
        if not sources:
            return []

        refs = self._extract_source_refs(query)
        if refs:
            selected = [s for s in sources if str(s.get("reference") or "").upper() in refs]
            if allowed_kinds:
                selected = [s for s in selected if extract_product_signals(s).kind in allowed_kinds]
            if anchor_tokens:
                selected = [s for s in selected if self._source_matches_query_anchor(s, anchor_tokens)]
            if selected:
                return selected

        categories = self._extract_category_filter(query)
        if categories:
            filtered = [
                s for s in sources
                if str(s.get("category") or "") in categories
                or normalize_text(str(s.get("category") or "")) in {normalize_text(c) for c in categories}
            ]
            if filtered:
                sources = filtered

        if allowed_kinds:
            filtered = [s for s in sources if extract_product_signals(s).kind in allowed_kinds]
            if filtered:
                sources = filtered
            else:
                return []

        if anchor_tokens:
            filtered = [s for s in sources if self._source_matches_query_anchor(s, anchor_tokens)]
            if filtered:
                sources = filtered

        query_norm = normalize_text(query)
        if any(word in query_norm for word in {"all", "every", "gesamte", "alle", "catalog", "katalog"}):
            return sources

        query_tokens = self._query_tokens(query)
        if not query_tokens and not query_norm:
            return sources[:max_sources]

        scored = [(self._source_score(source, query_norm, query_tokens), source) for source in sources]
        scored.sort(key=lambda item: item[0], reverse=True)

        selected = [source for score, source in scored if score >= 0.16][:max_sources]
        if selected:
            return selected

        # If the best score is too low, the query doesn't match anything in the catalog.
        # Return empty so the Brave web fallback can be used instead.
        if scored and scored[0][0] < 0.05:
            return []

        return [source for _, source in scored[:max_sources]]

    # ── Target Matching ───────────────────────────────────────────────────────

    def _match_one_source(
        self,
        source: dict[str, Any],
        targets: list[TargetRecord],
        max_competitors: int,
        allowed_retailers: set[str],
        allowed_kinds: set[str],
        min_price: float | None,
        max_price: float | None,
    ) -> list[tuple[float, str, TargetRecord]]:
        """Find matching targets for a single source product."""
        source_signals = extract_product_signals(source)
        source_ref = str(source.get("reference") or "")
        source_category_norm = normalize_text(source.get("category"))
        source_name_norm = normalize_text(source.get("name"))

        if allowed_kinds and source_signals.kind and source_signals.kind not in allowed_kinds:
            return []

        scored: list[tuple[float, str, TargetRecord]] = []
        for target in targets:
            retailer = str(target.product.get("retailer") or "")
            if allowed_retailers and retailer not in allowed_retailers:
                continue

            # Kind filtering
            if allowed_kinds:
                target_kind = target.signals.kind
                if target_kind not in allowed_kinds:
                    target_name_norm = normalize_text(target.product.get("name"))
                    kind_name_hit = False
                    for kind in allowed_kinds:
                        for kw in KIND_QUERY_KEYWORDS.get(kind, set()):
                            needle = normalize_text(kw)
                            if needle and needle in target_name_norm:
                                kind_name_hit = True
                                break
                        if kind_name_hit:
                            break
                    if not kind_name_hit:
                        continue

            # Category filtering for visible targets
            if target.visible and source_category_norm and target.category_norm:
                if source_category_norm != target.category_norm:
                    continue

            # Price filtering
            price = target.product.get("price_eur")
            if isinstance(price, (int, float)):
                if min_price is not None and price < min_price:
                    continue
                if max_price is not None and price > max_price:
                    continue

            # Direct reference match
            target_ref = str(target.product.get("reference") or "")
            if source_ref and source_ref == target_ref:
                scored.append((1.0, "direct_ref", target))
                continue

            # Kind validation for cross-kind matches
            if allowed_kinds and source_signals.kind is None:
                source_kind_hit = False
                for kind in allowed_kinds:
                    for kw in KIND_QUERY_KEYWORDS.get(kind, set()):
                        needle = normalize_text(kw)
                        if needle and needle in source_name_norm:
                            source_kind_hit = True
                            break
                    if source_kind_hit:
                        break
                if not source_kind_hit:
                    continue

            # Score the match
            result = score_product_match(
                source,
                target.product,
                source_signals=source_signals,
                target_signals=target.signals,
                threshold=0.80,
            )
            if result.matched:
                scored.append((result.score, result.method, target))

        scored.sort(key=lambda item: item[0], reverse=True)

        # Deduplicate by listing key
        best_by_key: dict[str, tuple[float, str, TargetRecord]] = {}
        for score, method, target in scored:
            if target.visible:
                key = str(target.product.get("reference") or "")
            else:
                key = canonical_listing_key(target.product)
            if not key:
                key = f"fallback|{target.product.get('reference') or id(target)}"
            current = best_by_key.get(key)
            if current is None or score > current[0]:
                best_by_key[key] = (score, method, target)

        deduped = sorted(best_by_key.values(), key=lambda item: item[0], reverse=True)
        return deduped[:max_competitors]

    # ── Web Search Fallback ───────────────────────────────────────────────────

    def _search_brave(self, query: str, max_results: int) -> list[dict[str, Any]]:
        """Search using Brave API as fallback."""
        settings = get_settings()
        api_key = settings.brave_api_key or os.getenv("BRAVE_SEARCH_API_KEY", "")
        if not api_key:
            return []

        params = urllib.parse.urlencode({"q": query, "count": max_results})
        url = f"https://api.search.brave.com/res/v1/web/search?{params}"
        req = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": "competitor-matcher/1.0",
                "X-Subscription-Token": api_key,
            },
        )

        try:
            with urllib.request.urlopen(req, timeout=15) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, ValueError) as e:
            logger.warning(f"Brave search failed: {e}")
            return []

        results = payload.get("web", {}).get("results", [])
        if not isinstance(results, list):
            return []

        competitors: list[dict[str, Any]] = []
        for item in results[:max_results]:
            if not isinstance(item, dict):
                continue
            link = item.get("url")
            title = item.get("title")
            if not isinstance(link, str) or not link.startswith("http"):
                continue
            if not isinstance(title, str) or not title.strip():
                continue

            host = urllib.parse.urlparse(link).netloc.lower().removeprefix("www.")
            ref = "P_WS_" + hashlib.md5(link.encode("utf-8")).hexdigest()[:8].upper()
            competitors.append({
                "reference": ref,
                "competitor_retailer": host or "Web Search",
                "competitor_product_name": title.strip(),
                "competitor_url": link,
                "competitor_price": None,
            })

        return competitors

    # ── Main Query Method ─────────────────────────────────────────────────────

    def query(
        self,
        query: str,
        source_products: list[dict[str, Any]] | None,
        max_sources: int,
        max_competitors_per_source: int,
        history: list[str] | None = None,
        previous_submission: list[dict[str, Any]] | None = None,
        persist_output: bool = False,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
        """
        Execute a query and return matches.

        Returns:
            (submission, cards, stats) tuple
        """

        # Parse query signals
        current_signals = self._structured_query_signal(query)
        has_hard_product_filter = bool(
            current_signals["refs"] or current_signals["categories"]
            or current_signals["kinds"] or current_signals["retailers"]
            or current_signals["has_price_filter"]
        )

        # Check for follow-up expansion
        previous_source_refs = [
            str(entry.get("source_reference") or "").strip()
            for entry in (previous_submission or [])
            if isinstance(entry, dict) and str(entry.get("source_reference") or "").strip()
        ]
        follow_up_expand = (
            bool(previous_source_refs)
            and not has_hard_product_filter
            and self._looks_like_expand_follow_up(query)
        )

        if follow_up_expand:
            effective_query = self._last_anchor_query(history) or query
        else:
            effective_query = self._effective_query(query, history)

        # Extract filters
        allowed_kinds = self._extract_kind_filter(effective_query)
        anchor_tokens = self._query_anchor_tokens(effective_query, allowed_kinds)
        allowed_retailers = self._extract_retailer_filter(effective_query)
        min_price, max_price = self._extract_price_bounds(effective_query)
        previous_shown_keys = self._previous_submission_map(previous_submission)

        # Select sources
        selected_sources = self._select_sources(
            effective_query, source_products, max_sources,
            allowed_kinds=allowed_kinds, anchor_tokens=anchor_tokens,
        )

        # For follow-up, use previous source refs
        if follow_up_expand and previous_source_refs:
            source_map = {
                str(source.get("reference") or "").strip(): source
                for source in (source_products or self.default_sources)
                if str(source.get("reference") or "").strip()
            }
            selected_sources = [
                source_map[ref] for ref in previous_source_refs if ref in source_map
            ]

        # Determine the category to pass to the DB (use the first selected source's category)
        query_category: str | None = None
        if selected_sources:
            query_category = selected_sources[0].get("category") or None

        # Fetch candidate targets from DB once per request (server-side pre-filtering)
        target_candidates = self._repo.get_target_candidates(
            category=query_category,
            kinds=allowed_kinds or None,
            retailers=allowed_retailers or None,
            min_price=min_price,
            max_price=max_price,
        )
        logger.debug(
            "DB returned %d candidate targets (category=%s, kinds=%s).",
            len(target_candidates), query_category, allowed_kinds,
        )

        # Execute matching
        submission: list[dict[str, Any]] = []
        cards: list[dict[str, Any]] = []
        matched_sources = 0
        visible_links = 0
        hidden_links = 0
        fallback_used = False
        fallback_reason = None
        additional_only = follow_up_expand
        excluded_previous_links = 0

        # Fallback if no targets at all
        if not target_candidates:
            fallback_reason = "no_local_target_files"
            fallback_competitors = self._search_brave(effective_query, max_competitors_per_source)
            if fallback_competitors:
                fallback_used = True
                source_ref = str(selected_sources[0].get("reference") or "") if selected_sources else "WEB_QUERY"
                submission = [{"source_reference": source_ref, "competitors": fallback_competitors}]
                cards = [
                    {
                        "reference": c["reference"],
                        "source_reference": source_ref,
                        "name": c["competitor_product_name"],
                        "retailer": c["competitor_retailer"],
                        "price_eur": c["competitor_price"],
                        "image_url": None,
                        "url": c["competitor_url"],
                    }
                    for c in fallback_competitors
                ]
                matched_sources = 1
                hidden_links = len(fallback_competitors)

        # Normal matching
        if not fallback_used:
            for source in selected_sources:
                source_ref = str(source.get("reference") or "")
                if not source_ref:
                    source_ref = f"UP_{len(submission)+1:04d}"

                matched = self._match_one_source(
                    source,
                    target_candidates,
                    max_competitors=max(max_competitors_per_source, 24) if additional_only else max_competitors_per_source,
                    allowed_retailers=allowed_retailers,
                    allowed_kinds=allowed_kinds,
                    min_price=min_price,
                    max_price=max_price,
                )

                competitors: list[dict[str, Any]] = []
                for _, _, target in matched:
                    target_key = self._target_result_key(target)
                    if target_key in previous_shown_keys.get(source_ref, set()):
                        excluded_previous_links += 1
                        continue

                    product = target.product
                    competitor = {
                        "reference": str(product.get("reference") or ""),
                        "competitor_retailer": str(product.get("retailer") or ""),
                        "competitor_product_name": str(product.get("name") or ""),
                        "competitor_url": product.get("url"),
                        "competitor_price": product.get("price_eur"),
                    }
                    competitors.append(competitor)

                    cards.append({
                        "reference": competitor["reference"],
                        "source_reference": source_ref,
                        "name": competitor["competitor_product_name"],
                        "retailer": competitor["competitor_retailer"],
                        "price_eur": competitor["competitor_price"],
                        "image_url": product.get("image_url"),
                        "url": competitor["competitor_url"],
                    })

                    if target.visible:
                        visible_links += 1
                    else:
                        hidden_links += 1

                if competitors:
                    matched_sources += 1

                submission.append({
                    "source_reference": source_ref,
                    "competitors": competitors,
                })

        # Brave fallback when local matching found nothing
        if not fallback_used and matched_sources == 0:
            fallback_reason = "no_local_matches"
            fallback_competitors = self._search_brave(effective_query, max_competitors_per_source)
            if fallback_competitors:
                fallback_used = True
                source_ref = str(selected_sources[0].get("reference") or "") if selected_sources else "WEB_QUERY"
                submission = [{"source_reference": source_ref, "competitors": fallback_competitors}]
                cards = [
                    {
                        "reference": c["reference"],
                        "source_reference": source_ref,
                        "name": c["competitor_product_name"],
                        "retailer": c["competitor_retailer"],
                        "price_eur": c["competitor_price"],
                        "image_url": None,
                        "url": c["competitor_url"],
                    }
                    for c in fallback_competitors
                ]
                matched_sources = 1
                hidden_links += len(fallback_competitors)

        stats = {
            "query": query,
            "effective_query": effective_query,
            "selected_sources": len(selected_sources),
            "matched_sources": matched_sources,
            "total_links": visible_links + hidden_links,
            "visible_links": visible_links,
            "hidden_links": hidden_links,
            "retailer_filter": sorted(allowed_retailers),
            "kind_filter": sorted(allowed_kinds),
            "anchor_tokens": sorted(anchor_tokens),
            "price_filter": {"min": min_price, "max": max_price},
            "candidates_fetched": len(target_candidates),
            "follow_up_expand": follow_up_expand,
            "additional_only": additional_only,
            "previous_source_refs": previous_source_refs,
            "excluded_previous_links": excluded_previous_links,
            "fallback_used": fallback_used,
            "fallback_reason": fallback_reason,
            "output_file": None,
        }

        return submission, cards, stats


# Global instance
_matcher: CatalogMatcher | None = None


def get_matcher() -> CatalogMatcher:
    """Get or create the global matcher instance."""
    global _matcher
    if _matcher is None:
        _matcher = CatalogMatcher()
    return _matcher
