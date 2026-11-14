"""Retrieval benchmark: BM25 vs semantic vs hybrid (RRF) vs hybrid + reranker.

Two query settings are measured:
  - raw:      the incident text written by the user is used as the query;
  - analyzer: the queries produced by the Incident Analyzer agent (needs GROQ_API_KEY; cached).

Usage:
  python -m evaluation.run_retrieval_benchmark                 # both settings, all strategies
  python -m evaluation.run_retrieval_benchmark --raw-only
  python -m evaluation.run_retrieval_benchmark --collection devops_kb_ft --model finetuning/output/minilm-devops \
         --strategies semantic hybrid --tag finetuned --raw-only
  python -m evaluation.run_retrieval_benchmark --dataset evaluation/datasets/benchmark_v1.json --tag bench_v1 --raw-only

Document-level metrics (recall, precision, mrr, hit) use expected_doc_ids. When the dataset gives
evidence passages (benchmark_v1.json), evidence-level metrics are added: see evaluation/metrics.py.
Another dataset than the historical one needs its own --tag, and its analyzer queries are cached
in analyzer_queries_<tag>.json: the historical results and caches are never touched.
"""
import argparse
import csv
import hashlib
import json
import time
from pathlib import Path

from evaluation.metrics import (MIN_FRAGMENT_CHARS, evidence_precision_at_k, evidence_recall_at_k,
                                evidence_reciprocal_rank, evidence_units, hit_rate_at_k, mean, precision_at_k,
                                recall_at_k, reciprocal_rank)
from incident_assistant import config, retrieval

DEFAULT_DATASET = Path(__file__).parent / "datasets" / "incidents_eval.json"
DATASET = DEFAULT_DATASET   # replaced by --dataset; load_incidents always reads this variable
RESULTS = Path(__file__).parent / "results"
ANALYZER_CACHE = RESULTS / "analyzer_queries.json"
KS = (1, 3, 5, 10)
STRATEGIES = ("bm25", "semantic", "hybrid", "hybrid_rerank")
HISTORICAL_TAGS = ("baseline", "finetuned")   # results of the historical dataset


def load_incidents(split: str = "test", answerable_only: bool = True) -> list[dict]:
    incidents = json.loads(DATASET.read_text(encoding="utf-8"))["incidents"]
    return [i for i in incidents if i["split"] == split and (i["answerable"] or not answerable_only)]


def is_default_dataset() -> bool:
    return Path(DATASET).resolve() == DEFAULT_DATASET.resolve()


def select_dataset(parser: argparse.ArgumentParser, path: str | None, tag: str, reserved_tags: tuple):
    """Use another dataset than the historical one (--dataset). Its results need a dedicated tag,
    so that they never replace or mix with the historical results and caches."""
    global DATASET
    if path is None:
        return
    candidate = Path(path)
    if not candidate.is_file():
        parser.error(f"dataset not found: {path}")
    DATASET = candidate
    if not is_default_dataset() and tag in reserved_tags:
        parser.error(f"--tag {tag or '(none)'} is reserved for the historical dataset: "
                     f"use a dedicated tag, e.g. --tag bench_v1")


def dataset_info() -> dict:
    """Provenance of the dataset: path, SHA-256 of the file, version."""
    data = DATASET.read_bytes()
    content = json.loads(data)
    try:
        path = Path(DATASET).resolve().relative_to(config.ROOT_DIR).as_posix()
    except ValueError:
        path = str(DATASET)
    return {"path": path, "name": Path(DATASET).name, "sha256": hashlib.sha256(data).hexdigest(),
            "version": content.get("version"), "created": content.get("created")}


def analyzer_queries(incidents: list[dict], cache_path: Path | None = None, answers_dir: Path | None = None) -> dict:
    """Queries produced by the Incident Analyzer agent (same rule as the workflow), cached on disk.
    By default: the historical cache and the historical generation answers."""
    from incident_assistant import agents   # imported here: only this setting needs the LLM
    cache_path = cache_path or ANALYZER_CACHE
    answers_dir = answers_dir or RESULTS / "generation"
    cache = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.exists() else {}
    for incident in incidents:
        if incident["id"] not in cache:
            # Reuse the analysis made by the generation benchmark when it exists (saves LLM tokens).
            answer_file = answers_dir / f"{incident['id']}_answer.json"
            if answer_file.exists():
                analysis = agents.IncidentAnalysis(**json.loads(answer_file.read_text(encoding="utf-8"))["answer"]["analysis"])
            else:
                analysis = agents.analyze_incident(incident["question"])
            queries = []
            for q in analysis.search_queries + analysis.error_messages:
                if q and q.lower() not in [x.lower() for x in queries]:
                    queries.append(q)
            cache[incident["id"]] = queries[:5]
            cache_path.parent.mkdir(exist_ok=True)
            cache_path.write_text(json.dumps(cache, indent=2), encoding="utf-8")
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
            for k in KS:
                row[f"hit@{k}"] = hit_rate_at_k(docs, relevant, k)
            units = evidence_units(incident)
            if units:   # evidence level: only for datasets that give evidence passages
                row["evidence_mrr"] = evidence_reciprocal_rank(passages, units)
                for k in KS:
                    row[f"evidence_recall@{k}"] = evidence_recall_at_k(passages, units, k)
                    row[f"evidence_precision@{k}"] = evidence_precision_at_k(passages, units, k)
            per_question.append(row)
        seconds = (time.perf_counter() - start) / len(incidents)
        keys = list(dict.fromkeys(key for r in per_question for key in r))
        metrics = {key: round(mean([r[key] for r in per_question if key in r]), 4)
                   for key in keys if key.startswith(("recall", "precision", "mrr", "hit", "evidence"))}
        summary.append({"tag": tag, "setting": setting, "strategy": strategy, "questions": len(incidents),
                        **metrics, "seconds_per_query": round(seconds, 3)})
        line = (f"{tag:10} {setting:8} {strategy:14} R@5={metrics['recall@5']:.3f} R@10={metrics['recall@10']:.3f} "
                f"MRR={metrics['mrr']:.3f} P@5={metrics['precision@5']:.3f}")
        if "evidence_recall@5" in metrics:
            line += f" EvR@5={metrics['evidence_recall@5']:.3f} EvMRR={metrics['evidence_mrr']:.3f}"
        print(f"{line}  ({seconds:.2f}s/query)")
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
    parser.add_argument("--dataset", help=f"evaluation dataset (default: {DEFAULT_DATASET.name}); "
                                          "another dataset needs its own --tag")
    args = parser.parse_args()
    select_dataset(parser, args.dataset, args.tag, HISTORICAL_TAGS)
    # A run with --raw-only or fewer strategies would replace a complete result file with a partial one.
    existing = [p.name for p in (RESULTS / f"retrieval_per_question_{args.tag}.csv",
                                 RESULTS / f"retrieval_summary_{args.tag}.json") if p.exists()]
    if existing and not args.overwrite:
        parser.error(f"{', '.join(existing)} already exist: use another --tag, or --overwrite to replace them")

    incidents = load_incidents("test")
    print(f"{len(incidents)} answerable test incidents")
    if args.raw_only:
        settings = {"raw": None}
    elif is_default_dataset():
        settings = {"raw": None, "analyzer": analyzer_queries(incidents)}
    else:   # never the historical cache nor the historical answers
        settings = {"raw": None, "analyzer": analyzer_queries(incidents, RESULTS / f"analyzer_queries_{args.tag}.json",
                                                              RESULTS / f"generation_{args.tag}")}

    all_rows, all_summary = [], []
    for setting, query_map in settings.items():
        rows, summary = evaluate(incidents, args.strategies, setting, query_map, args.collection, args.model, args.tag)
        all_rows += rows
        all_summary += summary

    RESULTS.mkdir(exist_ok=True)
    with open(RESULTS / f"retrieval_per_question_{args.tag}.csv", "w", newline="", encoding="utf-8") as f:
        fieldnames = list(dict.fromkeys(key for row in all_rows for key in row))
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(all_rows)
    with_evidence = any(evidence_units(i) for i in incidents)
    (RESULTS / f"retrieval_summary_{args.tag}.json").write_text(json.dumps({
        "date": time.strftime("%Y-%m-%d %H:%M"), "collection": args.collection, "embedding_model": args.model,
        "reranker": config.RERANKER_MODEL, "rrf_k": config.RRF_K,
        "tag": args.tag, "dataset": dataset_info(), "questions": len(incidents), "ks": list(KS),
        "settings": list(settings), "analyzer_model": config.ANALYZER_MODEL if "analyzer" in settings else None,
        "candidates_per_search": config.CANDIDATES_PER_SEARCH, "rerank_candidates": config.RERANK_CANDIDATES,
        "rerank_passages": config.RERANK_PASSAGES,
        "notes": ["Strategies are set by --strategies; RERANK_PASSAGES only changes the workflow, not this benchmark.",
                  "recall, precision, mrr and hit are document-level metrics (expected_doc_ids)."]
                 + (["evidence_* metrics: a passage matches an evidence unit (doc_id + physical PDF page, or doc_id + "
                     "Markdown section) when its normalized text contains the evidence passage, or a beginning or an "
                     f"end of it of at least {MIN_FRAGMENT_CHARS} characters. evidence_precision is a lower bound "
                     "(the evidence list is not exhaustive)."] if with_evidence else []),
        "results": all_summary}, indent=2), encoding="utf-8")
    print(f"Results written to {RESULTS}")


if __name__ == "__main__":
    main()
