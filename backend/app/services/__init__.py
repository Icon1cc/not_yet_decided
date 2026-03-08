"""Services module initialization."""

from backend.app.services.catalog import CatalogMatcher, get_matcher
from backend.app.services.agent import AIAgent, get_agent
from backend.app.services.matching import (
    MatchResult,
    ProductSignals,
    build_deterministic_query_terms,
    canonical_listing_key,
    extract_product_signals,
    score_product_match,
)

__all__ = [
    "AIAgent",
    "CatalogMatcher",
    "get_agent",
    "get_matcher",
    "MatchResult",
    "ProductSignals",
    "build_deterministic_query_terms",
    "canonical_listing_key",
    "extract_product_signals",
    "score_product_match",
]
