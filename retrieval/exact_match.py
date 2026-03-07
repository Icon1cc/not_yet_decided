from typing import Any


def get_field(doc: dict, field: str) -> Any:
    """Supports dot-notation for nested fields, e.g. 'specifications.GTIN'."""
    parts = field.split(".", 1)
    value = doc.get(parts[0])
    if len(parts) == 1:
        return value
    if not isinstance(value, dict):
        return None
    return get_field(value, parts[1])


def exact_match(
    source: dict,
    targets: list[dict],
    columns: list[dict],
    threshold: float,
) -> list[tuple[dict, float]]:
    """
    For each target, sum weights of fields that match the source exactly.
    Returns targets whose cumulative weight >= threshold, with their score.
    """
    results = []
    for target in targets:
        score = 0.0
        for col in columns:
            src_val = get_field(source, col["source_field"])
            tgt_val = get_field(target, col["target_field"])
            if src_val is not None and tgt_val is not None and src_val == tgt_val:
                score += col["weight"]
        if score >= threshold:
            results.append((target, score))
    results.sort(key=lambda x: x[1], reverse=True)
    return results
