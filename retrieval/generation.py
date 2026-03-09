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
    seen_refs: set[str] = set()
    matched = []
    for line in response.splitlines():
        line = line.strip()
        if not line:
            continue
        if ": " not in line:
            raise ValueError(f"LLM output line missing ': ' separator: {line!r}\nFull response:\n{response}")
        ref, decision = line.split(": ", 1)
        ref = ref.strip()
        if ref.startswith("[") or ref.endswith("]"):
            raise ValueError(f"LLM wrapped reference in brackets (prompt format error): {line!r}\nFull response:\n{response}")
        decision = decision.strip().upper().rstrip(".")
        if ref not in valid_refs:
            raise ValueError(f"LLM returned unknown reference {ref!r} (not in candidate batch)\nFull response:\n{response}")
        if decision not in ("MATCH", "NO_MATCH"):
            raise ValueError(f"LLM returned invalid decision for {ref!r}: {decision!r}\nFull response:\n{response}")
        if ref in seen_refs:
            raise ValueError(f"LLM returned duplicate decision for {ref!r}\nFull response:\n{response}")
        seen_refs.add(ref)
        if decision == "MATCH":
            matched.append(ref)
    missing = valid_refs - seen_refs
    if missing:
        print(f"  [WARN] LLM skipped {len(missing)} candidates (treating as NO_MATCH): {missing}")
    return matched


def filter_candidates(
    source: dict, candidates: list[dict], model: str, batch_size: int
) -> SourceMatch:
    """
    Split candidates into batches of batch_size, one LLM call per batch.
    LLM outputs '<reference>: MATCH/NO_MATCH' per line.
    Returns SourceMatch with all confirmed matches.
    """
    src_retailer = source.get("retailer")
    candidates = [
        c for c in candidates
        if c["reference"] != source["reference"]
        and (src_retailer is None or c.get("retailer") != src_retailer)
    ]
    if not candidates:
        return SourceMatch(source_reference=source["reference"], competitors=[])

    candidate_index = {c["reference"]: c for c in candidates}
    matched_refs: list[str] = []

    for i in range(0, len(candidates), batch_size):
        batch = candidates[i : i + batch_size]
        prompt = build_match_prompt(source, batch)

        b = i // batch_size + 1
        print(f"\n  -- LLM batch {b} ({len(batch)} candidates) --------------------------")
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
