"""LangGraph workflow with fake agents and fake retrieval: routing, bounded rewrite loop,
clarification branch and citation checking. No LLM, no index needed."""
import pytest

from incident_assistant import agents, workflow


def make_analysis(needs_clarification=False):
    return agents.IncidentAnalysis(
        summary="Pod restarts in CrashLoopBackOff", technologies=["kubernetes"], symptoms=["restarts"],
        error_messages=["CrashLoopBackOff"], recent_changes=[], search_queries=["pod crashloopbackoff"],
        missing_information=["logs"], needs_clarification=needs_clarification,
        clarification_questions=["Which technology?"] if needs_clarification else [])


def make_investigation(evidence):
    return agents.Investigation(
        possible_causes=[agents.Cause(cause="app error", explanation="exits", evidence=evidence, status="documented")],
        investigation_steps=[agents.Step(action="read logs", command="kubectl logs --previous",
                                         interpretation="error shown", evidence=evidence)],
        possible_solutions=[agents.Solution(solution="fix config", for_cause="app error", evidence=evidence)],
        missing_information=[], confidence_note="ok")


PASSAGE = {"chunk_id": "md-k8s-crashloopbackoff#3", "doc_id": "md-k8s-crashloopbackoff",
           "title": "Kubernetes Pod in CrashLoopBackOff", "source_path": "markdown/kubernetes/x.md",
           "domain": "kubernetes", "page": None, "section": "Possible Causes", "text": "...", "score": 1.0,
           "rerank_score": 5.0}


@pytest.fixture
def fake(monkeypatch):
    calls = {"retrieve": 0, "rewrite": 0, "evidence": [True]}

    def fake_search(queries, domains=None, rerank_query=None):
        calls["retrieve"] += 1
        return [dict(PASSAGE)]

    monkeypatch.setattr(workflow.retrieval, "hybrid_search", fake_search)
    monkeypatch.setattr(workflow.retrieval, "score_passages", lambda query, passages: passages)
    monkeypatch.setattr(workflow.retrieval, "evidence_is_sufficient", lambda p: calls["evidence"].pop(0) if calls["evidence"] else False)
    monkeypatch.setattr(workflow.agents, "analyze_incident", lambda text: make_analysis())
    monkeypatch.setattr(workflow.agents, "rewrite_queries", lambda a, q: calls.__setitem__("rewrite", calls["rewrite"] + 1) or ["new query"])
    monkeypatch.setattr(workflow.agents, "investigate", lambda a, p, evidence_insufficient: make_investigation(["S1", "S9"]))
    return calls


def test_sufficient_evidence_goes_straight_to_investigation(fake):
    state = workflow.run_investigation("pod in CrashLoopBackOff")
    assert fake["retrieve"] == 1 and fake["rewrite"] == 0
    assert state["answer"]["status"] == "ok"


def test_rewrite_loop_is_bounded(fake):
    fake["evidence"] = []   # evidence never sufficient
    state = workflow.run_investigation("pod in CrashLoopBackOff")
    assert fake["rewrite"] == workflow.config.MAX_REWRITES
    assert fake["retrieve"] == workflow.config.MAX_REWRITES + 1
    assert state["answer"]["status"] == "insufficient_evidence"


def test_invalid_citations_are_removed(fake):
    answer = workflow.run_investigation("pod in CrashLoopBackOff")["answer"]
    assert answer["possible_causes"][0]["evidence"] == ["S1"]          # S9 does not exist
    assert [r["id"] for r in answer["references"]] == ["S1"]
    assert answer["references"][0]["label"] == "Kubernetes Pod in CrashLoopBackOff - section Possible Causes"


def test_documented_cause_without_valid_citation_becomes_hypothesis(fake, monkeypatch):
    monkeypatch.setattr(workflow.agents, "investigate", lambda a, p, evidence_insufficient: make_investigation(["S7"]))
    answer = workflow.run_investigation("pod in CrashLoopBackOff")["answer"]
    assert answer["possible_causes"][0]["status"] == "hypothesis"
    assert answer["references"] == []


def test_vague_incident_asks_for_clarification(fake, monkeypatch):
    monkeypatch.setattr(workflow.agents, "analyze_incident", lambda text: make_analysis(needs_clarification=True))
    state = workflow.run_investigation("my app is broken")
    assert state["answer"]["status"] == "needs_clarification"
    assert state["answer"]["questions"] == ["Which technology?"]
    assert fake["retrieve"] == 0
