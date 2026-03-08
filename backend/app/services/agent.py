"""
AI Agent Service using OpenRouter/Claude.

Provides intelligent, conversational product matching with reasoning capabilities.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import httpx

from backend.app.core.config import get_settings

logger = logging.getLogger(__name__)

# System prompt for the agent
AGENT_SYSTEM_PROMPT = """You are an intelligent product matching assistant for Austrian electronics retailers. You help users find competitor prices for products across Amazon AT, MediaMarkt AT, Expert AT, Cyberport AT, electronic4you.at, and E-Tec.

## Your Capabilities
You have access to a product database with:
- 90 source products (the user's catalog) across TV & Audio, Small Appliances, and Large Appliances
- 6,364+ target products from competitor retailers

## How to Respond

1. **Understand the Intent**: Carefully analyze what the user is asking for. They might want:
   - Product matches for specific items (by name, brand, category)
   - Price comparisons
   - Filtering by retailer, price range, or product type
   - Follow-up questions about previous results
   - General questions about the data

2. **Extract Structured Filters**: From the user's message, identify:
   - `product_types`: tv, washer, dishwasher, fridge, freezer, dryer, headphone, coffee_machine, air_fryer, vacuum, toaster, kettle, mixer, microwave, etc.
   - `brands`: Samsung, LG, Bosch, Siemens, Sony, Philips, Miele, etc.
   - `price_min` / `price_max`: Price bounds in EUR
   - `retailers`: Amazon AT, MediaMarkt AT, Expert AT, Cyberport AT, electronic4you.at, E-Tec
   - `categories`: TV & Audio, Small Appliances, Large Appliances
   - `references`: Product IDs like P_0A7A0D68

3. **Be Conversational**:
   - Acknowledge what the user asked
   - Explain what you're searching for
   - If results are found, summarize them helpfully
   - If no results, suggest alternatives
   - Ask clarifying questions when needed

4. **Handle Follow-ups**: Remember context from the conversation. If the user says "show more" or "what about cheaper ones", relate it to previous results.

## Response Format

You MUST respond with a JSON object containing:
```json
{
  "thinking": "Your internal reasoning about what the user wants...",
  "response": "Your natural language response to show the user",
  "filters": {
    "product_types": ["tv"],
    "brands": ["samsung"],
    "price_min": null,
    "price_max": 500,
    "retailers": [],
    "categories": [],
    "references": [],
    "search_query": "samsung tv",
    "max_sources": 5,
    "is_follow_up": false,
    "wants_more_results": false
  },
  "needs_search": true
}
```

Set `needs_search: false` if the user is just chatting or asking questions that don't require a product search.

## Examples

User: "Hi, what can you help me with?"
```json
{
  "thinking": "User is greeting and asking about capabilities. No product search needed.",
  "response": "Hello! I'm your competitor price intelligence assistant. I can help you:\\n\\n• Find competitor prices for your products across 6 Austrian retailers\\n• Search by brand, category, price range, or specific product\\n• Compare prices between visible retailers (Amazon, MediaMarkt) and hidden ones (Expert, Cyberport, electronic4you, E-Tec)\\n\\nTry asking something like \\"Show me Samsung TVs under €500\\" or \\"Find competitors for Bosch dishwashers\\"!",
  "filters": {},
  "needs_search": false
}
```

User: "Show me Samsung TVs under 500 euros"
```json
{
  "thinking": "User wants Samsung brand TVs with max price €500. I should search for TVs filtered by brand and price.",
  "response": "I'll search for Samsung TVs under €500 across all retailers.",
  "filters": {
    "product_types": ["tv"],
    "brands": ["samsung"],
    "price_max": 500,
    "search_query": "samsung tv"
  },
  "needs_search": true
}
```

User: "What about from Cyberport only?"
```json
{
  "thinking": "This is a follow-up to the previous Samsung TV search. User wants to filter to Cyberport retailer only.",
  "response": "Let me filter those Samsung TV results to show only Cyberport listings.",
  "filters": {
    "product_types": ["tv"],
    "brands": ["samsung"],
    "price_max": 500,
    "retailers": ["Cyberport AT"],
    "is_follow_up": true
  },
  "needs_search": true
}
```

User: "Show me all washing machines"
```json
{
  "thinking": "User wants washing machines. This is the 'washer' product type in Large Appliances category.",
  "response": "I'll find all washing machines and their competitor prices for you.",
  "filters": {
    "product_types": ["washer"],
    "categories": ["Large Appliances"],
    "search_query": "washing machine",
    "max_sources": 10
  },
  "needs_search": true
}
```

Always respond with valid JSON only. No markdown code blocks, just the raw JSON object."""


class AIAgent:
    """
    Intelligent conversational agent using Claude via OpenRouter.

    Provides natural conversation flow with product search capabilities.
    """

    def __init__(self):
        """Initialize the AI agent."""
        settings = get_settings()
        self.api_key = settings.openrouter_api_key or os.getenv("OPENROUTER_API_KEY", "")
        self.base_url = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
        self.model = os.getenv("OPENROUTER_MODEL", "anthropic/claude-sonnet-4")
        self.conversation_history: list[dict[str, str]] = []
        self.last_filters: dict[str, Any] = {}

    @property
    def is_configured(self) -> bool:
        """Check if the agent is properly configured with an API key."""
        return bool(self.api_key)

    def _call_llm(self, messages: list[dict[str, str]]) -> str:
        """Call the LLM via OpenRouter."""
        if not self.api_key:
            raise ValueError("OPENROUTER_API_KEY not configured")

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://competitor-matcher.local",
            "X-Title": "Competitor Matcher Agent",
        }

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.3,
            "max_tokens": 2000,
        }

        try:
            with httpx.Client(timeout=60.0) as client:
                response = client.post(
                    f"{self.base_url}/chat/completions",
                    headers=headers,
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()
                return data["choices"][0]["message"]["content"]
        except httpx.HTTPStatusError as e:
            logger.error(f"OpenRouter API error: {e.response.status_code} - {e.response.text}")
            raise
        except Exception as e:
            logger.error(f"LLM call failed: {e}")
            raise

    def _parse_agent_response(self, llm_output: str) -> dict[str, Any]:
        """Parse the agent's JSON response."""
        # Clean up potential markdown code blocks
        cleaned = llm_output.strip()
        if cleaned.startswith("```json"):
            cleaned = cleaned[7:]
        if cleaned.startswith("```"):
            cleaned = cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()

        try:
            return json.loads(cleaned)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse agent response: {e}\nResponse: {llm_output}")
            # Return a fallback response
            return {
                "thinking": "Failed to parse response",
                "response": "I apologize, but I had trouble processing that request. Could you please rephrase your question?",
                "filters": {},
                "needs_search": False,
            }

    def process_message(
        self,
        user_message: str,
        conversation_history: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        """
        Process a user message and return agent response with filters.

        Args:
            user_message: The user's input message
            conversation_history: Optional list of previous messages

        Returns:
            Dict containing:
            - thinking: Agent's reasoning (for debugging)
            - response: Natural language response for the user
            - filters: Extracted search filters
            - needs_search: Whether to perform a product search
        """
        if not self.is_configured:
            return {
                "thinking": "No API key configured",
                "response": "I'm running in basic mode without AI capabilities. I can still search for products - just tell me what you're looking for (e.g., 'Samsung TVs' or 'dishwashers under €500').",
                "filters": self._extract_basic_filters(user_message),
                "needs_search": True,
            }

        # Build messages for LLM
        messages = [{"role": "system", "content": AGENT_SYSTEM_PROMPT}]

        # Add conversation history
        if conversation_history:
            for msg in conversation_history[-10:]:  # Keep last 10 messages for context
                messages.append(msg)

        # Add current user message
        messages.append({"role": "user", "content": user_message})

        # Call LLM
        try:
            llm_response = self._call_llm(messages)
            parsed = self._parse_agent_response(llm_response)

            # Store filters for follow-up context
            if parsed.get("filters"):
                self.last_filters = parsed["filters"]

            return parsed

        except Exception as e:
            logger.error(f"Agent processing failed: {e}")
            # Fallback to basic extraction
            return {
                "thinking": f"LLM call failed: {e}",
                "response": f"I'll search for that using basic matching.",
                "filters": self._extract_basic_filters(user_message),
                "needs_search": True,
            }

    def _extract_basic_filters(self, query: str) -> dict[str, Any]:
        """Extract basic filters without LLM (fallback)."""
        import re

        query_lower = query.lower()
        filters: dict[str, Any] = {
            "search_query": query,
            "product_types": [],
            "brands": [],
            "retailers": [],
            "categories": [],
            "references": [],
            "price_min": None,
            "price_max": None,
        }

        # Product types
        type_keywords = {
            "tv": ["tv", "television", "fernseher"],
            "washer": ["washing machine", "waschmaschine", "washer"],
            "dishwasher": ["dishwasher", "geschirrspüler", "spülmaschine"],
            "fridge": ["fridge", "refrigerator", "kühlschrank"],
            "headphone": ["headphone", "kopfhörer", "earbuds"],
            "vacuum": ["vacuum", "staubsauger"],
        }
        for ptype, keywords in type_keywords.items():
            if any(kw in query_lower for kw in keywords):
                filters["product_types"].append(ptype)

        # Brands
        brands = ["samsung", "lg", "bosch", "siemens", "sony", "philips", "miele", "panasonic"]
        for brand in brands:
            if brand in query_lower:
                filters["brands"].append(brand)

        # Price extraction
        price_match = re.search(r"under\s*€?\s*(\d+)|below\s*€?\s*(\d+)|max\s*€?\s*(\d+)", query_lower)
        if price_match:
            filters["price_max"] = float(price_match.group(1) or price_match.group(2) or price_match.group(3))

        # Reference extraction
        ref_matches = re.findall(r"P_[A-Z0-9]{8}", query, re.IGNORECASE)
        filters["references"] = [r.upper() for r in ref_matches]

        return filters

    def build_result_response(
        self,
        agent_response: dict[str, Any],
        search_results: dict[str, Any],
    ) -> str:
        """
        Build a final response incorporating search results.

        Args:
            agent_response: The initial agent response
            search_results: Results from the catalog matcher

        Returns:
            Natural language response with results summary
        """
        if not self.is_configured:
            # Use the basic answer from the matcher
            return search_results.get("answer", agent_response.get("response", ""))

        stats = search_results.get("stats", {})
        submission = search_results.get("submission", [])

        total_links = stats.get("total_links", 0)
        matched_sources = stats.get("matched_sources", 0)
        selected_sources = stats.get("selected_sources", 0)

        # Build context for LLM to generate final response
        result_context = f"""
Based on the search, here are the results:
- Sources searched: {selected_sources}
- Sources with matches: {matched_sources}
- Total competitor links found: {total_links}
- Visible retailer links: {stats.get('visible_links', 0)}
- Hidden retailer links: {stats.get('hidden_links', 0)}

Results by source product:
"""
        for entry in submission[:5]:  # Limit to 5 for context
            source_ref = entry.get("source_reference", "")
            competitors = entry.get("competitors", [])
            result_context += f"\n{source_ref}: {len(competitors)} competitor(s)"
            for comp in competitors[:3]:
                result_context += f"\n  - {comp.get('competitor_product_name', '')[:50]} ({comp.get('competitor_retailer', '')}) - €{comp.get('competitor_price', 'N/A')}"

        # Generate conversational response with results
        try:
            messages = [
                {"role": "system", "content": """You are a helpful product matching assistant.
Given search results, provide a natural, conversational summary. Be concise but informative.
Highlight key findings like best prices or notable matches.
If no results were found, suggest alternatives.
Do NOT output JSON - just write a natural response."""},
                {"role": "user", "content": f"User asked: {agent_response.get('response', '')}\n\n{result_context}\n\nProvide a helpful summary of these results."}
            ]

            final_response = self._call_llm(messages)
            return final_response.strip()

        except Exception as e:
            logger.error(f"Failed to generate result response: {e}")
            # Fallback to basic answer
            return search_results.get("answer", agent_response.get("response", ""))


# Global agent instance
_agent: AIAgent | None = None


def get_agent() -> AIAgent:
    """Get or create the global agent instance."""
    global _agent
    if _agent is None:
        _agent = AIAgent()
    return _agent
