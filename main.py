import csv
import json
import yaml
import os
from datetime import datetime
from dotenv import load_dotenv
from models import SourceMatch, Submission
from retrieval.exact_match import exact_match
from retrieval.enrichment import enrich_products
from retrieval.qdrant_retrieval import QdrantRetriever
from retrieval.query_expansion import expand_query
from retrieval.generation import filter_candidates
load_dotenv()


def load_json(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def fuse(
    exact_results: list[tuple[dict, float]],
    bm25_results: list[tuple[dict, float]],
    max_candidates: int | None = None,
) -> list[dict]:
    seen = set()
    merged = []
    # exact hits first (highest priority), then bm25 sorted by score desc
    all_results = [(doc, score) for doc, score in exact_results] + \
                  sorted(bm25_results, key=lambda x: x[1], reverse=True)
    for doc, _ in all_results:
        ref = doc["reference"]
        if ref not in seen:
            seen.add(ref)
            merged.append(doc)
    if max_candidates is not None:
        merged = merged[:max_candidates]
    return merged


def main():
    with open("config.yaml", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    sources = load_json(cfg["data"]["source"])

    subset_n = cfg["subset"]["n"]
    if subset_n is not None:
        sources = sources[:subset_n]

    exact_cfg = cfg["exact_match"]
    qdrant_cfg = cfg["qdrant"]
    llm_model = cfg["llm"]["model"]
    batch_size = cfg["llm"]["batch_size"]
    max_candidates = cfg["llm"]["max_candidates"]

    retriever = QdrantRetriever(
        qdrant_cfg["collection"],
        qdrant_cfg["url"],
        qdrant_cfg["embedding_model"],
        os.environ["OPENROUTER_API_KEY"],
    )
    targets = retriever.fetch_all(qdrant_cfg["category_filter"])
    print(f"Fetched {len(targets)} target products from Qdrant")

    print("\nEnriching source products...")
    sources = enrich_products(sources, os.environ["OPENROUTER_API_KEY"])
    print(f"Source product types: { {s['reference']: s.get('product_type') for s in sources} }")

    # ── Phase 1: retrieval (fast) ─────────────────────────────────────────────
    print("=" * 70)
    print("PHASE 1: Retrieval (exact match + Qdrant hybrid)")
    print("=" * 70)

    retrievals = []  # (source, exact_hits, bm25_hits, candidates)
    for source in sources:
        exact_hits = exact_match(source, targets, exact_cfg["columns"], exact_cfg["threshold"])

        terms = expand_query(source, llm_model)
        bm25_hits = retriever.retrieve_multi(
            terms,
            top_k_per_term=qdrant_cfg["top_k_per_term"],
            category=qdrant_cfg["category_filter"],
            min_score=qdrant_cfg["min_score"],
        )

        candidates = fuse(exact_hits, bm25_hits, max_candidates)
        retrievals.append((source, exact_hits, bm25_hits, candidates))

        exact_refs = {d["reference"] for d, _ in exact_hits}
        print(f"\n{source['reference']} | {source.get('name', '')[:60]}")
        print(f"  terms={terms}")
        print(f"  exact={len(exact_hits)}  bm25={len(bm25_hits)}  candidates={len(candidates)}")
        for doc, score in exact_hits:
            print(f"    [EXACT {score:.2f}] {doc['reference']} | {doc.get('name','')[:55]}")
        for doc, score in bm25_hits:
            tag = "BM25+EXACT" if doc["reference"] in exact_refs else "BM25"
            print(f"    [{tag} {score:.2f}] {doc['reference']} | {doc.get('name','')[:55]}")

    # ── Phase 2: LLM reranking in batches ────────────────────────────────────
    print("\n" + "=" * 70)
    print(f"PHASE 2: LLM match/no-match filtering (batch_size={batch_size}, model={llm_model})")
    print("=" * 70)

    llm_results: dict[str, SourceMatch] = {}

    for source, exact_hits, qdrant_hits, candidates in retrievals:
        ref = source["reference"]
        print(f"\n{ref} | {source.get('name', '')[:60]}")
        print(f"  sending {len(candidates)} candidates to LLM (batch_size={batch_size})")
        for c in candidates:
            print(f"    {c['reference']} | {c.get('name','')[:60]}")

        result = filter_candidates(source, candidates, llm_model, batch_size)
        llm_results[ref] = result

        print(f"  → matched={len(result.competitors)}")
        for c in result.competitors:
            print(f"    [✓] {c.reference} | {c.competitor_product_name[:60]}")

    # ── Phase 3: assemble + print summary ────────────────────────────────────
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)

    submission: Submission = []
    csv_rows = []

    for source, exact_hits, qdrant_hits, candidates in retrievals:
        ref = source["reference"]
        llm_result = llm_results[ref]
        submission.append(llm_result)
        llm_refs = {c.reference for c in llm_result.competitors}

        exact_refs = {d["reference"] for d, _ in exact_hits}
        print(f"\n{ref} | {source.get('name', '')[:60]}")
        print(f"  retrieved={len(candidates)}  llm_kept={len(llm_result.competitors)}")
        print(f"  Retrieved candidates:")
        for doc in candidates:
            tag = "EXACT" if doc["reference"] in exact_refs else "QDRANT"
            print(f"    [{tag}] {doc['reference']} | {doc.get('name','')[:50]}")
        print(f"  LLM kept:")
        if llm_result.competitors:
            for c in llm_result.competitors:
                print(f"    [✓] {c.reference} | {c.competitor_product_name[:50]}")
        else:
            print(f"    (none)")

        for doc, score in exact_hits:
            csv_rows.append({"source_ref": ref, "source_name": source.get("name", ""), "match_ref": doc["reference"], "match_name": doc.get("name", ""), "match_retailer": doc.get("retailer", ""), "method": "exact", "score": score, "llm_kept": doc["reference"] in llm_refs})
        for doc, score in qdrant_hits:
            csv_rows.append({"source_ref": ref, "source_name": source.get("name", ""), "match_ref": doc["reference"], "match_name": doc.get("name", ""), "match_retailer": doc.get("retailer", ""), "method": "qdrant", "score": score, "llm_kept": doc["reference"] in llm_refs})
        if not exact_hits and not qdrant_hits:
            csv_rows.append({"source_ref": ref, "source_name": source.get("name", ""), "match_ref": "", "match_name": "", "match_retailer": "", "method": "none", "score": 0, "llm_kept": False})

    # ── Output ────────────────────────────────────────────────────────────────
    out_cfg = cfg["output"]
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    os.makedirs(out_cfg["dir"], exist_ok=True)
    stem = f"{out_cfg['run_name']}_{timestamp}"

    # hard validate full submission against schema before writing
    from pydantic import TypeAdapter
    TypeAdapter(Submission).validate_python([m.model_dump(mode="json") for m in submission])

    out_path = os.path.join(out_cfg["dir"], f"{stem}.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump([m.model_dump(mode="json") for m in submission], f, indent=2, ensure_ascii=False)

    csv_path = os.path.join(out_cfg["dir"], f"{stem}_scores.csv")
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["source_ref", "source_name", "match_ref", "match_name", "match_retailer", "method", "score", "llm_kept"])
        writer.writeheader()
        writer.writerows(csv_rows)

    print(f"\nWrote {len(submission)} entries → {out_path}")
    print(f"Wrote scores → {csv_path}")


if __name__ == "__main__":
    main()
