"""
API routes for the Competitor Matcher service.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException

from backend.app.core.models import (
    ChatRequest,
    ChatResponse,
    Competitor,
    HealthResponse,
    MatchCard,
    SourceMatch,
)
from backend.app.services.catalog import get_matcher
from backend.app.services.agent import get_agent
from backend.app.api.response_builder import build_answer

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["chat"])


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """
    Health check endpoint.

    Returns service status and product counts.
    """
    try:
        matcher = get_matcher()
        agent = get_agent()
        return HealthResponse(
            status="ok" if agent.is_configured else "ok (basic mode)",
            version="1.0.0",
            sources=len(matcher.default_sources),
            targets=len(matcher.targets),
        )
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    """
    Process a natural language query and return competitor matches.

    Uses AI agent for intelligent conversation and query understanding.
    """
    try:
        matcher = get_matcher()
        agent = get_agent()

        # Build conversation history for agent context
        conversation_history = []
        if request.history:
            for i, msg in enumerate(request.history):
                conversation_history.append({
                    "role": "user" if i % 2 == 0 else "assistant",
                    "content": msg
                })

        # Process with AI agent
        agent_response = agent.process_message(
            user_message=request.query,
            conversation_history=conversation_history,
        )

        logger.info(f"Agent thinking: {agent_response.get('thinking', '')[:100]}...")
        logger.info(f"Agent filters: {agent_response.get('filters', {})}")

        # If agent says no search needed, return just the response
        if not agent_response.get("needs_search", True):
            return ChatResponse(
                answer=agent_response.get("response", ""),
                submission=[],
                cards=[],
                stats={
                    "query": request.query,
                    "effective_query": request.query,
                    "selected_sources": 0,
                    "matched_sources": 0,
                    "total_links": 0,
                    "visible_links": 0,
                    "hidden_links": 0,
                    "retailer_filter": [],
                    "kind_filter": [],
                    "anchor_tokens": [],
                    "price_filter": {"min": None, "max": None},
                    "agent_mode": True,
                    "agent_thinking": agent_response.get("thinking", ""),
                },
            )

        # Build effective query from agent filters
        filters = agent_response.get("filters", {})
        effective_query = _build_query_from_filters(request.query, filters)

        # Execute search with matcher
        submission, cards, stats = matcher.query(
            query=effective_query,
            source_products=request.source_products,
            max_sources=filters.get("max_sources", request.max_sources),
            max_competitors_per_source=request.max_competitors_per_source,
            history=request.history,
            previous_submission=request.previous_submission,
            persist_output=request.persist_output,
        )

        # Build intelligent response with results
        if agent.is_configured:
            answer = agent.build_result_response(
                agent_response=agent_response,
                search_results={
                    "submission": submission,
                    "cards": cards,
                    "stats": stats,
                    "answer": build_answer(stats, submission),
                },
            )
        else:
            answer = build_answer(stats, submission)

        # Add agent metadata to stats
        stats["agent_mode"] = agent.is_configured
        stats["agent_thinking"] = agent_response.get("thinking", "")
        stats["agent_filters"] = filters

        # Convert to response models
        submission_out = [
            SourceMatch(
                source_reference=s["source_reference"],
                competitors=[
                    Competitor(
                        reference=c["reference"],
                        competitor_retailer=c["competitor_retailer"],
                        competitor_product_name=c["competitor_product_name"],
                        competitor_url=c.get("competitor_url"),
                        competitor_price=c.get("competitor_price"),
                    )
                    for c in s["competitors"]
                ],
            )
            for s in submission
        ]

        cards_out = [
            MatchCard(
                reference=c["reference"],
                source_reference=c["source_reference"],
                name=c["name"],
                retailer=c["retailer"],
                price_eur=c.get("price_eur"),
                image_url=c.get("image_url"),
                url=c.get("url"),
            )
            for c in cards
        ]

        return ChatResponse(
            answer=answer,
            submission=submission_out,
            cards=cards_out,
            stats=stats,
        )

    except Exception as e:
        logger.exception(f"Chat endpoint failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


def _build_query_from_filters(original_query: str, filters: dict[str, Any]) -> str:
    """Build an effective search query from agent-extracted filters."""
    parts = []

    # Add product types
    product_types = filters.get("product_types", [])
    if product_types:
        parts.extend(product_types)

    # Add brands
    brands = filters.get("brands", [])
    if brands:
        parts.extend(brands)

    # Add categories
    categories = filters.get("categories", [])
    if categories:
        parts.extend(categories)

    # Add retailers
    retailers = filters.get("retailers", [])
    if retailers:
        # Convert to keywords the matcher understands
        retailer_keywords = {
            "Amazon AT": "amazon",
            "MediaMarkt AT": "mediamarkt",
            "Expert AT": "expert",
            "Cyberport AT": "cyberport",
            "electronic4you.at": "electronic4you",
            "E-Tec": "etec",
        }
        for r in retailers:
            if r in retailer_keywords:
                parts.append(retailer_keywords[r])

    # Add price constraints
    price_min = filters.get("price_min")
    price_max = filters.get("price_max")
    if price_max is not None:
        parts.append(f"under {price_max}")
    if price_min is not None:
        parts.append(f"over {price_min}")

    # Add references
    references = filters.get("references", [])
    if references:
        parts.extend(references)

    # If we have agent-extracted parts, use them; otherwise use original query
    if parts:
        # Also include key terms from search_query if provided
        search_query = filters.get("search_query", "")
        if search_query and search_query.lower() != original_query.lower():
            return f"{' '.join(parts)} {search_query}"
        return " ".join(parts)

    return original_query
