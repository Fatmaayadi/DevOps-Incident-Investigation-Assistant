"""Retrieval benchmark: BM25 vs semantic vs hybrid (RRF) vs hybrid + reranker.

Two query settings are measured:
  - raw:      the incident text written by the user is used as the query;
  - analyzer: the queries produced by the Incident Analyzer agent (needs GROQ_API_KEY; cached).

Usage:
  python -m evaluation.run_retrieval_benchmark                 # both settings, all strategies
  python -m evaluation.run_retrieval_benchmark --raw-only
  python -m evaluation.run_retrieval_benchmark --collection devops_kb_ft --model finetuning/output/minilm-devops \
         --strategies semantic hybrid --tag finetuned --raw-only
"""
import argparse
import csv
import json
import time
from pathlib import Path

from evaluation.metrics import mean, precision_at_k, recall_at_k, reciprocal_rank
from incident_assistant import config, retrieval

DATASET = Path(__file__).parent / "datasets" / "incidents_eval.json"
RESULTS = Path(__file__).parent / "results"
ANALYZER_CACHE = RESULTS / "analyzer_queries.json"
KS = (1, 3, 5, 10)
STRATEGIES = ("bm25", "semantic", "hybrid", "hybrid_rerank")


def load_incidents(split: str = "test", answerable_only: bool = True) -> list[dict]:
    incidents = json.loads(DATASET.read_text(encoding="utf-8"))["incidents"]
    return [i for i in incidents if i["split"] == split and (i["answerable"] or not answerable_only)]


def analyzer_queries(incidents: list[dict]) -> dict:
    """Queries produced by the Incident Analyzer agent (same rule as the workflow), cached on disk."""
    from incident_assistant import agents   # imported here: only this setting needs the LLM
    cache = json.loads(ANALYZER_CACHE.read_text(encoding="utf-8")) if ANALYZER_CACHE.exists() else {}
    for incident in incidents:
        if incident["id"] not in cache:
            # Reuse the analysis made by the generation benchmark when it exists (saves LLM tokens).
            answer_file = RESULTS / "generation" / f"{incident['id']}_answer.json"
            if answer_file.exists():
                analysis = agents.IncidentAnalysis(**json.loads(answer_file.read_text(encoding="utf-8"))["answer"]["analysis"])
            else:
                analysis = agents.analyze_incident(incident["question"])
            queries = []
            for q in analysis.search_queries + analysis.error_messages:
                if q and q.lower() not in [x.lower() for x in queries]:
                    queries.append(q)
            cache[incident["id"]] = queries[:5]
            RESULTS.mkdir(exist_ok=True)
            ANALYZER_CACHE.write_text(json.dumps(cache, indent=2), encoding="utf-8")
    return cache


def retrieve(incident: dict, strategy: str, queries: list[str] | None, collection: str, model: str) -> list[dict]:
    if queries is None:   # raw question
        return retrieval.search_with_strategy(incident["question"], strategy, top_k=max(KS),
                                              collection=collection, model_name=model)
    if strategy in retrieval.MODES:   # one method, several queries: fuse them with RRF
        lists = [retrieval.search(q, strategy, k=max(KS), collection=collection, model_name=model) for q in queries]
        return retrieval.reciprocal_rank_fusion(lists)[:max(KS)]
    return retrieval.hybrid_search(queries, use_reranker=(strategy == "hybrid_rerank"),
                                   rerank_query=incident["question"], top_k=max(KS),
                                   collection=collection, model_name=model)


def evaluate(incidents, strategies, setting, query_map, collection, model, tag) -> tuple[list[dict], list[dict]]:
    rows, summary = [], []
    for strategy in strategies:
        start = time.perf_counter()
        per_question = []
        for incident in incidents:
            queries = None if setting == "raw" else query_map[incident["id"]]
            passages = retrieve(incident, strategy, queries, collection, model)
            docs = [p["doc_id"] for p in passages]
            relevant = set(incident["expected_doc_ids"])
            row = {"tag": tag, "setting": setting, "strategy": strategy, "id": incident["id"],
                   "domain": incident["domain"], "mrr": reciprocal_rank(docs, relevant),
                   "top_docs": " ".join(docs[:5])}
            for k in KS:
                row[f"recall@{k}"] = recall_at_k(docs, relevant, k)
                row[f"precision@{k}"] = precision_at_k(docs, relevant, k)
            per_question.append(row)
        seconds = (time.perf_counter() - start) / len(incidents)
        metrics = {key: round(mean([r[key] for r in per_question]), 4)
                   for key in per_question[0] if key.startswith(("recall", "precision", "mrr"))}
        summary.append({"tag": tag, "setting": setting, "strategy": strategy, "questions": len(incidents),
                        **metrics, "seconds_per_query": round(seconds, 3)})
        print(f"{tag:10} {setting:8} {strategy:14} R@5={metrics['recall@5']:.3f} R@10={metrics['recall@10']:.3f} "
              f"MRR={metrics['mrr']:.3f} P@5={metrics['precision@5']:.3f}  ({seconds:.2f}s/query)")
        rows += per_question
    return rows, summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-only", action="store_true")
    parser.add_argument("--strategies", nargs="+", default=list(STRATEGIES), choices=STRATEGIES)
    parser.add_argument("--collection", default=config.COLLECTION_NAME)
    parser.add_argument("--model", default=config.EMBEDDING_MODEL)
    parser.add_argument("--tag", default="baseline")
    parser.add_argument("--overwrite", action="store_true", help="replace the existing results of this tag")
    args = parser.parse_args()
    # A run with --raw-only or fewer strategies would replace a complete result file with a partial one.
    existing = [p.name for p in (RESULTS / f"retrieval_per_question_{args.tag}.csv",
                                 RESULTS / f"retrieval_summary_{args.tag}.json") if p.exists()]
    if existing and not args.overwrite:
        parser.error(f"{', '.join(existing)} already exist: use another --tag, or --overwrite to replace them")

    incidents = load_incidents("test")
    print(f"{len(incidents)} answerable test incidents")
    settings = {"raw": None} if args.raw_only else {"raw": None, "analyzer": analyzer_queries(incidents)}

    all_rows, all_summary = [], []
    for setting, query_map in settings.items():
        rows, summary = evaluate(incidents, args.strategies, setting, query_map, args.collection, args.model, args.tag)
        all_rows += rows
        all_summary += summary

    RESULTS.mkdir(exist_ok=True)
    with open(RESULTS / f"retrieval_per_question_{args.tag}.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(all_rows[0]))
        writer.writeheader()
        writer.writerows(all_rows)
    (RESULTS / f"retrieval_summary_{args.tag}.json").write_text(json.dumps({
        "date": time.strftime("%Y-%m-%d %H:%M"), "collection": args.collection, "embedding_model": args.model,
        "reranker": config.RERANKER_MODEL, "rrf_k": config.RRF_K, "results": all_summary}, indent=2), encoding="utf-8")
    print(f"Results written to {RESULTS}")


if __name__ == "__main__":
    main()
