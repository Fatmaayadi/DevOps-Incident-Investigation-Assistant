"""Paired comparison base vs fine-tuned embeddings, question by question (raw queries).

For each strategy: number of questions improved / degraded / unchanged in reciprocal rank,
and a 95% bootstrap confidence interval of the MRR difference (fine-tuned - base).

Usage: python -m evaluation.compare_finetuning
       python -m evaluation.compare_finetuning --base-tag bench_v1 --tuned-tag bench_v1_ft \
              --output finetuning_comparison_bench_v1.json --dataset evaluation/datasets/benchmark_v1.json

With --dataset (a benchmark with independence_check), the questions are split into two groups
reported separately: no overlap of evidence passages with the fine-tuning pairs (main comparison)
and overlap (secondary analysis).
"""
import argparse
import csv
import hashlib
import json
import random
import sys
from pathlib import Path

from evaluation.run_retrieval_benchmark import RESULTS

STRATEGIES = ("semantic", "hybrid")
DEFAULT_OUTPUT = "finetuning_comparison.json"


def load(tag: str) -> dict:
    with open(RESULTS / f"retrieval_per_question_{tag}.csv", encoding="utf-8") as f:
        return {(r["setting"], r["strategy"], r["id"]): r for r in csv.DictReader(f)}


def load_summary(tag: str) -> dict:
    return json.loads((RESULTS / f"retrieval_summary_{tag}.json").read_text(encoding="utf-8"))


def check_provenance(base_summary: dict, tuned_summary: dict, base: dict, tuned: dict):
    """Refuse a comparison that would not measure the fine-tuning: both runs must use their own
    collection and embedding model, the same RRF setting, and the same questions per strategy."""
    for field in ("collection", "embedding_model"):
        if base_summary[field] == tuned_summary[field]:
            raise ValueError(f"baseline and finetuned results use the same {field}: {base_summary[field]}")
    if base_summary["rrf_k"] != tuned_summary["rrf_k"]:
        raise ValueError(f"different rrf_k: {base_summary['rrf_k']} and {tuned_summary['rrf_k']}")
    for strategy in STRATEGIES:
        for name, summary in (("baseline", base_summary), ("finetuned", tuned_summary)):
            if not any(r["setting"] == "raw" and r["strategy"] == strategy for r in summary["results"]):
                raise ValueError(f"{name} summary has no raw results for strategy {strategy}")
        questions = [{k[2] for k in rows if k[:2] == ("raw", strategy)} for rows in (base, tuned)]
        if not questions[0] or questions[0] != questions[1]:
            raise ValueError(f"baseline and finetuned results do not cover the same questions for {strategy}")


def bootstrap_ci(differences: list[float], rounds: int = 10000, seed: int = 42) -> tuple[float, float]:
    rng = random.Random(seed)
    means = sorted(sum(rng.choice(differences) for _ in differences) / len(differences) for _ in range(rounds))
    return means[int(0.025 * rounds)], means[int(0.975 * rounds)]


def compare(base: dict, tuned: dict, questions: set[str] | None = None) -> dict:
    """Paired statistics per strategy, on all the questions or only on the given ones."""
    report = {}
    for strategy in STRATEGIES:
        keys = [k for k in tuned if k[0] == "raw" and k[1] == strategy and (questions is None or k[2] in questions)]
        if not keys:
            raise ValueError(f"no question to compare for {strategy}")
        diffs = [float(tuned[k]["mrr"]) - float(base[k]["mrr"]) for k in keys]
        recall_diffs = [float(tuned[k]["recall@5"]) - float(base[k]["recall@5"]) for k in keys]
        low, high = bootstrap_ci(diffs)
        report[strategy] = {
            "questions": len(keys),
            "mrr_base": round(sum(float(base[k]["mrr"]) for k in keys) / len(keys), 4),
            "mrr_finetuned": round(sum(float(tuned[k]["mrr"]) for k in keys) / len(keys), 4),
            "mrr_difference": round(sum(diffs) / len(diffs), 4),
            "mrr_difference_95ci": [round(low, 4), round(high, 4)],
            "improved": sum(d > 0 for d in diffs), "degraded": sum(d < 0 for d in diffs),
            "unchanged": sum(d == 0 for d in diffs),
            "recall@5_difference": round(sum(recall_diffs) / len(recall_diffs), 4),
            "degraded_questions": [k[2] for k, d in zip(keys, diffs) if d < 0],
            "improved_questions": [k[2] for k, d in zip(keys, diffs) if d > 0],
        }
    return report


def overlap_groups(dataset: dict) -> dict[str, set[str]]:
    """Answerable questions split by the overlap of their evidence passages with the fine-tuning
    pairs (field independence_check.evidence_passages_found_in_finetuning_pairs of the benchmark)."""
    groups = {"primary_no_passage_overlap": set(), "secondary_passage_overlap": set()}
    for incident in dataset["incidents"]:
        if not incident["answerable"]:
            continue
        check = incident.get("independence_check")
        if check is None:
            raise ValueError(f"{incident['id']} has no independence_check: the overlap groups cannot be built")
        overlap = check["evidence_passages_found_in_finetuning_pairs"]
        groups["secondary_passage_overlap" if overlap else "primary_no_passage_overlap"].add(incident["id"])
    return groups


def main(argv: list[str] | tuple = ()):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base-tag", default="baseline", help="tag of the base model results")
    parser.add_argument("--tuned-tag", default="finetuned", help="tag of the fine-tuned model results")
    parser.add_argument("--output", default=DEFAULT_OUTPUT, help="file written in evaluation/results/")
    parser.add_argument("--dataset", help="benchmark with independence_check: report the two overlap groups separately")
    parser.add_argument("--overwrite", action="store_true", help="replace an existing output file")
    args = parser.parse_args(list(argv))
    output = RESULTS / args.output
    historical = (args.base_tag, args.tuned_tag, args.output, args.dataset) == ("baseline", "finetuned", DEFAULT_OUTPUT, None)
    if not historical and output.exists() and not args.overwrite:   # the historical call keeps its behaviour
        parser.error(f"{args.output} already exists: use another --output, or --overwrite to replace it")

    base, tuned = load(args.base_tag), load(args.tuned_tag)
    base_summary, tuned_summary = load_summary(args.base_tag), load_summary(args.tuned_tag)
    check_provenance(base_summary, tuned_summary, base, tuned)
    if args.dataset is None:
        report = compare(base, tuned)
    else:
        data = Path(args.dataset).read_bytes()
        sha256 = hashlib.sha256(data).hexdigest()
        for name, summary in ((args.base_tag, base_summary), (args.tuned_tag, tuned_summary)):
            if summary.get("dataset", {}).get("sha256") != sha256:
                raise ValueError(f"results {name} were not produced on {args.dataset} (different or missing SHA-256)")
        groups = overlap_groups(json.loads(data))
        report = {
            "dataset": {"path": args.dataset, "sha256": sha256},
            "base_tag": args.base_tag, "tuned_tag": args.tuned_tag,
            "groups": {name: {"question_ids": sorted(ids), "results": compare(base, tuned, ids)}
                       for name, ids in groups.items()},
            "notes": [
                "primary_no_passage_overlap: no evidence passage of the question appears in the fine-tuning pairs. "
                "This is the main comparison. It does not mean that the documents were never seen in training.",
                "secondary_passage_overlap: at least one evidence passage appears in train.jsonl or validation.jsonl; "
                "the fine-tuned model may be favoured. Reported separately, never merged with the primary group.",
            ],
        }
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main(sys.argv[1:])
