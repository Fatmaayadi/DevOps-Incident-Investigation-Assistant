"""Provenance check of the fine-tuning comparison, on temporary result files."""
import csv
import hashlib
import json

import pytest

from evaluation import compare_finetuning as compare

FIELDS = ["setting", "strategy", "id", "mrr", "recall@5"]


def write_results(folder, tag, collection, model, strategies=("semantic", "hybrid"), questions=("q1", "q2"), rrf_k=60,
                  dataset_sha256=None, mrr=1.0):
    with open(folder / f"retrieval_per_question_{tag}.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows({"setting": "raw", "strategy": s, "id": q, "mrr": mrr, "recall@5": 1.0}
                         for s in strategies for q in questions)
    summary = {"collection": collection, "embedding_model": model, "rrf_k": rrf_k,
               "results": [{"setting": "raw", "strategy": s} for s in strategies]}
    if dataset_sha256:
        summary["dataset"] = {"sha256": dataset_sha256}
    (folder / f"retrieval_summary_{tag}.json").write_text(json.dumps(summary), encoding="utf-8")


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


def test_tags_and_output_are_configurable_and_the_historical_file_is_not_written(results):
    write_results(results, "bench_a", "devops_kb", "base-model")
    write_results(results, "bench_b", "devops_kb_ft", "tuned-model")
    compare.main(["--base-tag", "bench_a", "--tuned-tag", "bench_b", "--output", "cmp.json"])
    assert json.loads((results / "cmp.json").read_text(encoding="utf-8"))["hybrid"]["questions"] == 2
    assert not (results / "finetuning_comparison.json").exists()


def test_existing_output_is_replaced_only_on_request(results):
    write_results(results, "finetuned", "devops_kb_ft", "tuned-model")
    output = results / "cmp.json"
    output.write_text("reference", encoding="utf-8")
    with pytest.raises(SystemExit):
        compare.main(["--output", "cmp.json"])
    assert output.read_text(encoding="utf-8") == "reference"
    compare.main(["--output", "cmp.json", "--overwrite"])
    assert "hybrid" in json.loads(output.read_text(encoding="utf-8"))


@pytest.fixture
def benchmark(tmp_path):
    def incident(qid, overlap, answerable=True):
        return {"id": qid, "answerable": answerable,
                "independence_check": {"evidence_passages_found_in_finetuning_pairs": ["train.jsonl:1"] if overlap else []}}
    path = tmp_path / "bench.json"
    path.write_text(json.dumps({"incidents": [incident("q1", False), incident("q2", False), incident("q3", True),
                                              incident("oos", False, answerable=False)]}), encoding="utf-8")
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def test_overlap_groups_are_reported_separately(results, benchmark):
    path, sha256 = benchmark
    write_results(results, "bench_a", "devops_kb", "base-model", questions=("q1", "q2", "q3"), dataset_sha256=sha256)
    write_results(results, "bench_b", "devops_kb_ft", "tuned-model", questions=("q1", "q2", "q3"),
                  dataset_sha256=sha256, mrr=0.5)
    compare.main(["--base-tag", "bench_a", "--tuned-tag", "bench_b", "--output", "cmp.json", "--dataset", str(path)])
    report = json.loads((results / "cmp.json").read_text(encoding="utf-8"))
    groups = report["groups"]
    assert set(groups) == {"primary_no_passage_overlap", "secondary_passage_overlap"}
    assert groups["primary_no_passage_overlap"]["question_ids"] == ["q1", "q2"]
    assert groups["secondary_passage_overlap"]["question_ids"] == ["q3"]
    assert groups["primary_no_passage_overlap"]["results"]["hybrid"]["questions"] == 2
    assert groups["secondary_passage_overlap"]["results"]["hybrid"]["mrr_difference"] == -0.5
    assert "hybrid" not in report and report["dataset"]["sha256"] == sha256


def test_results_of_another_dataset_are_refused(results, benchmark):
    path, sha256 = benchmark
    write_results(results, "bench_a", "devops_kb", "base-model", questions=("q1", "q2", "q3"), dataset_sha256="other")
    write_results(results, "bench_b", "devops_kb_ft", "tuned-model", questions=("q1", "q2", "q3"), dataset_sha256=sha256)
    with pytest.raises(ValueError, match="not produced on"):
        compare.main(["--base-tag", "bench_a", "--tuned-tag", "bench_b", "--output", "cmp.json", "--dataset", str(path)])
    assert not (results / "cmp.json").exists()


def test_strategy_without_questions_on_both_sides_is_refused(results):
    write_results(results, "finetuned", "devops_kb_ft", "tuned-model")
    for tag in ("baseline", "finetuned"):
        path = results / f"retrieval_per_question_{tag}.csv"
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        path.write_text("".join(line for line in lines if ",hybrid," not in line), encoding="utf-8")
    with pytest.raises(ValueError, match="same questions for hybrid"):
        compare.main()
    assert not (results / "finetuning_comparison.json").exists()
