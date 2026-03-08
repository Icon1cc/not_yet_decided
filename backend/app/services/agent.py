"""AI Agent Service using Google Gemini."""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import httpx

logger = logging.getLogger(__name__)

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
  "response": "Hello! I'm your competitor price intelligence assistant. I can help you:\\n\\n• Find competitor prices for your products across 6 Austrian retailers\\n• Search by brand, category, price range, or specific product\\n• Compare prices between visible retailers (Amazon, MediaMarkt) and hidden ones (Expert, Cyberport, electronic4you, E-Tec)\\n\\nTry asking something like 'Show me Samsung TVs under €500' or 'Find competitors for Bosch dishwashers'!",
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

Always respond with valid JSON only. No markdown code blocks, just the raw JSON object."""


class QuotaExceededError(Exception):
    pass


class APINotEnabledError(Exception):
    pass


class APIError(Exception):
    pass


class AIAgent:
    """Intelligent conversational agent using Google Gemini."""

    def __init__(self):
        self.api_key = os.getenv("GEMINI_API_KEY", "")
        self.model = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
        self.conversation_history: list[dict[str, str]] = []
        self.last_filters: dict[str, Any] = {}
        self.quota_exceeded = False
        logger.info(f"AI Agent initialized: {'configured' if self.api_key else 'no API key'}")

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)

    def _call_gemini(self, messages: list[dict[str, str]]) -> str:
        contents = []
        system_prompt = None

        for msg in messages:
            if msg["role"] == "system":
                system_prompt = msg["content"]
            elif msg["role"] == "user":
                content = msg["content"]
                if system_prompt and not contents:
                    content = f"{system_prompt}\n\n---\n\nUser message: {content}"
                contents.append({"role": "user", "parts": [{"text": content}]})
            elif msg["role"] == "assistant":
                contents.append({"role": "model", "parts": [{"text": msg["content"]}]})

        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent?key={self.api_key}"
        payload = {
            "contents": contents,
            "generationConfig": {"temperature": 0.3, "maxOutputTokens": 2000}
        }

        with httpx.Client(timeout=60.0) as client:
            response = client.post(url, json=payload)

            if response.status_code == 429:
                self.quota_exceeded = True
                raise QuotaExceededError("API quota exceeded. Please upgrade or recharge your credits.")

            if response.status_code == 403:
                error_data = response.json().get("error", {})
                if "SERVICE_DISABLED" in str(error_data):
                    raise APINotEnabledError("Gemini API is not enabled. Please enable it in Google Cloud Console.")
                raise APIError(f"API access denied: {error_data.get('message', 'Unknown error')}")

            response.raise_for_status()
            data = response.json()

            candidates = data.get("candidates", [])
            if candidates:
                content = candidates[0].get("content", {})
                parts = content.get("parts", [])
                if parts:
                    return parts[0].get("text", "")

            raise APIError("No response from Gemini")

    def _parse_agent_response(self, llm_output: str) -> dict[str, Any]:
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
        if not self.is_configured:
            return {
                "thinking": "No API key configured",
                "response": "Gemini API key not configured. Please add GEMINI_API_KEY to your environment variables.",
                "filters": {},
                "needs_search": False,
                "api_error": True,
            }

        if self.quota_exceeded:
            return {
                "thinking": "API quota exceeded",
                "response": "API credits exhausted. Please upgrade or recharge your Gemini API credits to continue using the AI assistant.",
                "filters": {},
                "needs_search": False,
                "quota_exceeded": True,
            }

        messages = [{"role": "system", "content": AGENT_SYSTEM_PROMPT}]

        if conversation_history:
            for msg in conversation_history[-10:]:
                messages.append(msg)

        messages.append({"role": "user", "content": user_message})

        try:
            llm_response = self._call_gemini(messages)
            parsed = self._parse_agent_response(llm_response)

            if parsed.get("filters"):
                self.last_filters = parsed["filters"]

            return parsed

        except QuotaExceededError:
            self.quota_exceeded = True
            return {
                "thinking": "API quota exceeded",
                "response": "API credits exhausted. Please upgrade or recharge your Gemini API credits to continue using the AI assistant.",
                "filters": {},
                "needs_search": False,
                "quota_exceeded": True,
            }

        except APINotEnabledError:
            return {
                "thinking": "API not enabled",
                "response": "The Gemini API needs to be enabled. Please visit Google Cloud Console to enable it.",
                "filters": {},
                "needs_search": False,
                "api_error": True,
            }

        except Exception as e:
            logger.error(f"Agent processing failed: {e}")
            return {
                "thinking": f"API error: {e}",
                "response": "Unable to process request. Please check your API configuration or try again later.",
                "filters": {},
                "needs_search": False,
                "api_error": True,
            }

    def build_result_response(
        self,
        agent_response: dict[str, Any],
        search_results: dict[str, Any],
    ) -> str:
        if not self.is_configured or self.quota_exceeded:
            return search_results.get("answer", agent_response.get("response", ""))

        stats = search_results.get("stats", {})
        submission = search_results.get("submission", [])
        total_links = stats.get("total_links", 0)
        matched_sources = stats.get("matched_sources", 0)
        selected_sources = stats.get("selected_sources", 0)

        result_context = f"""
Based on the search, here are the results:
- Sources searched: {selected_sources}
- Sources with matches: {matched_sources}
- Total competitor links found: {total_links}
- Visible retailer links: {stats.get('visible_links', 0)}
- Hidden retailer links: {stats.get('hidden_links', 0)}

Results by source product:
"""
        for entry in submission[:5]:
            source_ref = entry.get("source_reference", "")
            competitors = entry.get("competitors", [])
            result_context += f"\n{source_ref}: {len(competitors)} competitor(s)"
            for comp in competitors[:3]:
                result_context += f"\n  - {comp.get('competitor_product_name', '')[:50]} ({comp.get('competitor_retailer', '')}) - €{comp.get('competitor_price', 'N/A')}"

        try:
            messages = [
                {"role": "system", "content": "You are a helpful product matching assistant. Given search results, provide a natural, conversational summary. Be concise but informative. Highlight key findings like best prices or notable matches. If no results were found, suggest alternatives. Do NOT output JSON - just write a natural response."},
                {"role": "user", "content": f"User asked: {agent_response.get('response', '')}\n\n{result_context}\n\nProvide a helpful summary of these results."}
            ]
            final_response = self._call_gemini(messages)
            return final_response.strip()

        except QuotaExceededError:
            self.quota_exceeded = True
            return "API credits exhausted. Results shown above. Please upgrade or recharge your credits for AI-powered summaries."

        except Exception as e:
            logger.error(f"Failed to generate result response: {e}")
            return search_results.get("answer", agent_response.get("response", ""))


_agent: AIAgent | None = None


def get_agent() -> AIAgent:
    global _agent
    if _agent is None:
        _agent = AIAgent()
    return _agent
