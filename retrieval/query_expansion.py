import os
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from matching_utils import build_deterministic_query_terms
from prompts import EXPANSION_SYSTEM, build_expansion_prompt


def _call_openrouter(system: str, user: str, model: str) -> str:
    resp = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={"Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}"},
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        },
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()


def expand_query(source: dict, model: str, max_terms: int = 6) -> list[str]:
    """
    LLM extracts up to max_terms discriminative search terms from the source product.
    Returns list of terms, most discriminative first.
    """
    base_terms = build_deterministic_query_terms(source, max_terms=max_terms)

    if not os.environ.get("OPENROUTER_API_KEY"):
        return base_terms

    prompt = build_expansion_prompt(source)
    try:
        response = _call_openrouter(EXPANSION_SYSTEM, prompt, model)
    except Exception:
        return base_terms

    terms = list(base_terms)
    seen = {term.lower() for term in terms}
    for line in response.splitlines():
        term = line.strip().lstrip("-•*→").strip()
        if term and term.lower() not in seen:
            terms.append(term)
            seen.add(term.lower())

    return terms[:max_terms]
