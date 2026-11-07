"""Command line of the retrieval benchmark, on a temporary results folder and a fake search."""
import json
import sys

import pytest

from evaluation import run_retrieval_benchmark as bench

INCIDENT = {"id": "x-001", "split": "test", "answerable": True, "domain": "linux", "question": "disk full",
            "expected_doc_ids": ["md-a"]}


@pytest.fixture
def run(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(bench, "RESULTS", tmp_path)
    monkeypatch.setattr(bench, "load_incidents", lambda split: [INCIDENT])

    def retrieve(incident, strategy, queries, collection, model):
        calls.append(strategy)
        return [{"doc_id": "md-a"}]

    monkeypatch.setattr(bench, "retrieve", retrieve)

    def main(*args):
        monkeypatch.setattr(sys, "argv", ["run_retrieval_benchmark", "--raw-only", *args])
        bench.main()

    main.calls = calls
    main.results = tmp_path
    return main


def test_results_are_written_for_a_new_tag(run):
    run("--tag", "new", "--strategies", "bm25")
    summary = json.loads((run.results / "retrieval_summary_new.json").read_text(encoding="utf-8"))
    assert summary["results"][0]["mrr"] == 1.0
    assert (run.results / "retrieval_per_question_new.csv").exists()


@pytest.mark.parametrize("name", ["retrieval_per_question_baseline.csv", "retrieval_summary_baseline.json"])
def test_existing_results_are_refused_before_any_search(run, capsys, name):
    reference = run.results / name
    reference.write_text("reference", encoding="utf-8")
    with pytest.raises(SystemExit):
        run("--strategies", "bm25")
    assert reference.read_text(encoding="utf-8") == "reference"
    assert run.calls == []
    assert name in capsys.readouterr().err


def test_existing_results_are_refused_before_the_agent_is_called(run, monkeypatch):
    def no_agent(incidents):
        pytest.fail("the agent was called before the existing results were refused")

    reference = run.results / "retrieval_summary_baseline.json"
    reference.write_text("reference", encoding="utf-8")
    monkeypatch.setattr(bench, "analyzer_queries", no_agent)
    monkeypatch.setattr(sys, "argv", ["run_retrieval_benchmark"])   # without --raw-only
    with pytest.raises(SystemExit):
        bench.main()
    assert reference.read_text(encoding="utf-8") == "reference"
    assert run.calls == []


def test_existing_results_are_replaced_only_on_request(run):
    reference = run.results / "retrieval_summary_baseline.json"
    reference.write_text("reference", encoding="utf-8")
    run("--strategies", "bm25", "--overwrite")
    assert json.loads(reference.read_text(encoding="utf-8"))["results"][0]["strategy"] == "bm25"


@pytest.mark.parametrize("name", ["rerank", "hybrid-rerank", "hybird"])
def test_unknown_strategy_is_refused(run, name):
    with pytest.raises(SystemExit):
        run("--tag", "new", "--strategies", name)
    assert run.calls == []
    assert not (run.results / "retrieval_summary_new.json").exists()
