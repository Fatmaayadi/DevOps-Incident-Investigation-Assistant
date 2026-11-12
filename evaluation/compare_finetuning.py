"""Paired comparison base vs fine-tuned embeddings, question by question (raw queries).

For each strategy: number of questions improved / degraded / unchanged in reciprocal rank,
and a 95% bootstrap confidence interval of the MRR difference (fine-tuned - base).

Usage: python -m evaluation.compare_finetuning
"""
import csv
import json
import random

from evaluation.run_retrieval_benchmark import RESULTS

STRATEGIES = ("semantic", "hybrid")


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


def main():
    base, tuned = load("baseline"), load("finetuned")
    check_provenance(load_summary("baseline"), load_summary("finetuned"), base, tuned)
    report = {}
    for strategy in STRATEGIES:
        keys = [k for k in tuned if k[0] == "raw" and k[1] == strategy]
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
    (RESULTS / "finetuning_comparison.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
