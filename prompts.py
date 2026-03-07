from retrieval.indexing import product_to_chunk

MATCH_SYSTEM = """You are a product matching expert for an Austrian retailer.

You receive a SOURCE product and a list of CANDIDATE products from competitor retailers.
For each candidate decide if it is the SAME or EQUIVALENT product as the source, sold by a different retailer.

Rules for MATCH:
- Same brand AND same core model number/identifier (e.g. "32LQ63806LC" must match "32LQ63806LC")
- Minor listing differences OK: extra words, retailer suffix, translated descriptions
- Color/finish suffix variants OK if core model matches

Rules for NO_MATCH:
- Different screen size (e.g. 32" vs 40") = NOT the same product
- Different model number = NOT the same product
- Same brand but different product line or specs = NOT the same product
- Clearly different product type = NOT the same product

Output exactly one line per candidate in this format:
<reference>: MATCH
<reference>: NO_MATCH

No other text. No explanations.
"""


def build_match_prompt(source: dict, candidates: list[dict]) -> str:
    source_chunk = product_to_chunk(source)
    candidate_blocks = []
    for c in candidates:
        chunk = c.get("chunk_text") or product_to_chunk(c)
        candidate_blocks.append(f"[{c['reference']}]\n{chunk}")
    candidates_text = "\n\n".join(candidate_blocks)
    return (
        f"SOURCE PRODUCT:\n{source_chunk}\n\n"
        f"CANDIDATES:\n{candidates_text}\n\n"
        "Output one line per candidate: <reference>: MATCH or <reference>: NO_MATCH"
    )
