"""Abstention on out-of-scope incidents, computed from the cached workflow answers only (no LLM).
An answer abstains correctly when it reports insufficient evidence or contains no documented cause.

Each answer is also given one category (deterministic, from the cached answer):
  - answered                                    answerable question, status ok with documented causes
                                                (whether the answer is correct is judged by run_generation_benchmark)
  - false_abstention                            answerable question, no answer (insufficient evidence or no documented cause)
  - justified_abstention                        out-of-scope question, insufficient evidence or no documented cause
  - answered_out_of_scope                       out-of-scope question answered with status ok and documented causes
  - insufficient_evidence_with_documented_causes  status insufficient_evidence, yet causes presented as documented
  - clarification                               the assistant asked for clarification

Usage: python -m evaluation.abstention [--tag v2]
       python -m evaluation.abstention --dataset evaluation/datasets/benchmark_v1.json --tag bench_v1
"""
import argparse
import json
from collections import Counter

from evaluation.run_retrieval_benchmark import DEFAULT_DATASET, RESULTS, dataset_info, load_incidents, select_dataset


def category(answerable: bool, status: str, documented_causes: int) -> str:
    if status == "needs_clarification":
        return "clarification"
    if status == "insufficient_evidence" and documented_causes:
        return "insufficient_evidence_with_documented_causes"
    abstains = status != "ok" or not documented_causes
    if answerable:
        return "false_abstention" if abstains else "answered"
    return "justified_abstention" if abstains else "answered_out_of_scope"


def rate(rows: list[dict]) -> float | None:
    return round(sum(r["abstains"] for r in rows) / len(rows), 3) if rows else None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", default="", help="same tag as run_generation_benchmark (default: earlier configuration; v2: final system)")
    parser.add_argument("--dataset", help=f"evaluation dataset (default: {DEFAULT_DATASET.name}); "
                                          "another dataset needs its own --tag")
    args = parser.parse_args()
    select_dataset(parser, args.dataset, args.tag, ("", "v2"))
    tag = args.tag
    suffix = f"_{tag}" if tag else ""
    rows = []
    categories = {}
    for incident in load_incidents("test", answerable_only=False):
        path = RESULTS / f"generation{suffix}" / f"{incident['id']}_answer.json"
        if not path.exists():
            continue
        answer = json.loads(path.read_text(encoding="utf-8"))["answer"]
        documented = [c for c in answer.get("possible_causes", []) if c["status"] == "documented"]
        rows.append({"id": incident["id"], "answerable": incident["answerable"], "status": answer["status"],
                     "documented_causes": len(documented), "rewrites": answer.get("rewrites"),
                     "abstains": answer["status"] != "ok" or not documented})
        categories[incident["id"]] = category(incident["answerable"], answer["status"], len(documented))
    out_of_scope = [r for r in rows if not r["answerable"]]
    answerable = [r for r in rows if r["answerable"]]
    report = {
        "out_of_scope_questions": len(out_of_scope),
        "out_of_scope_correct_abstention_rate": rate(out_of_scope),
        "answerable_questions": len(answerable),
        "answerable_false_abstention_rate": rate(answerable),
        "answerable_status_insufficient": [r["id"] for r in answerable if r["status"] == "insufficient_evidence"],
        "answerable_status_clarification": [r["id"] for r in answerable if r["status"] == "needs_clarification"],
        "out_of_scope_details": out_of_scope,
        "categories": categories,
        "category_counts": dict(Counter(categories.values())),
        "dataset": dataset_info(),
    }
    (RESULTS / f"abstention{suffix}.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
