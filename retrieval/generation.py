import os
import requests
from models import Competitor, SourceMatch
from prompts import MATCH_SYSTEM, build_match_prompt


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


def _parse_decisions(response: str, candidates: list[dict]) -> list[str]:
    """Parse 'P_XXXXX: MATCH/NO_MATCH' lines, return list of matched references."""
    valid_refs = {c["reference"] for c in candidates}
    matched = []
    for line in response.splitlines():
        line = line.strip()
        if not line:
            continue
        assert ": " in line, f"Unexpected LLM output line (missing ': '): {line!r}"
        ref, decision = line.split(": ", 1)
        ref, decision = ref.strip().strip("[]"), decision.strip()
        decision = decision.upper().strip().rstrip(".")
        assert ref in valid_refs, f"LLM returned unknown reference: {ref!r}"
        assert decision in ("MATCH", "NO_MATCH"), f"Unexpected decision for {ref}: {decision!r}"
        if decision == "MATCH":
            matched.append(ref)
    return matched


def filter_candidates(
    source: dict, candidates: list[dict], model: str, batch_size: int
) -> SourceMatch:
    """
    Split candidates into batches of batch_size, one LLM call per batch.
    LLM outputs '<reference>: MATCH/NO_MATCH' per line.
    Returns SourceMatch with all confirmed matches.
    """
    candidates = [c for c in candidates if c["reference"] != source["reference"]]
    if not candidates:
        return SourceMatch(source_reference=source["reference"], competitors=[])

    candidate_index = {c["reference"]: c for c in candidates}
    matched_refs: list[str] = []

    for i in range(0, len(candidates), batch_size):
        batch = candidates[i : i + batch_size]
        prompt = build_match_prompt(source, batch)

        b = i // batch_size + 1
        print(f"\n  ── LLM batch {b} ({len(batch)} candidates) ──────────────────────────")
        print(f"  SOURCE : [{source['reference']}] {(source.get('name') or '')[:80]}")
        brand = source.get('brand') or '-'
        price = source.get('price_eur') or '-'
        ean = source.get('ean') or '-'
        print(f"           brand={brand}  price={price}  ean={ean}")
        print(f"  CANDIDATES:")
        for c in batch:
            print(f"    [{c['reference']}] {(c.get('name') or '')[:75]}")

        response = _call_openrouter(MATCH_SYSTEM, prompt, model)

        print(f"  LLM RESPONSE:")
        for line in response.splitlines():
            print(f"    {line}")

        matched_refs.extend(_parse_decisions(response, batch))

    competitors = [
        Competitor(
            reference=ref,
            competitor_retailer=candidate_index[ref].get("retailer") or "",
            competitor_product_name=candidate_index[ref].get("name") or "",
            competitor_url=candidate_index[ref].get("url"),
            competitor_price=candidate_index[ref].get("price_eur"),
        )
        for ref in matched_refs
    ]
    return SourceMatch(source_reference=source["reference"], competitors=competitors)
