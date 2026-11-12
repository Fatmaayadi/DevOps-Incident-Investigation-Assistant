"""Tune the evidence check on a VALIDATION set that is separate from the test set.

Validation set:
  - positives: the 10 calibration incidents + 40 questions generated from the Markdown guides
    (fine-tuning pairs; each one is answerable by construction);
  - negatives: 20 hand-written out-of-scope incidents (datasets/evidence_validation_negatives.json).

For each question, the first retrieval round of the workflow is reproduced without LLM
(hybrid RRF search on the question text), and two candidate scores are computed on the
6 passages: the reranker score and the cosine similarity of the dense embeddings.
Rule tested: "evidence is sufficient when at least N passages score >= s".
The rule with the best balanced accuracy on the validation set is selected.

Usage: python -m evaluation.tune_evidence
"""
import json
import random

import numpy as np

from evaluation.run_retrieval_benchmark import DATASET, RESULTS, load_incidents
from incident_assistant import config, retrieval
from incident_assistant.indexing import get_dense_embeddings

NEGATIVES = DATASET.parent / "evidence_validation_negatives.json"
PAIRS = config.ROOT_DIR / "finetuning" / "data"


def validation_questions() -> list[tuple[str, bool]]:
    questions = [(i["question"], True) for i in load_incidents("calibration")]
    pairs = [json.loads(line) for name in ("train.jsonl", "validation.jsonl")
             for line in (PAIRS / name).read_text(encoding="utf-8").splitlines() if line.strip()]
    markdown_pairs = [p for p in pairs if p["doc_id"].startswith("md-")]
    questions += [(p["question"], True) for p in random.Random(42).sample(markdown_pairs, 40)]
    questions += [(q, False) for q in json.loads(NEGATIVES.read_text(encoding="utf-8"))["incidents"]]
    return questions


def passage_scores(question: str) -> dict:
    """Scores of the 6 passages returned by hybrid RRF search (the workflow's first round)."""
    passages = retrieval.hybrid_search([question], use_reranker=False)
    rerank = retrieval.get_reranker().predict([(question, p["text"]) for p in passages])
    embeddings = get_dense_embeddings()
    q = np.array(embeddings.embed_query(question))
    docs = np.array(embeddings.embed_documents([p["text"] for p in passages]))
    cosine = docs @ q / (np.linalg.norm(docs, axis=1) * np.linalg.norm(q))
    return {"reranker": sorted(map(float, rerank), reverse=True), "cosine": sorted(map(float, cosine), reverse=True)}


def best_rule(rows: list[dict], score: str) -> dict:
    best = None
    values = sorted({round(v, 2) for r in rows for v in r[score]})
    for n in (1, 2, 3):
        for s in values:
            accepted = [sum(v >= s for v in r[score]) >= n for r in rows]
            tpr = np.mean([a for a, r in zip(accepted, rows) if r["answerable"]])
            tnr = np.mean([not a for a, r in zip(accepted, rows) if not r["answerable"]])
            candidate = {"score": score, "min_passages": n, "threshold": s, "balanced_accuracy": round((tpr + tnr) / 2, 3),
                         "accept_rate_answerable": round(float(tpr), 3), "reject_rate_out_of_scope": round(float(tnr), 3)}
            if best is None or candidate["balanced_accuracy"] > best["balanced_accuracy"]:
                best = candidate
    return best


def evaluate_rule(rows: list[dict], rule: dict) -> dict:
    accepted = [sum(v >= rule["threshold"] for v in r[rule["score"]]) >= rule["min_passages"] for r in rows]
    answerable = [a for a, r in zip(accepted, rows) if r["answerable"]]
    out_of_scope = [a for a, r in zip(accepted, rows) if not r["answerable"]]
    return {"accept_rate_answerable": round(float(np.mean(answerable)), 3),
            "reject_rate_out_of_scope": round(float(1 - np.mean(out_of_scope)), 3) if out_of_scope else None}


def main():
    rows = [{"question": q, "answerable": answerable, **passage_scores(q)} for q, answerable in validation_questions()]
    v1_rule = {"score": "reranker", "min_passages": 2, "threshold": -0.22}   # earlier rule, kept for comparison
    report = {
        "validation_questions": len(rows),
        "answerable": sum(r["answerable"] for r in rows),
        "out_of_scope": sum(not r["answerable"] for r in rows),
        "v1_rule": {**v1_rule, **evaluate_rule(rows, v1_rule)},
        "best_reranker_rule": best_rule(rows, "reranker"),
        "best_cosine_rule": best_rule(rows, "cosine"),
    }
    # Offline check on the TEST set (no tuning here): first retrieval round with the raw question.
    test = [{"answerable": i["answerable"], **passage_scores(i["question"])} for i in load_incidents("test", answerable_only=False)]
    report["test_set_offline_check"] = {name: evaluate_rule(test, rule) for name, rule in
                                        (("v1_rule", v1_rule), ("best_reranker_rule", report["best_reranker_rule"]),
                                         ("best_cosine_rule", report["best_cosine_rule"]))}
    (RESULTS / "evidence_tuning.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
