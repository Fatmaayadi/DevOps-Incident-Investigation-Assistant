"""Command line of the retrieval benchmark, on a temporary results folder and a fake search."""
import csv
import hashlib
import json
import sys
from types import SimpleNamespace

import pytest

from evaluation import run_retrieval_benchmark as bench
from evaluation.metrics import evidence_units

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


# ---------------------------------------------------------------- --dataset (benchmark v1)

BENCHMARK = bench.DEFAULT_DATASET.parent / "benchmark_v1.json"
EVIDENCE_TEXT = "Readiness describes when a container is ready to serve user requests."
SYNTHETIC = {"version": "test", "incidents": [
    {"id": "b-001", "split": "test", "answerable": True, "domain": "kubernetes", "question": "readiness",
     "expected_doc_ids": ["pdf-a"], "evidence": [
         {"doc_id": "pdf-a", "page_number": 7, "printed_page": None, "section": "Readiness",
          "exact_evidence_passage": EVIDENCE_TEXT}]},
    {"id": "b-oos", "split": "test", "answerable": False, "domain": "out_of_scope", "question": "kerberos",
     "expected_doc_ids": [], "evidence": []},
]}


def test_default_dataset_is_the_historical_one():
    assert bench.DATASET == bench.DEFAULT_DATASET and bench.DEFAULT_DATASET.name == "incidents_eval.json"
    assert bench.is_default_dataset()
    assert len(bench.load_incidents("test")) == 48
    assert len(bench.load_incidents("test", answerable_only=False)) == 53


@pytest.mark.skipif(not BENCHMARK.exists(), reason="benchmark_v1.json not available")
def test_benchmark_v1_is_loaded_with_its_answerable_and_out_of_scope_questions(monkeypatch):
    monkeypatch.setattr(bench, "DATASET", BENCHMARK)
    answerable = bench.load_incidents("test")
    everything = bench.load_incidents("test", answerable_only=False)
    assert len(answerable) == 34 and len(everything) == 37
    assert sum(not i["answerable"] for i in everything) == 3
    assert all(evidence_units(i) for i in answerable)
    assert sum(len(evidence_units(i)) for i in answerable) == 67
    assert not bench.is_default_dataset()


@pytest.fixture
def synthetic(tmp_path, monkeypatch):
    dataset = tmp_path / "bench.json"
    dataset.write_text(json.dumps(SYNTHETIC), encoding="utf-8")
    results = tmp_path / "results"
    results.mkdir()
    monkeypatch.setattr(bench, "RESULTS", results)
    monkeypatch.setattr(bench, "DATASET", bench.DATASET)   # restored after the test
    calls = []

    def retrieve(incident, strategy, queries, collection, model):
        calls.append(incident["id"])
        return [{"doc_id": "pdf-b", "page": 1, "section": None, "text": "other"},
                {"doc_id": "pdf-a", "page": 7, "section": None, "text": f"Intro. {EVIDENCE_TEXT}"}]

    monkeypatch.setattr(bench, "retrieve", retrieve)

    def main(*args):
        monkeypatch.setattr(sys, "argv", ["run_retrieval_benchmark", "--dataset", str(dataset), *args])
        bench.main()

    main.dataset, main.results, main.calls = dataset, results, calls
    return main


def test_benchmark_results_have_evidence_metrics_and_provenance(synthetic):
    synthetic("--tag", "bench_test", "--raw-only", "--strategies", "bm25")
    summary = json.loads((synthetic.results / "retrieval_summary_bench_test.json").read_text(encoding="utf-8"))
    assert synthetic.calls == ["b-001"]   # the out-of-scope question is not in the retrieval metrics
    assert summary["questions"] == 1
    assert summary["dataset"]["sha256"] == hashlib.sha256(synthetic.dataset.read_bytes()).hexdigest()
    assert summary["dataset"]["version"] == "test" and summary["ks"] == list(bench.KS)
    assert "rerank_passages" in summary and summary["tag"] == "bench_test"
    result = summary["results"][0]
    assert result["hit@1"] == 0.0 and result["hit@3"] == 1.0
    assert result["evidence_recall@1"] == 0.0 and result["evidence_recall@3"] == 1.0
    assert result["evidence_mrr"] == 0.5
    with open(synthetic.results / "retrieval_per_question_bench_test.csv", encoding="utf-8") as f:
        row = next(csv.DictReader(f))
    assert float(row["evidence_precision@3"]) == pytest.approx(1 / 3)


@pytest.mark.parametrize("tag", ["baseline", "finetuned"])
def test_historical_tags_are_refused_for_another_dataset(synthetic, tag):
    with pytest.raises(SystemExit):
        synthetic("--tag", tag, "--raw-only")
    assert synthetic.calls == []
    assert list(synthetic.results.iterdir()) == []


def test_missing_dataset_is_refused(run):
    with pytest.raises(SystemExit):
        run("--tag", "new", "--dataset", "does/not/exist.json")
    assert run.calls == []


def test_benchmark_analyzer_queries_use_their_own_cache(synthetic, monkeypatch):
    used = {}

    def fake_analyzer(incidents, cache_path=None, answers_dir=None):
        used.update(cache_path=cache_path, answers_dir=answers_dir)
        return {i["id"]: ["readiness probe"] for i in incidents}

    monkeypatch.setattr(bench, "analyzer_queries", fake_analyzer)
    synthetic("--tag", "bench_test", "--strategies", "bm25")
    assert used == {"cache_path": synthetic.results / "analyzer_queries_bench_test.json",
                    "answers_dir": synthetic.results / "generation_bench_test"}


def test_analyzer_cache_of_a_benchmark_leaves_the_historical_cache_untouched(tmp_path, monkeypatch):
    from incident_assistant import agents
    historical = tmp_path / "analyzer_queries.json"
    historical.write_text("reference", encoding="utf-8")
    monkeypatch.setattr(bench, "ANALYZER_CACHE", historical)
    monkeypatch.setattr(agents, "analyze_incident",
                        lambda question: SimpleNamespace(search_queries=["q1", "Q1"], error_messages=["err"]))
    cache = tmp_path / "analyzer_queries_bench_test.json"
    result = bench.analyzer_queries([{"id": "b-001", "question": "q"}], cache, tmp_path / "generation_bench_test")
    assert result == {"b-001": ["q1", "err"]}
    assert json.loads(cache.read_text(encoding="utf-8")) == result
    assert historical.read_text(encoding="utf-8") == "reference"
