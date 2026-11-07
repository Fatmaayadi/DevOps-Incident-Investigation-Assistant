"""Human review support.

  python -m evaluation.review_agreement --prepare   # create the two CSV files to fill in (Excel, ';' separator)
  python -m evaluation.review_agreement             # compute agreement once the team columns are filled

Files (evaluation/review/), blind review: the verdicts of the AI assistant and of the LLM judge are NOT
in the CSV files (they would influence the reviewers); they are read from the result files when computing agreement.
  - pairs_review.csv  : the 50 fine-tuning pairs; team_verdict = correct / incorrect
  - judge_review.csv  : 15 answers; team_score = share of expected causes covered (0, 0.33, 0.5, 0.67 or 1)
"""
import argparse
import csv
import json

from evaluation.run_retrieval_benchmark import DATASET, RESULTS
from incident_assistant import config

REVIEW_DIR = config.ROOT_DIR / "evaluation" / "review"
PAIRS_SAMPLE = config.ROOT_DIR / "finetuning" / "data" / "review_sample.json"
# Correctness scores given by the AI assistant during its own audit (docs/rapport_technique.docx, section 13.6).
ASSISTANT_SCORES = {"k8s-007": 1, "git-001": 1, "linux-001": 1, "aws-004": 1, "docker-001": 0.5, "docker-004": 0.67,
                    "k8s-010": 1, "k8s-004": 1, "aws-001": 0.5, "k8s-001": 1, "net-007": 1, "net-003": 0.67,
                    "aws-002": 0, "github-002": 1, "k8s-011": 1}


def write_csv(path, rows):
    with open(path, "w", newline="", encoding="utf-8-sig") as f:   # utf-8-sig: accents shown correctly in Excel
        writer = csv.DictWriter(f, fieldnames=list(rows[0]), delimiter=";")
        writer.writeheader()
        writer.writerows(rows)


def read_csv(path):
    with open(path, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f, delimiter=";"))


def prepare():
    REVIEW_DIR.mkdir(exist_ok=True)
    pairs = json.loads(PAIRS_SAMPLE.read_text(encoding="utf-8"))["pairs"]
    write_csv(REVIEW_DIR / "pairs_review.csv", [{
        "number": n, "question": p["question"], "passage": " ".join(p["passage"].split()), "chunk_id": p["chunk_id"],
        "team_verdict": "", "team_comment": "",
    } for n, p in enumerate(pairs, start=1)])

    incidents = {i["id"]: i for i in json.loads(DATASET.read_text(encoding="utf-8"))["incidents"]}
    rows = []
    for qid in ASSISTANT_SCORES:
        answer = json.loads((RESULTS / "generation" / f"{qid}_answer.json").read_text(encoding="utf-8"))["answer"]
        rows.append({
            "id": qid, "question": incidents[qid]["question"],
            "expected_causes": " | ".join(incidents[qid]["expected_causes"]),
            "answer_causes": " | ".join(f"{c['cause']} ({c['status']})" for c in answer["possible_causes"]) or "(no cause)",
            "team_score": "", "team_comment": "",
        })
    write_csv(REVIEW_DIR / "judge_review.csv", rows)
    print(f"Files created in {REVIEW_DIR}")


def agreement():
    assistant_pairs = json.loads(PAIRS_SAMPLE.read_text(encoding="utf-8"))["pairs"]
    pairs = [{**r, "assistant_verdict": assistant_pairs[int(r["number"]) - 1]["verdict"]}
             for r in read_csv(REVIEW_DIR / "pairs_review.csv") if r["team_verdict"].strip()]
    judged = []
    for r in read_csv(REVIEW_DIR / "judge_review.csv"):
        if r["team_score"].strip():
            judgement = json.loads((RESULTS / "generation" / f"{r['id']}_judgement.json").read_text(encoding="utf-8"))
            judged.append({**r, "judge_score": str(judgement["correctness"]), "assistant_score": str(ASSISTANT_SCORES[r["id"]])})
    report = {"pairs_reviewed_by_team": len(pairs), "judgements_reviewed_by_team": len(judged)}
    if pairs:
        report["pairs_correct_rate_team"] = round(sum(r["team_verdict"].strip().lower() == "correct" for r in pairs) / len(pairs), 3)
        report["pairs_agreement_team_vs_assistant"] = round(
            sum(r["team_verdict"].strip().lower() == r["assistant_verdict"] for r in pairs) / len(pairs), 3)
    if judged:
        def score(r, key):
            return float(r[key].replace(",", "."))
        report["judge_mean_abs_difference_vs_team"] = round(
            sum(abs(score(r, "judge_score") - score(r, "team_score")) for r in judged) / len(judged), 3)
        report["judge_exact_agreement_with_team"] = round(
            sum(abs(score(r, "judge_score") - score(r, "team_score")) < 0.05 for r in judged) / len(judged), 3)
        report["assistant_exact_agreement_with_team"] = round(
            sum(abs(score(r, "assistant_score") - score(r, "team_score")) < 0.05 for r in judged) / len(judged), 3)
    (RESULTS / "human_review.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--prepare", action="store_true", help="create the CSV files to fill in")
    if parser.parse_args().prepare:
        prepare()
    else:
        agreement()


if __name__ == "__main__":
    main()
