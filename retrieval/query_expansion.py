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


def expand_query(source: dict, model: str, max_terms: int = 8, expansion_model: str | None = None) -> list[str]:
    """
    Build search terms for BM25 retrieval:
    1. Pre-inject EAN and model_number directly (exact signal, no LLM)
    2. LLM extracts up to max_terms additional discriminative terms (series name, synonyms, etc.)
    Returns deduplicated list, high-signal terms first.
    """
    # --- direct high-signal terms (no LLM) ---
    direct: list[str] = []
    ean = source.get("ean")
    if ean:
        direct.append(str(ean))
    specs = source.get("specifications") or {}
    for key in ("GTIN", "EAN", "EAN-Code"):
        val = specs.get(key)
        if val and str(val) not in direct:
            direct.append(str(val))
    model_number = source.get("model_number")
    if model_number and model_number not in direct:
        direct.append(model_number)

    print(f"    [expansion] direct terms: {direct}")

    # --- LLM expansion ---
    prompt = build_expansion_prompt(source)
    response = _call_openrouter(EXPANSION_SYSTEM, prompt, expansion_model or model)
    print(f"    [expansion] LLM raw:\n" + "\n".join(f"      {l}" for l in response.splitlines()))

    seen = set(t.lower() for t in direct)
    llm_terms: list[str] = []
    for line in response.splitlines():
        term = line.strip().lstrip("-•*→").strip()
        if term and term.lower() not in seen:
            llm_terms.append(term)
            seen.add(term.lower())

    all_terms = direct + llm_terms
    assert all_terms, f"Query expansion returned no terms for {source.get('reference')}: {response!r}"
    return all_terms[:max_terms]
