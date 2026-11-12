"""Generation benchmark: runs the full LangGraph workflow on every test incident and scores the
answers with an LLM judge (JUDGE_MODEL) plus deterministic checks.

Metrics (per question, then averaged):
  - correctness        share of expected causes covered by the answer (judge)
  - faithfulness       share of "documented" claims (causes + solutions) supported by their cited passages (judge)
  - context_relevance  share of the passages given to the agent that are useful for the incident (judge)
  - citation_validity  share of citations pointing to a real passage (deterministic, before cleaning)
  - source_match       share of cited documents that are in the expected documents (deterministic)
  - abstention         for out-of-scope questions: the answer reports insufficient evidence
                       or contains no documented cause (deterministic)

Answers and judgements are cached in evaluation/results/generation/ so the run can be resumed
(the free Groq tier has per-minute and per-day limits).

Usage: python -m evaluation.run_generation_benchmark [--limit N]
"""
import argparse
import json
import time

from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from evaluation.metrics import mean
from evaluation.run_retrieval_benchmark import RESULTS, load_incidents
from incident_assistant import config
from incident_assistant.agents import get_llm
from incident_assistant.workflow import run_investigation

CACHE = RESULTS / "generation"
# Models that produced the recorded results. Another model must use another --tag,
# so that results of different models are never mixed in one comparison.
HISTORICAL_MODELS = {"analyzer": "openai/gpt-oss-120b", "investigator": "openai/gpt-oss-120b",
                     "judge": "qwen/qwen3.8-27b"}


class Verdicts(BaseModel):
    verdicts: list[bool] = Field(description="One true/false verdict per numbered item, in the same order")
    justification: str = Field(description="One short sentence explaining the verdicts")


COVERAGE_PROMPT = ChatPromptTemplate.from_template("""You evaluate a troubleshooting answer.
For each EXPECTED CAUSE, answer true if the ANSWER mentions this cause (same meaning, wording may differ), else false.

EXPECTED CAUSES:
{items}

ANSWER (possible causes proposed):
{answer}""")

SUPPORT_PROMPT = ChatPromptTemplate.from_template("""You check whether claims are supported by their sources.
For each numbered CLAIM, answer true only if the SOURCE PASSAGES cited for it state or directly imply the claim, else false.

{items}""")

RELEVANCE_PROMPT = ChatPromptTemplate.from_template("""INCIDENT: {incident}

For each numbered PASSAGE, answer true if it contains information useful to diagnose or fix this incident, else false.

{items}""")


def judge(prompt: ChatPromptTemplate, expected_count: int, **values) -> list[bool] | None:
    if expected_count == 0:
        return []
    chain = prompt | get_llm(config.JUDGE_MODEL).with_structured_output(Verdicts, method="json_schema")
    try:
        result = chain.invoke(values)
    except Exception:   # the judge sometimes returns a malformed object: one more attempt
        result = chain.invoke(values)
    if len(result.verdicts) != expected_count:   # malformed judgement: ignore rather than guess
        return None
    return result.verdicts


def numbered(lines: list[str]) -> str:
    return "\n".join(f"{i}. {line}" for i, line in enumerate(lines, start=1))


def current_models() -> dict:
    return {"analyzer": config.ANALYZER_MODEL, "investigator": config.INVESTIGATOR_MODEL, "judge": config.JUDGE_MODEL}


def get_answer(incident: dict) -> dict:
    path = CACHE / f"{incident['id']}_answer.json"
    models = {k: v for k, v in current_models().items() if k != "judge"}
    if path.exists():
        record = json.loads(path.read_text(encoding="utf-8"))
        # answers cached before 2026-11-02 22:30 do not record their models (they used HISTORICAL_MODELS)
        if record.get("models", models) != models:
            raise SystemExit(f"{path.name} was produced with {record['models']}: use another --tag")
        return record
    start = time.perf_counter()
    state = run_investigation(incident["question"])
    record = {"answer": state["answer"], "trace": state["trace"], "seconds": round(time.perf_counter() - start, 1),
              "models": models}
    path.write_text(json.dumps(record, indent=2, default=str), encoding="utf-8")
    return record


def score(incident: dict, record: dict) -> dict:
    path = CACHE / f"{incident['id']}_judgement.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    answer = record["answer"]
    result = {"id": incident["id"], "domain": incident["domain"], "answerable": incident["answerable"],
              "status": answer["status"], "seconds": record["seconds"], "judge_model": config.JUDGE_MODEL}
    if answer["status"] == "needs_clarification":
        result["note"] = "assistant asked for clarification"
        path.write_text(json.dumps(result, indent=2), encoding="utf-8")
        return result

    causes = answer["possible_causes"]
    documented = [c for c in causes if c["status"] == "documented"]
    if not incident["answerable"]:
        result["abstention"] = float(answer["status"] == "insufficient_evidence" or not documented)

    passages = {p["id"]: p for p in answer["passages"]}
    if incident["answerable"]:
        verdicts = judge(COVERAGE_PROMPT, len(incident["expected_causes"]),
                         items=numbered(incident["expected_causes"]),
                         answer=numbered([f"{c['cause']}: {c['explanation']}" for c in causes]) or "(none)")
        result["correctness"] = mean([float(v) for v in verdicts]) if verdicts is not None else None

    claims = [(f"{c['cause']}: {c['explanation']}", c["evidence"]) for c in documented]
    claims += [(s["solution"], s["evidence"]) for s in answer["possible_solutions"] if s["evidence"]]
    blocks = [f"CLAIM {i}: {text}\nSOURCE PASSAGES:\n" + "\n".join(f"[{e}] {passages[e]['text']}" for e in ev)
              for i, (text, ev) in enumerate(claims, start=1)]
    verdicts = judge(SUPPORT_PROMPT, len(claims), items="\n\n".join(blocks))
    result["faithfulness"] = mean([float(v) for v in verdicts]) if verdicts else None

    verdicts = judge(RELEVANCE_PROMPT, len(answer["passages"]), incident=incident["question"],
                     items=numbered([p["text"][:700] for p in answer["passages"]]))
    result["context_relevance"] = mean([float(v) for v in verdicts]) if verdicts else None

    total = answer["citations_before_check"]
    result["citation_validity"] = 1 - len(answer["citations_removed"]) / total if total else None
    cited_docs = {r["doc_id"] for r in answer["references"]}
    if incident["answerable"] and cited_docs:
        result["source_match"] = len(cited_docs & set(incident["expected_doc_ids"])) / len(cited_docs)
    result["rewrites"] = answer["rewrites"]
    path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, help="only the first N test incidents")
    parser.add_argument("--tag", default="", help="store results separately, e.g. --tag v2 for the final system (default: earlier configuration)")
    parser.add_argument("--answers-only", action="store_true",
                        help="only produce the workflow answers (when the judge quota is exhausted)")
    args = parser.parse_args()
    if args.tag in ("", "v2") and current_models() != HISTORICAL_MODELS:
        parser.error(f"the recorded results were produced with {HISTORICAL_MODELS}; "
                     f"evaluate {current_models()} with another --tag")
    global CACHE
    suffix = f"_{args.tag}" if args.tag else ""
    CACHE = RESULTS / f"generation{suffix}"
    CACHE.mkdir(parents=True, exist_ok=True)
    incidents = load_incidents("test", answerable_only=False)[:args.limit]

    results = []
    for number, incident in enumerate(incidents, start=1):
        try:
            record = get_answer(incident)
            if args.answers_only:
                print(f"[{number}/{len(incidents)}] {incident['id']}: answer {record['answer']['status']}")
                continue
            results.append(score(incident, record))
            print(f"[{number}/{len(incidents)}] {incident['id']}: {results[-1].get('status')}")
        except Exception as error:   # API limit or transient error: keep going, rerun later
            print(f"[{number}/{len(incidents)}] {incident['id']}: FAILED ({str(error)[:150]})")

    if args.answers_only:
        return
    metrics = ["correctness", "faithfulness", "context_relevance", "citation_validity", "source_match", "abstention"]
    summary = {"date": time.strftime("%Y-%m-%d %H:%M"), "tag": args.tag or "v1",
               "analyzer_model": config.ANALYZER_MODEL, "investigator_model": config.INVESTIGATOR_MODEL,
               "judge": config.JUDGE_MODEL,
               # answers of the earlier configuration are cached: they used its rule, not the current config
               "evidence_rule": f">= {config.EVIDENCE_MIN_PASSAGES} passages with reranker score >= {config.EVIDENCE_MIN_SCORE}"
                                if args.tag else ">= 2 passages with reranker score >= -0.22 (reranker order)",
               "questions_scored": len(results), "questions_total": len(incidents),
               "status_counts": {s: sum(r["status"] == s for r in results) for s in {r["status"] for r in results}},
               "mean_seconds_per_question": round(mean([r["seconds"] for r in results]), 1)}
    for metric in metrics:
        values = [r[metric] for r in results if r.get(metric) is not None]
        summary[metric] = {"mean": round(mean(values), 4), "n": len(values)}
    (RESULTS / f"generation_summary{suffix}.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (RESULTS / f"generation_per_question{suffix}.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
