import os
import requests
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
    prompt = build_expansion_prompt(source)
    response = _call_openrouter(EXPANSION_SYSTEM, prompt, model)
    terms = []
    for line in response.splitlines():
        term = line.strip().lstrip("-•*→").strip()
        if term:
            terms.append(term)
    assert terms, f"Query expansion returned no terms for {source.get('reference')}: {response!r}"
    return terms[:max_terms]
