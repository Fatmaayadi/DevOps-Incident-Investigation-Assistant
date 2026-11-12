"""Choose the reranker score threshold used by the evidence check (EVIDENCE_MIN_SCORE).

Only the calibration questions are used. For each one, the hybrid search + reranker returns
passages; a passage is labelled relevant when it comes from an expected document. We pick the
threshold that best separates relevant from non-relevant passages (balanced accuracy).

Usage: python -m evaluation.calibrate_evidence
"""
import json

from evaluation.run_retrieval_benchmark import RESULTS, load_incidents
from incident_assistant import config, retrieval


def main():
    incidents = load_incidents("calibration")
    scored = []   # (rerank score, is relevant)
    for incident in incidents:
        passages = retrieval.hybrid_search([incident["question"]], use_reranker=True, top_k=config.FINAL_PASSAGES)
        for p in passages:
            scored.append((p["rerank_score"], p["doc_id"] in incident["expected_doc_ids"]))

    positives = [s for s, rel in scored if rel]
    negatives = [s for s, rel in scored if not rel]
    best = None
    for threshold in sorted({round(s, 2) for s, _ in scored}):
        tpr = sum(s >= threshold for s in positives) / len(positives)
        tnr = sum(s < threshold for s in negatives) / len(negatives)
        balanced = (tpr + tnr) / 2
        if best is None or balanced > best["balanced_accuracy"]:
            best = {"threshold": threshold, "balanced_accuracy": round(balanced, 3),
                    "true_positive_rate": round(tpr, 3), "true_negative_rate": round(tnr, 3)}

    report = {"calibration_questions": len(incidents), "passages": len(scored),
              "relevant_passages": len(positives), "reranker": config.RERANKER_MODEL, "best": best,
              "relevant_score_range": [round(min(positives), 2), round(max(positives), 2)],
              "non_relevant_score_range": [round(min(negatives), 2), round(max(negatives), 2)]}
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "evidence_calibration.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    print(f"\nSet EVIDENCE_MIN_SCORE={best['threshold']} in .env (or config.py) to use this threshold.")


if __name__ == "__main__":
    main()
