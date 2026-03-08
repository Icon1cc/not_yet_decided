"""
Chat endpoint for Vercel.
Supports OpenAI and OpenRouter for AI agent.
"""

import json
import sys
from pathlib import Path
from http.server import BaseHTTPRequestHandler

# Add project root to path
root = Path(__file__).parent.parent
sys.path.insert(0, str(root))


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        """Handle CORS preflight."""
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_POST(self):
        try:
            from backend.app.services.catalog import get_matcher
            from backend.app.services.agent import get_agent
            from backend.app.api.response_builder import build_answer

            # Read request body
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            request = json.loads(body) if body else {}

            query = request.get("query", "")
            source_products = request.get("source_products")
            history = request.get("history")
            previous_submission = request.get("previous_submission")
            max_sources = request.get("max_sources", 5)
            max_competitors = request.get("max_competitors_per_source", 12)
            persist_output = request.get("persist_output", False)  # Don't persist on Vercel

            matcher = get_matcher()
            agent = get_agent()

            # Build conversation history for agent
            conversation_history = []
            if history:
                for i, msg in enumerate(history):
                    conversation_history.append({
                        "role": "user" if i % 2 == 0 else "assistant",
                        "content": msg
                    })

            # Process with AI agent
            agent_response = agent.process_message(
                user_message=query,
                conversation_history=conversation_history,
            )

            # If no search needed, return agent response
            if not agent_response.get("needs_search", True):
                response = {
                    "answer": agent_response.get("response", ""),
                    "submission": [],
                    "cards": [],
                    "stats": {
                        "query": query,
                        "effective_query": query,
                        "selected_sources": 0,
                        "matched_sources": 0,
                        "total_links": 0,
                        "visible_links": 0,
                        "hidden_links": 0,
                        "retailer_filter": [],
                        "kind_filter": [],
                        "anchor_tokens": [],
                        "price_filter": {"min": None, "max": None},
                        "agent_mode": agent.is_configured,
                    },
                }
                self._send_json(200, response)
                return

            # Build effective query from agent filters
            filters = agent_response.get("filters", {})
            effective_query = self._build_query_from_filters(query, filters)

            # Execute search
            submission, cards, stats = matcher.query(
                query=effective_query,
                source_products=source_products,
                max_sources=filters.get("max_sources", max_sources),
                max_competitors_per_source=max_competitors,
                history=history,
                previous_submission=previous_submission,
                persist_output=False,  # Never persist on Vercel (read-only filesystem)
            )

            # Build response
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

            stats["agent_mode"] = agent.is_configured
            stats["agent_thinking"] = agent_response.get("thinking", "")
            stats["output_file"] = None  # No file output on Vercel

            # Format submission for response
            submission_out = [
                {
                    "source_reference": s["source_reference"],
                    "competitors": [
                        {
                            "reference": c["reference"],
                            "competitor_retailer": c["competitor_retailer"],
                            "competitor_product_name": c["competitor_product_name"],
                            "competitor_url": c.get("competitor_url"),
                            "competitor_price": c.get("competitor_price"),
                        }
                        for c in s["competitors"]
                    ],
                }
                for s in submission
            ]

            cards_out = [
                {
                    "reference": c["reference"],
                    "source_reference": c["source_reference"],
                    "name": c["name"],
                    "retailer": c["retailer"],
                    "price_eur": c.get("price_eur"),
                    "image_url": c.get("image_url"),
                    "url": c.get("url"),
                }
                for c in cards
            ]

            response = {
                "answer": answer,
                "submission": submission_out,
                "cards": cards_out,
                "stats": stats,
            }

            self._send_json(200, response)

        except Exception as e:
            import traceback
            traceback.print_exc()
            self._send_json(500, {"error": str(e)})

    def _send_json(self, status: int, data: dict):
        """Send JSON response with CORS headers."""
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def _build_query_from_filters(self, original_query: str, filters: dict) -> str:
        """Build effective search query from agent filters."""
        parts = []

        product_types = filters.get("product_types", [])
        if product_types:
            parts.extend(product_types)

        brands = filters.get("brands", [])
        if brands:
            parts.extend(brands)

        categories = filters.get("categories", [])
        if categories:
            parts.extend(categories)

        retailers = filters.get("retailers", [])
        if retailers:
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

        price_max = filters.get("price_max")
        if price_max is not None:
            parts.append(f"under {price_max}")

        price_min = filters.get("price_min")
        if price_min is not None:
            parts.append(f"over {price_min}")

        references = filters.get("references", [])
        if references:
            parts.extend(references)

        if parts:
            search_query = filters.get("search_query", "")
            if search_query and search_query.lower() != original_query.lower():
                return f"{' '.join(parts)} {search_query}"
            return " ".join(parts)

        return original_query
