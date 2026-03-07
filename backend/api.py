from __future__ import annotations

from backend.matcher_service import matcher


def _build_answer(stats: dict, submission: list) -> str:
    """Build a natural, informative chat response from matcher stats + submission."""
    selected: int = stats.get("selected_sources", 0)
    matched: int = stats.get("matched_sources", 0)
    total: int = stats.get("total_links", 0)
    visible: int = stats.get("visible_links", 0)
    hidden: int = stats.get("hidden_links", 0)
    kind_filter: list = stats.get("kind_filter") or []
    retailer_filter: list = stats.get("retailer_filter") or []
    price_filter: dict = stats.get("price_filter") or {}
    excluded: int = stats.get("excluded_previous_links", 0)
    follow_up: bool = bool(stats.get("follow_up_expand"))
    additional_only: bool = bool(stats.get("additional_only"))

    source_names = {
        s.get("reference", ""): s.get("name", "")
        for s in matcher.default_sources
    }

    # ── no sources resolved ──────────────────────────────────────────────────
    if selected == 0:
        hints = []
        if kind_filter:
            hints.append(f"I understood you're looking for: {', '.join(kind_filter)}.")
        return (
            "I couldn't find any source products that match your query. "
            + (" ".join(hints) + " " if hints else "")
            + "Try searching by product name, brand, category (TV & Audio, Small Appliances, "
            "Large Appliances), or paste a reference like P_0A7A0D68."
        )

    # ── follow-up expand with no new results ─────────────────────────────────
    if follow_up and total == 0:
        msg = "I've already shown all available competitor links for this product set."
        if excluded:
            msg += f" ({excluded} previously shown link{'s' if excluded != 1 else ''} were skipped.)"
        return msg

    # ── no matches found ─────────────────────────────────────────────────────
    if total == 0:
        lines = [
            f"I searched {selected} source product{'s' if selected > 1 else ''} "
            "but found no competitor matches in the local database."
        ]
        if stats.get("fallback_reason") == "no_local_target_files":
            lines.append(
                "The local target database appears to be empty. "
                "Set BRAVE_SEARCH_API_KEY in your .env to enable live web search as fallback."
            )
        else:
            lines.append(
                "These products may not yet be indexed in the competitor pool. "
                "Try broadening your search or ask for 'all' products to scan the full catalog."
            )
        return "\n".join(lines)

    # ── main case: matches found ─────────────────────────────────────────────
    lines = []

    # Intro
    if additional_only:
        intro = (
            f"Here are {total} additional competitor link{'s' if total > 1 else ''} "
            f"for {matched} of {selected} source product{'s' if selected > 1 else ''}."
        )
    elif selected == matched:
        intro = (
            f"Found {total} competitor link{'s' if total > 1 else ''} "
            f"for all {matched} source product{'s' if matched > 1 else ''}."
        )
    else:
        no_match = selected - matched
        intro = (
            f"Found {total} competitor link{'s' if total > 1 else ''} "
            f"for {matched} of {selected} source products "
            f"({no_match} had no match)."
        )
    lines.append(intro)

    # Retailer breakdown
    if visible > 0 and hidden > 0:
        lines.append(
            f"  {visible} from visible retailers · {hidden} from hidden retailers."
        )
    elif hidden > 0 and visible == 0:
        lines.append(f"  All from hidden retailers.")

    # Active filters understood
    filters_understood = []
    if kind_filter:
        filters_understood.append(f"product type: {', '.join(kind_filter)}")
    if retailer_filter:
        filters_understood.append(f"retailer: {', '.join(retailer_filter)}")
    if price_filter.get("min") is not None or price_filter.get("max") is not None:
        mn = f"€{price_filter['min']}" if price_filter.get("min") is not None else ""
        mx = f"€{price_filter['max']}" if price_filter.get("max") is not None else ""
        filters_understood.append(f"price {mn}–{mx}".strip(" –"))
    if filters_understood:
        lines.append(f"  Understood filters → {', '.join(filters_understood)}.")

    # Per-source breakdown
    matched_entries = [e for e in submission if e.get("competitors")]
    if matched_entries:
        lines.append("")
        lines.append("Competitor links per product:")
        for entry in matched_entries:
            ref = entry["source_reference"]
            name = source_names.get(ref) or ref
            comps = entry["competitors"]
            retailers = list(dict.fromkeys(c["competitor_retailer"] for c in comps))
            if len(comps) == 1:
                c = comps[0]
                lines.append(
                    f"  • {name}\n"
                    f"    → {c['competitor_product_name'][:60]} "
                    f"({c['competitor_retailer']}"
                    + (f", €{c['competitor_price']:.2f}" if c.get("competitor_price") else "")
                    + ")"
                )
            else:
                lines.append(
                    f"  • {name}\n"
                    f"    → {len(comps)} links from: {', '.join(retailers)}"
                )

    # Unmatched sources
    unmatched_entries = [e for e in submission if not e.get("competitors")]
    if unmatched_entries:
        names = [
            source_names.get(e["source_reference"]) or e["source_reference"]
            for e in unmatched_entries
        ]
        lines.append("")
        lines.append(
            f"No competitor found for: {', '.join(names)}."
        )

    # Fallback note
    if stats.get("fallback_used"):
        lines.append("")
        lines.append(
            "Note: local target DB was unavailable — results fetched via live web search."
        )

    # Output file
    if stats.get("output_file"):
        lines.append("")
        lines.append(f"Saved scoring output → {stats['output_file']}.")

    return "\n".join(lines)

try:
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware
    from pydantic import BaseModel, Field
except ModuleNotFoundError as exc:  # pragma: no cover
    FastAPI = None  # type: ignore[assignment]
    CORSMiddleware = None  # type: ignore[assignment]
    BaseModel = object  # type: ignore[assignment]
    Field = None  # type: ignore[assignment]
    _IMPORT_ERROR = exc
else:
    _IMPORT_ERROR = None


if FastAPI is not None:
    class CompetitorOut(BaseModel):
        reference: str
        competitor_retailer: str
        competitor_product_name: str
        competitor_url: str | None = None
        competitor_price: float | None = None


    class SourceMatchOut(BaseModel):
        source_reference: str
        competitors: list[CompetitorOut]


    class CardOut(BaseModel):
        reference: str
        source_reference: str
        name: str
        retailer: str
        price_eur: float | None = None
        image_url: str | None = None
        url: str | None = None


    class ChatRequest(BaseModel):
        query: str = ""
        source_products: list[dict] | None = None
        history: list[str] | None = None
        previous_submission: list[dict] | None = None
        persist_output: bool = True
        max_sources: int = Field(default=5, ge=1, le=200)
        max_competitors_per_source: int = Field(default=12, ge=1, le=100)


    class ChatResponse(BaseModel):
        answer: str
        submission: list[SourceMatchOut]
        cards: list[CardOut]
        stats: dict


    class HealthResponse(BaseModel):
        status: str
        sources: int
        targets: int


    app = FastAPI(title="Competitor Matcher API", version="1.0.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:8080",
            "http://127.0.0.1:8080",
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


    @app.get("/api/v1/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(
            status="ok",
            sources=len(matcher.default_sources),
            targets=len(matcher.targets),
        )


    @app.post("/api/v1/chat", response_model=ChatResponse)
    def chat(request: ChatRequest) -> ChatResponse:
        submission, cards, stats = matcher.query(
            query=request.query,
            source_products=request.source_products,
            max_sources=request.max_sources,
            max_competitors_per_source=request.max_competitors_per_source,
            history=request.history,
            previous_submission=request.previous_submission,
            persist_output=request.persist_output,
        )
        answer = _build_answer(stats, submission)
        return ChatResponse(answer=answer, submission=submission, cards=cards, stats=stats)
else:  # pragma: no cover
    app = None

    def __getattr__(name: str):
        if name == "app":
            raise RuntimeError(
                f"Cannot create FastAPI app: missing dependency ({_IMPORT_ERROR}). "
                "Run `uv sync` to install backend dependencies."
            )
        raise AttributeError(name)
