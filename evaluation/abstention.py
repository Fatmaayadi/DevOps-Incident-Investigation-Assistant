"""Abstention on out-of-scope incidents, computed from the cached workflow answers only (no LLM).
An answer abstains correctly when it reports insufficient evidence or contains no documented cause.

Usage: python -m evaluation.abstention
"""
import argparse
import json

from evaluation.run_retrieval_benchmark import RESULTS, load_incidents


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", default="", help="same tag as run_generation_benchmark (default: earlier configuration; v2: final system)")
    tag = parser.parse_args().tag
    suffix = f"_{tag}" if tag else ""
    rows = []
    for incident in load_incidents("test", answerable_only=False):
        path = RESULTS / f"generation{suffix}" / f"{incident['id']}_answer.json"
        if not path.exists():
            continue
        answer = json.loads(path.read_text(encoding="utf-8"))["answer"]
        documented = [c for c in answer.get("possible_causes", []) if c["status"] == "documented"]
        rows.append({"id": incident["id"], "answerable": incident["answerable"], "status": answer["status"],
                     "documented_causes": len(documented), "rewrites": answer.get("rewrites"),
                     "abstains": answer["status"] != "ok" or not documented})
    out_of_scope = [r for r in rows if not r["answerable"]]
    answerable = [r for r in rows if r["answerable"]]
    report = {
        "out_of_scope_questions": len(out_of_scope),
        "out_of_scope_correct_abstention_rate": round(sum(r["abstains"] for r in out_of_scope) / len(out_of_scope), 3),
        "answerable_questions": len(answerable),
        "answerable_false_abstention_rate": round(sum(r["abstains"] for r in answerable) / len(answerable), 3),
        "answerable_status_insufficient": [r["id"] for r in answerable if r["status"] == "insufficient_evidence"],
        "answerable_status_clarification": [r["id"] for r in answerable if r["status"] == "needs_clarification"],
        "out_of_scope_details": out_of_scope,
    }
    (RESULTS / f"abstention{suffix}.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
