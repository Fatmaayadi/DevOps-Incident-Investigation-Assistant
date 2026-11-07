"""Provenance check of the fine-tuning comparison, on temporary result files."""
import csv
import json

import pytest

from evaluation import compare_finetuning as compare

FIELDS = ["setting", "strategy", "id", "mrr", "recall@5"]


def write_results(folder, tag, collection, model, strategies=("semantic", "hybrid"), questions=("q1", "q2"), rrf_k=60):
    with open(folder / f"retrieval_per_question_{tag}.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows({"setting": "raw", "strategy": s, "id": q, "mrr": 1.0, "recall@5": 1.0}
                         for s in strategies for q in questions)
    (folder / f"retrieval_summary_{tag}.json").write_text(json.dumps({
        "collection": collection, "embedding_model": model, "rrf_k": rrf_k,
        "results": [{"setting": "raw", "strategy": s} for s in strategies]}), encoding="utf-8")


@pytest.fixture
def results(tmp_path, monkeypatch):
    monkeypatch.setattr(compare, "RESULTS", tmp_path)
    write_results(tmp_path, "baseline", "devops_kb", "base-model")
    return tmp_path


def test_comparison_of_two_distinct_configurations_is_written(results):
    write_results(results, "finetuned", "devops_kb_ft", "tuned-model")
    compare.main()
    report = json.loads((results / "finetuning_comparison.json").read_text(encoding="utf-8"))
    assert set(report) == {"semantic", "hybrid"} and report["hybrid"]["questions"] == 2


@pytest.mark.parametrize(("arguments", "message"), [
    ({"collection": "devops_kb", "model": "tuned-model"}, "same collection"),
    ({"collection": "devops_kb_ft", "model": "base-model"}, "same embedding_model"),
    ({"collection": "devops_kb_ft", "model": "tuned-model", "rrf_k": 30}, "different rrf_k"),
    ({"collection": "devops_kb_ft", "model": "tuned-model", "strategies": ("semantic",)}, "strategy hybrid"),
    ({"collection": "devops_kb_ft", "model": "tuned-model", "questions": ("q1",)}, "same questions"),
])
def test_incompatible_results_stop_before_any_conclusion(results, arguments, message):
    write_results(results, "finetuned", **arguments)
    with pytest.raises(ValueError, match=message):
        compare.main()
    assert not (results / "finetuning_comparison.json").exists()


def test_results_without_questions_are_refused(results):
    write_results(results, "finetuned", "devops_kb_ft", "tuned-model", questions=())
    with pytest.raises(ValueError, match="same questions"):
        compare.main()


def test_strategy_listed_only_for_the_agent_queries_in_the_summary_is_refused(results):
    write_results(results, "finetuned", "devops_kb_ft", "tuned-model")
    path = results / "retrieval_summary_finetuned.json"
    summary = json.loads(path.read_text(encoding="utf-8"))
    next(r for r in summary["results"] if r["strategy"] == "hybrid")["setting"] = "analyzer"
    path.write_text(json.dumps(summary), encoding="utf-8")
    with pytest.raises(ValueError, match="no raw results for strategy hybrid"):
        compare.main()
    assert not (results / "finetuning_comparison.json").exists()


def test_strategy_measured_only_on_the_agent_queries_in_the_csv_is_refused(results):
    write_results(results, "finetuned", "devops_kb_ft", "tuned-model")
    path = results / "retrieval_per_question_finetuned.csv"
    path.write_text(path.read_text(encoding="utf-8").replace("raw,hybrid", "analyzer,hybrid"), encoding="utf-8")
    with pytest.raises(ValueError, match="same questions for hybrid"):
        compare.main()
    assert not (results / "finetuning_comparison.json").exists()


def test_strategy_without_questions_on_both_sides_is_refused(results):
    write_results(results, "finetuned", "devops_kb_ft", "tuned-model")
    for tag in ("baseline", "finetuned"):
        path = results / f"retrieval_per_question_{tag}.csv"
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        path.write_text("".join(line for line in lines if ",hybrid," not in line), encoding="utf-8")
    with pytest.raises(ValueError, match="same questions for hybrid"):
        compare.main()
    assert not (results / "finetuning_comparison.json").exists()
