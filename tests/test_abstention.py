"""Abstention report from cached answers (synthetic answers, no LLM)."""
import json
import sys

import pytest

from evaluation import abstention
from evaluation import run_retrieval_benchmark as retrieval_bench


@pytest.mark.parametrize(("answerable", "status", "documented", "expected"), [
    (True, "ok", 2, "answered"),
    (True, "insufficient_evidence", 0, "false_abstention"),
    (True, "ok", 0, "false_abstention"),
    (False, "insufficient_evidence", 0, "justified_abstention"),
    (False, "ok", 0, "justified_abstention"),
    (False, "ok", 1, "answered_out_of_scope"),
    (False, "insufficient_evidence", 1, "insufficient_evidence_with_documented_causes"),
    (True, "insufficient_evidence", 1, "insufficient_evidence_with_documented_causes"),
    (False, "needs_clarification", 0, "clarification"),
])
def test_category(answerable, status, documented, expected):
    assert abstention.category(answerable, status, documented) == expected


CASES = {   # id: (answerable, status, documented causes)
    "a-ok": (True, "ok", 1), "a-miss": (True, "insufficient_evidence", 0),
    "o-good": (False, "insufficient_evidence", 0), "o-bad": (False, "ok", 1),
    "o-mixed": (False, "insufficient_evidence", 1), "o-clar": (False, "needs_clarification", 0),
}


@pytest.fixture
def benchmark(tmp_path, monkeypatch):
    incidents = [{"id": i, "split": "test", "answerable": a} for i, (a, _, _) in CASES.items()]
    dataset = tmp_path / "bench.json"
    dataset.write_text(json.dumps({"incidents": incidents}), encoding="utf-8")
    answers = tmp_path / "generation_bench_test"
    answers.mkdir()
    for qid, (_, status, documented) in CASES.items():
        causes = [{"status": "documented"}] * documented + [{"status": "hypothesis"}]
        (answers / f"{qid}_answer.json").write_text(json.dumps({"answer": {"status": status, "possible_causes": causes}}),
                                                     encoding="utf-8")
    monkeypatch.setattr(abstention, "RESULTS", tmp_path)
    monkeypatch.setattr(retrieval_bench, "DATASET", retrieval_bench.DATASET)   # restored after the test
    return dataset


def test_benchmark_abstention_report(benchmark, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["abstention", "--dataset", str(benchmark), "--tag", "bench_test"])
    abstention.main()
    report = json.loads((benchmark.parent / "abstention_bench_test.json").read_text(encoding="utf-8"))
    assert report["categories"] == {"a-ok": "answered", "a-miss": "false_abstention", "o-good": "justified_abstention",
                                    "o-bad": "answered_out_of_scope",
                                    "o-mixed": "insufficient_evidence_with_documented_causes", "o-clar": "clarification"}
    assert report["out_of_scope_questions"] == 4 and report["out_of_scope_correct_abstention_rate"] == 0.75
    assert report["answerable_false_abstention_rate"] == 0.5
    assert report["dataset"]["name"] == "bench.json"
    assert not (benchmark.parent / "abstention.json").exists()


@pytest.mark.parametrize("tag", [[], ["--tag", "v2"]])
def test_historical_tags_are_refused_for_another_dataset(benchmark, monkeypatch, tag):
    monkeypatch.setattr(sys, "argv", ["abstention", "--dataset", str(benchmark), *tag])
    with pytest.raises(SystemExit):
        abstention.main()
    assert not list(benchmark.parent.glob("abstention*.json"))
