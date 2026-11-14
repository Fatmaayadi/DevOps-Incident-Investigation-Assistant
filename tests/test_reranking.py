"""Reranking option: passages chosen by the cross-encoder, metadata kept, comparison before / after,
and use in the workflow. Fake search and fake cross-encoder: no model and no index needed."""
import pytest

from evaluation import compare_reranking
from incident_assistant import agents, config, retrieval, workflow


def passage(chunk_id, text):
    return {"chunk_id": chunk_id, "doc_id": f"doc-{chunk_id}", "title": f"Title {chunk_id}",
            "source_path": f"markdown/docker/{chunk_id}.md", "domain": "docker", "technology": ["docker"],
            "page": None, "section": "Overview", "text": text, "score": 1.0}


class FakeReranker:
    def predict(self, pairs):
        return [len(text) for _, text in pairs]   # longer text = more relevant


@pytest.fixture
def fake_index(monkeypatch):
    # RRF order: a (found by both searches), then b, then c. Reranker order: b, c, a.
    results = {"semantic": [passage("a", "x"), passage("b", "xxx")],
               "bm25": [passage("a", "x"), passage("c", "xx")]}
    monkeypatch.setattr(retrieval, "search", lambda query, mode, **kwargs: [dict(p) for p in results[mode]])
    monkeypatch.setattr(retrieval, "get_reranker", lambda: FakeReranker())


def test_reranking_changes_the_order_and_keeps_the_metadata(fake_index):
    rrf = retrieval.hybrid_search(["q"], top_k=3)
    reranked = retrieval.hybrid_search(["q"], use_reranker=True, top_k=3)
    assert [p["chunk_id"] for p in rrf] == ["a", "b", "c"]
    assert [p["chunk_id"] for p in reranked] == ["b", "c", "a"]
    assert [p["rrf_rank"] for p in reranked] == [2, 3, 1]
    assert [p["rerank_score"] for p in reranked] == [3, 2, 1]
    first = reranked[0]
    assert (first["doc_id"], first["source_path"], first["section"], first["page"]) == \
           ("doc-b", "markdown/docker/b.md", "Overview", None)
    assert "rrf_score" in first and first["ranks"] == [2]


def test_default_hybrid_search_is_unchanged(fake_index):
    assert all("rrf_rank" not in p and "rerank_score" not in p for p in retrieval.hybrid_search(["q"]))


def test_comparison_shows_the_passages_brought_in_and_left_out(fake_index):
    result = compare_reranking.compare("q", top_k=2)
    assert [p["chunk_id"] for p in result["before"]] == ["a", "b"]
    assert [p["chunk_id"] for p in result["after"]] == ["b", "c"]
    assert result["added"] == ["c"] and result["removed"] == ["a"]


@pytest.fixture
def fake_workflow(monkeypatch):
    calls = {"search": [], "scored": 0}

    def fake_search(queries, domains=None, **options):
        calls["search"].append(options)
        return [dict(passage("a", "x"), rerank_score=5.0)]

    def fake_score(query, passages):
        calls["scored"] += 1
        return passages

    analysis = agents.IncidentAnalysis(
        summary="Pod restarts", technologies=["kubernetes"], symptoms=[], error_messages=[],
        recent_changes=[], search_queries=["pod crashloopbackoff"], missing_information=[],
        needs_clarification=False, clarification_questions=[])
    investigation = agents.Investigation(possible_causes=[], investigation_steps=[], possible_solutions=[],
                                         missing_information=[], confidence_note="ok")
    monkeypatch.setattr(workflow.retrieval, "hybrid_search", fake_search)
    monkeypatch.setattr(workflow.retrieval, "score_passages", fake_score)
    monkeypatch.setattr(workflow.retrieval, "evidence_is_sufficient", lambda passages: True)
    monkeypatch.setattr(workflow.agents, "analyze_incident", lambda text: analysis)
    monkeypatch.setattr(workflow.agents, "investigate", lambda a, p, evidence_insufficient: investigation)
    return calls


def test_workflow_keeps_the_rrf_order_by_default(fake_workflow, monkeypatch):
    monkeypatch.setattr(config, "RERANK_PASSAGES", False)
    state = workflow.run_investigation("pod in CrashLoopBackOff")
    assert fake_workflow["search"] == [{}]          # same call as before the option existed
    assert fake_workflow["scored"] == 1             # scores only, for the evidence check
    assert any("(RRF order)" in line for line in state["trace"])


def test_workflow_option_lets_the_reranker_choose_the_passages(fake_workflow, monkeypatch):
    monkeypatch.setattr(config, "RERANK_PASSAGES", True)
    state = workflow.run_investigation("pod in CrashLoopBackOff")
    assert fake_workflow["search"] == [{"use_reranker": True, "rerank_query": "pod in CrashLoopBackOff"}]
    assert fake_workflow["scored"] == 0             # the reranker already scored the passages
    assert any("(reranked)" in line for line in state["trace"])
    assert state["answer"]["passages"][0]["doc_id"] == "doc-a"
