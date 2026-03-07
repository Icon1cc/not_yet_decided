from __future__ import annotations

from backend.matcher_service import matcher

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
        if stats.get("follow_up_expand") and stats["total_links"] == 0:
            answer = (
                f"No additional competitor links were found for the current product set. "
                f"Excluded {stats.get('excluded_previous_links', 0)} links that were already shown."
            )
        elif stats.get("additional_only"):
            answer = (
                f"Found {stats['total_links']} additional competitor links for "
                f"{stats['matched_sources']}/{stats['selected_sources']} source products."
            )
        else:
            answer = (
                f"Matched {stats['matched_sources']}/{stats['selected_sources']} source products and found "
                f"{stats['total_links']} competitor links ({stats['visible_links']} visible, {stats['hidden_links']} hidden)."
            )
        if stats.get("kind_filter"):
            answer = f"{answer} Applied kind filter: {', '.join(stats['kind_filter'])}."
        if stats.get("fallback_used"):
            answer = (
                f"{answer} No local target DB was available, so results were fetched via live web search fallback."
            )
        elif stats.get("fallback_reason") == "no_local_target_files":
            answer = (
                f"{answer} Local target DB is empty. Set `BRAVE_SEARCH_API_KEY` (or `BRAVE_API_KEY`) to enable live web search fallback."
            )
        if stats.get("output_file"):
            answer = f"{answer} Saved scoring output to {stats['output_file']}."
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
