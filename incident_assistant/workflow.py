"""LangGraph workflow: analysis -> queries -> hybrid retrieval -> evidence check
(-> query rewriting, at most MAX_REWRITES times) -> investigation -> answer with checked citations."""
import operator
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph

from incident_assistant import agents, config, retrieval


class State(TypedDict, total=False):
    incident: str
    domains: list[str] | None
    analysis: agents.IncidentAnalysis
    queries: list[str]
    passages: list[dict]
    rewrites: int
    evidence_ok: bool
    investigation: agents.Investigation
    answer: dict
    trace: Annotated[list[str], operator.add]


# ---------------------------------------------------------------- nodes

def analyze_node(state: State) -> dict:
    analysis = agents.analyze_incident(state["incident"])
    return {"analysis": analysis, "rewrites": 0,
            "trace": [f"analyze_incident: technologies={analysis.technologies}, clarification={analysis.needs_clarification}"]}


def clarification_node(state: State) -> dict:
    analysis = state["analysis"]
    answer = {"status": "needs_clarification", "analysis": analysis.model_dump(),
              "questions": analysis.clarification_questions or analysis.missing_information}
    return {"answer": answer, "trace": ["ask_clarification: description too vague, questions returned"]}


def build_queries_node(state: State) -> dict:
    """Agent queries + error messages copied verbatim (exact strings help BM25)."""
    analysis = state["analysis"]
    queries = []
    for query in analysis.search_queries + analysis.error_messages:
        if query and query.lower() not in [q.lower() for q in queries]:
            queries.append(query)
    return {"queries": queries[:5], "trace": [f"build_queries: {queries[:5]}"]}


def retrieve_node(state: State) -> dict:
    # Passages keep the RRF order; the reranker only scores them for the evidence check.
    passages = retrieval.hybrid_search(state["queries"], domains=state.get("domains"))
    retrieval.score_passages(state["incident"], passages)
    if not passages:
        return {"passages": [], "trace": ["hybrid_retrieve: no passage"]}
    scores = sorted((p["rerank_score"] for p in passages), reverse=True)
    return {"passages": passages, "trace": [f"hybrid_retrieve: {len(passages)} passages (RRF order), "
                                            f"reranker scores {[round(s, 1) for s in scores]}"]}


def evaluate_node(state: State) -> dict:
    ok = retrieval.evidence_is_sufficient(state["passages"])
    return {"evidence_ok": ok, "trace": [f"evaluate_evidence: {'sufficient' if ok else 'insufficient'}"]}


def rewrite_node(state: State) -> dict:
    queries = agents.rewrite_queries(state["analysis"], state["queries"])
    return {"queries": queries, "rewrites": state["rewrites"] + 1,
            "trace": [f"rewrite_queries (round {state['rewrites'] + 1}): {queries}"]}


def investigate_node(state: State) -> dict:
    investigation = agents.investigate(state["analysis"], state["passages"],
                                       evidence_insufficient=not state["evidence_ok"])
    return {"investigation": investigation, "trace": ["investigate: structured answer produced"]}


def format_answer_node(state: State) -> dict:
    answer, removed = build_answer(state)
    note = f"format_answer: {len(answer['references'])} sources cited"
    if removed:
        note += f", invalid citations removed: {sorted(set(removed))}"
    return {"answer": answer, "trace": [note]}


# ---------------------------------------------------------------- citation checking

def check_citations(ids: list[str], valid_ids: set[str], removed: list[str]) -> list[str]:
    kept = []
    for passage_id in ids:
        clean = passage_id.strip().strip("[]")
        if clean in valid_ids and clean not in kept:
            kept.append(clean)
        else:
            removed.append(passage_id)
    return kept


def build_answer(state: State) -> tuple[dict, list[str]]:
    """Keep only citations that point to a passage really given to the agent; a 'documented'
    cause without any valid citation is downgraded to 'hypothesis'."""
    passages = state["passages"]
    sources = {f"S{i}": p for i, p in enumerate(passages, start=1)}
    investigation = state["investigation"].model_dump()
    removed: list[str] = []
    citations_before = sum(len(item["evidence"]) for group in ("possible_causes", "investigation_steps",
                                                                 "possible_solutions") for item in investigation[group])

    for cause in investigation["possible_causes"]:
        cause["evidence"] = check_citations(cause["evidence"], set(sources), removed)
        if cause["status"] == "documented" and not cause["evidence"]:
            cause["status"] = "hypothesis"
    for item in investigation["investigation_steps"] + investigation["possible_solutions"]:
        item["evidence"] = check_citations(item["evidence"], set(sources), removed)

    cited = {i for group in ("possible_causes", "investigation_steps", "possible_solutions")
             for item in investigation[group] for i in item["evidence"]}
    references = [{"id": i, "label": agents.reference_label(p), "doc_id": p["doc_id"],
                   "source_path": p["source_path"], "page": p["page"], "section": p["section"]}
                  for i, p in sources.items() if i in cited]
    answer = {
        "status": "ok" if state["evidence_ok"] else "insufficient_evidence",
        "analysis": state["analysis"].model_dump(),
        "queries": state["queries"],
        "rewrites": state["rewrites"],
        **investigation,
        "references": references,
        "passages": [{"id": i, **p} for i, p in sources.items()],
        "citations_before_check": citations_before,
        "citations_removed": removed,
    }
    return answer, removed


# ---------------------------------------------------------------- graph

def after_analysis(state: State) -> str:
    return "ask_clarification" if state["analysis"].needs_clarification else "build_queries"


def after_evaluation(state: State) -> str:
    if state["evidence_ok"] or state["rewrites"] >= config.MAX_REWRITES:
        return "investigate"
    return "rewrite_queries"


def build_graph():
    graph = StateGraph(State)
    graph.add_node("analyze_incident", analyze_node)
    graph.add_node("ask_clarification", clarification_node)
    graph.add_node("build_queries", build_queries_node)
    graph.add_node("hybrid_retrieve", retrieve_node)
    graph.add_node("evaluate_evidence", evaluate_node)
    graph.add_node("rewrite_queries", rewrite_node)
    graph.add_node("investigate", investigate_node)
    graph.add_node("format_answer", format_answer_node)

    graph.add_edge(START, "analyze_incident")
    graph.add_conditional_edges("analyze_incident", after_analysis, ["ask_clarification", "build_queries"])
    graph.add_edge("ask_clarification", END)
    graph.add_edge("build_queries", "hybrid_retrieve")
    graph.add_edge("hybrid_retrieve", "evaluate_evidence")
    graph.add_conditional_edges("evaluate_evidence", after_evaluation, ["rewrite_queries", "investigate"])
    graph.add_edge("rewrite_queries", "hybrid_retrieve")
    graph.add_edge("investigate", "format_answer")
    graph.add_edge("format_answer", END)
    return graph.compile()


def run_investigation(incident: str, domains: list[str] | None = None) -> dict:
    """Run the whole workflow and return the final state (answer + trace)."""
    return build_graph().invoke({"incident": incident, "domains": domains or None, "trace": []})
