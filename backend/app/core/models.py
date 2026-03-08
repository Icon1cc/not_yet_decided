"""
Domain models and Pydantic schemas for the application.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, HttpUrl


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Enums
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class ProductCategory(str, Enum):
    """Product categories."""

    TV_AUDIO = "TV & Audio"
    SMALL_APPLIANCES = "Small Appliances"
    LARGE_APPLIANCES = "Large Appliances"


class ProductKind(str, Enum):
    """Fine-grained product types."""

    AIR_FRYER = "air_fryer"
    COFFEE_MACHINE = "coffee_machine"
    DISHWASHER = "dishwasher"
    DRYER = "dryer"
    FREEZER = "freezer"
    FRIDGE = "fridge"
    HEADPHONE = "headphone"
    HOB = "hob"
    KETTLE = "kettle"
    MICROWAVE = "microwave"
    MIXER = "mixer"
    TOASTER = "toaster"
    TV = "tv"
    VACUUM = "vacuum"
    WASHER = "washer"
    WASHER_DRYER = "washer_dryer"


class Retailer(str, Enum):
    """Supported retailers."""

    AMAZON_AT = "Amazon AT"
    MEDIAMARKT_AT = "MediaMarkt AT"
    EXPERT_AT = "Expert AT"
    CYBERPORT_AT = "Cyberport AT"
    ELECTRONIC4YOU = "electronic4you.at"
    ETEC = "E-Tec"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Domain Models (Dataclasses for internal use)
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


@dataclass(frozen=True)
class TargetRecord:
    """A target product with precomputed signals."""

    product: dict[str, Any]
    signals: ProductSignals
    visible: bool
    category_norm: str
    canonical_url: str | None


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# API Schemas (Pydantic for validation and serialization)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class SourceProduct(BaseModel):
    """Schema for source product input."""

    reference: str = Field(..., description="Unique product reference")
    name: str = Field(..., description="Product name")
    brand: str | None = Field(None, description="Brand name")
    ean: str | None = Field(None, description="EAN/GTIN code")
    price_eur: float | None = Field(None, ge=0, description="Price in EUR")
    category: str | None = Field(None, description="Product category")
    specifications: dict[str, Any] | None = Field(
        None, description="Product specifications"
    )


class Competitor(BaseModel):
    """Schema for competitor product output."""

    reference: str = Field(..., description="Competitor product reference")
    competitor_retailer: str = Field(..., description="Retailer name")
    competitor_product_name: str = Field(..., description="Product name")
    competitor_url: str | None = Field(None, description="Product URL")
    competitor_price: float | None = Field(None, ge=0, description="Price in EUR")


class SourceMatch(BaseModel):
    """Schema for source product with its competitor matches."""

    source_reference: str = Field(..., description="Source product reference")
    competitors: list[Competitor] = Field(
        default_factory=list, description="Matched competitors"
    )


class MatchCard(BaseModel):
    """Schema for UI card display."""

    reference: str
    source_reference: str
    name: str
    retailer: str
    price_eur: float | None = None
    image_url: str | None = None
    url: str | None = None


class PriceFilter(BaseModel):
    """Price filter bounds."""

    min: float | None = None
    max: float | None = None


class QueryStats(BaseModel):
    """Statistics from a query execution."""

    query: str
    effective_query: str
    selected_sources: int
    matched_sources: int
    total_links: int
    visible_links: int
    hidden_links: int
    retailer_filter: list[str] = Field(default_factory=list)
    kind_filter: list[str] = Field(default_factory=list)
    anchor_tokens: list[str] = Field(default_factory=list)
    price_filter: PriceFilter = Field(default_factory=PriceFilter)
    follow_up_expand: bool = False
    additional_only: bool = False
    excluded_previous_links: int = 0
    output_file: str | None = None


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# API Request/Response Schemas
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class ChatRequest(BaseModel):
    """Request schema for chat endpoint."""

    query: str = Field("", description="Natural language query")
    source_products: list[dict[str, Any]] | None = Field(
        None, description="Custom source products to search"
    )
    history: list[str] | None = Field(
        None, description="Previous queries for context"
    )
    previous_submission: list[dict[str, Any]] | None = Field(
        None, description="Previous results for deduplication"
    )
    persist_output: bool = Field(True, description="Save results to disk")
    max_sources: int = Field(5, ge=1, le=200, description="Max source products")
    max_competitors_per_source: int = Field(
        12, ge=1, le=100, description="Max competitors per source"
    )


class ChatResponse(BaseModel):
    """Response schema for chat endpoint."""

    answer: str = Field(..., description="Natural language response")
    submission: list[SourceMatch] = Field(
        ..., description="Structured match results"
    )
    cards: list[MatchCard] = Field(..., description="UI card data")
    stats: dict[str, Any] = Field(..., description="Query statistics")


class HealthResponse(BaseModel):
    """Response schema for health endpoint."""

    status: str = Field(..., description="Service status")
    version: str = Field(..., description="API version")
    sources: int = Field(..., description="Number of source products")
    targets: int = Field(..., description="Number of target products")
