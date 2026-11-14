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
Faithfulness only checks the documented causes and the solutions with citations: hypotheses and
investigation steps are not checked.

Only when the dataset provides them (benchmark_v1.json: evidence, expected_answer_criteria):
  - criteria_coverage  share of expected_answer_criteria met by the whole answer (judge)
  - answer_relevancy   1 if the answer addresses the incident asked, else 0 (judge, one verdict)
  - context_precision  share of the passages given to the agent that match an evidence unit
                       (deterministic; lower bound, the evidence list is not exhaustive)
  - context_recall     share of the evidence units found in the passages given to the agent (deterministic)
Evidence matching is defined in evaluation/metrics.py (passage_matches_unit).

Answers and judgements are cached in evaluation/results/generation/ so the run can be resumed
(the free Groq tier has per-minute and per-day limits).

Judge errors (judge()): a request too large for the model is not sent again (the same request would
fail again); a malformed judgement is retried once; per-minute limits and temporary network or
service errors are retried with the delay given by Groq; a used-up daily quota stops the judge calls
for the rest of the run (questions already judged are still read from the cache). Each judge failure
is printed in full and appended to judge_errors_<tag>.jsonl with the prompt name, the request size
and the limits reported by Groq (organization identifiers are masked).
COVERAGE only: when the judge returns {expected cause: true/false} instead of the Verdicts object,
its verdicts are read from that mapping under strict rules (exact cause texts or EXPECTED_CAUSE_<n>,
every cause exactly once, boolean values; see verdicts_from_expected_cause_mapping), without a new
call; the judgement records correctness_parsing = "expected_cause_mapping" and the judge output.

Usage: python -m evaluation.run_generation_benchmark [--limit N]
       python -m evaluation.run_generation_benchmark --dataset evaluation/datasets/benchmark_v1.json --tag bench_v1
"""
import argparse
import json
import re
import time

import groq
from langchain_core.exceptions import OutputParserException
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field, ValidationError

from evaluation.metrics import MIN_FRAGMENT_CHARS, context_precision, context_recall, evidence_units, mean
from evaluation.run_retrieval_benchmark import (DEFAULT_DATASET, RESULTS, dataset_info, load_incidents,
                                                select_dataset)
from incident_assistant import config
from incident_assistant.agents import classify_llm_error, get_llm, groq_delay
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

CRITERIA_PROMPT = ChatPromptTemplate.from_template("""You evaluate a troubleshooting answer.
For each numbered CRITERION, answer true if the ANSWER satisfies it (same meaning, wording may differ), else false.

CRITERIA:
{items}

ANSWER:
{answer}""")

ANSWER_RELEVANCY_PROMPT = ChatPromptTemplate.from_template("""INCIDENT: {incident}

ANSWER:
{answer}

Give exactly one verdict: true if the ANSWER addresses this incident (it diagnoses or helps to investigate
the problem described), false if it answers another problem or does not address the incident.""")


PROMPT_NAMES = ((COVERAGE_PROMPT, "coverage"), (SUPPORT_PROMPT, "support"), (RELEVANCE_PROMPT, "relevance"),
                (CRITERIA_PROMPT, "criteria"), (ANSWER_RELEVANCY_PROMPT, "answer_relevancy"))
MAX_JUDGE_RETRIES = 8          # per-minute limits and temporary network or service errors
RETRY_KINDS = {"rate_limit", "network", "service"}
SLEEP = time.sleep             # replaced in the tests


def prompt_name(prompt: ChatPromptTemplate) -> str:
    return next((name for p, name in PROMPT_NAMES if p is prompt), "unknown")


def mask(text: str) -> str:
    """Error text without the Groq organization identifier."""
    return re.sub(r"org_[A-Za-z0-9]+", "org_***", text)


def reported_limits(text: str) -> dict:
    """Limit, Used and Requested reported by Groq, e.g. "tokens per minute (TPM): Limit 6000, Requested 7016"."""
    limits = {}
    unit = re.search(r"\((TPM|TPD|RPM|RPD)\)", text)
    if unit:
        limits["unit"] = unit.group(1)
    for key in ("Limit", "Used", "Requested"):
        value = re.search(rf"{key} (\d+)", text)
        if value:
            limits[key.lower()] = int(value.group(1))
    return limits


def judge_error_kind(error: Exception) -> str:
    """request_too_large, daily_quota, rate_limit, network, service, configuration, malformed or other."""
    text = str(error).lower()
    if (getattr(error, "status_code", None) == 413 or "request too large" in text
            or "reduce the length" in text or "context_length_exceeded" in text):
        return "request_too_large"
    problem = classify_llm_error(error, config.JUDGE_MODEL)
    if problem is not None:
        return problem.kind
    if isinstance(error, (OutputParserException, ValidationError, groq.BadRequestError)):
        return "malformed"
    return "other"


def attempt_record(attempt: int, kind: str, error: Exception, waited: float | None = None) -> dict:
    """One failed judge call: its kind, the HTTP status, the Groq error code, the limits and the
    failed generation reported by Groq, the delay waited before the next call (None: no wait)."""
    detail = mask(str(error))
    code = re.search(r"'code': '([^']+)'", detail)
    failed = re.search(r"'failed_generation': '((?:[^'\\]|\\.)*)'", detail)
    return {"attempt": attempt, "kind": kind, "error_type": type(error).__name__,
            "status_code": getattr(error, "status_code", None), "error_code": code.group(1) if code else None,
            "limits": reported_limits(detail), "failed_generation": failed.group(1)[:300] if failed else None,
            "waited_seconds": waited, "detail": detail[:500]}


class JudgeError(RuntimeError):
    """A judge call failed: which prompt, how large the request was, what Groq reported and the
    kind of every attempt (history)."""

    def __init__(self, kind: str, prompt: str, request_chars: int, error: Exception, attempts: int,
                 history: list[dict] | None = None):
        self.kind, self.prompt, self.request_chars, self.attempts = kind, prompt, request_chars, attempts
        self.status_code = getattr(error, "status_code", None)
        self.detail = mask(str(error))
        self.limits = reported_limits(self.detail)
        self.history = history or []
        sequence = " -> ".join(h["kind"] for h in self.history) or kind
        super().__init__(f"judge {kind} on the {prompt} prompt ({request_chars} characters, "
                         f"{attempts} attempt(s): {sequence}, HTTP {self.status_code}, limits {self.limits}): "
                         f"{self.detail[:1000]}")

    def record(self) -> dict:
        return {"kind": self.kind, "prompt": self.prompt, "request_chars": self.request_chars,
                "attempts": self.attempts, "status_code": self.status_code, "limits": self.limits,
                "detail": self.detail[:2000], "history": self.history}


EXPECTED_CAUSE_KEY = re.compile(r"EXPECTED_CAUSE_([1-9][0-9]*)")


def verdicts_from_expected_cause_mapping(obj, expected_causes: list[str]) -> list[bool] | None:
    """Verdicts of a COVERAGE judgement returned as {expected cause: true/false} instead of Verdicts.

    Accepted only when every key uses the same form, with no approximate matching or normalization:
      - the exact text of an expected cause, or
      - EXPECTED_CAUSE_<n>, n being the number of the expected cause in the prompt (1..N);
    each expected cause appears exactly once, there is no other key, and every value is a JSON boolean.
    Returns the verdicts in the order of expected_causes, or None (the judgement stays malformed)."""
    if not isinstance(obj, dict) or not expected_causes or len(obj) != len(expected_causes):
        return None
    if len(set(expected_causes)) != len(expected_causes):   # two identical causes: keys would be ambiguous
        return None
    if not all(isinstance(value, bool) for value in obj.values()):   # 1, "true" or null are refused
        return None
    if set(obj) == set(expected_causes):
        return [obj[cause] for cause in expected_causes]
    matches = [EXPECTED_CAUSE_KEY.fullmatch(key) for key in obj]
    if all(matches) and sorted(int(m.group(1)) for m in matches) == list(range(1, len(expected_causes) + 1)):
        return [obj[f"EXPECTED_CAUSE_{n}"] for n in range(1, len(expected_causes) + 1)]
    return None


def judge(prompt: ChatPromptTemplate, expected_count: int, expected_causes: list[str] | None = None,
          parsing: dict | None = None, **values) -> list[bool] | None:
    """Judge verdicts, None when their number is wrong. expected_causes (COVERAGE only): after a
    parsing failure, the strict expected-cause mapping is tried before any new call; when it is
    used, parsing receives the trace (correctness_parsing and the judge output)."""
    if expected_count == 0:
        return []
    name, request_chars = prompt_name(prompt), len(prompt.format(**values))
    # max_retries=0: the client would otherwise resend every 429, including "request too large"
    chain = prompt | get_llm(config.JUDGE_MODEL, max_retries=0).with_structured_output(Verdicts, method="json_schema")
    malformed_retried = False
    history = []   # every failed attempt, also when a later attempt succeeds (only reported on failure)
    for attempt in range(1, MAX_JUDGE_RETRIES + 2):
        try:
            result = chain.invoke(values)
            if result is None:
                raise OutputParserException("the judge returned no structured object")
        except Exception as error:
            kind = judge_error_kind(error)
            if expected_causes is not None and isinstance(error, OutputParserException) and error.llm_output:
                try:
                    output = json.loads(error.llm_output)
                except ValueError:
                    output = None
                mapped = verdicts_from_expected_cause_mapping(output, expected_causes)
                if mapped is not None and len(mapped) == expected_count:   # the judge's own verdicts, no new call
                    if parsing is not None:
                        parsing.update({"correctness_parsing": "expected_cause_mapping",
                                        "correctness_judge_output": output})
                    return mapped
            if kind == "malformed" and not malformed_retried and attempt <= MAX_JUDGE_RETRIES:
                # the judge sometimes returns a malformed object: one more attempt
                malformed_retried = True
                history.append(attempt_record(attempt, kind, error))
                continue
            if kind in RETRY_KINDS and attempt <= MAX_JUDGE_RETRIES:
                delay = groq_delay(error)
                delay = delay if delay is not None else min(2 ** attempt, 30)
                history.append(attempt_record(attempt, kind, error, delay))
                SLEEP(delay)
                continue
            history.append(attempt_record(attempt, kind, error))
            raise JudgeError(kind, name, request_chars, error, attempt, history) from error
        if len(result.verdicts) != expected_count:   # malformed judgement: ignore rather than guess
            return None
        return result.verdicts
    raise AssertionError("unreachable")


def numbered(lines: list[str]) -> str:
    return "\n".join(f"{i}. {line}" for i, line in enumerate(lines, start=1))


def answer_text(answer: dict) -> str:
    """The whole answer as plain text for the judge: summary, causes, steps and solutions."""
    lines = [f"Summary: {answer.get('analysis', {}).get('summary', '')}"]
    lines += [f"Cause ({c['status']}): {c['cause']}: {c['explanation']}" for c in answer.get("possible_causes", [])]
    lines += [f"Step: {s['action']}" + (f" (command: {s['command']})" if s.get("command") else "")
              + f": {s['interpretation']}" for s in answer.get("investigation_steps", [])]
    lines += [f"Solution: {s['solution']}" for s in answer.get("possible_solutions", [])]
    return "\n".join(lines)


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
        parsing = {}   # filled only when the verdicts were read from an expected-cause mapping
        verdicts = judge(COVERAGE_PROMPT, len(incident["expected_causes"]),
                         expected_causes=incident["expected_causes"], parsing=parsing,
                         items=numbered(incident["expected_causes"]),
                         answer=numbered([f"{c['cause']}: {c['explanation']}" for c in causes]) or "(none)")
        result["correctness"] = mean([float(v) for v in verdicts]) if verdicts is not None else None
        result.update(parsing)

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

    # Metrics of the benchmark fields (absent from the historical dataset: nothing changes for it).
    units = evidence_units(incident)
    if units:   # deterministic, no judge
        result["context_precision"] = context_precision(answer["passages"], units)
        result["context_recall"] = context_recall(answer["passages"], units)
    criteria = incident.get("expected_answer_criteria") or []
    if incident["answerable"] and criteria:
        verdicts = judge(CRITERIA_PROMPT, len(criteria), items=numbered(criteria), answer=answer_text(answer))
        result["criteria_coverage"] = mean([float(v) for v in verdicts]) if verdicts is not None else None
    if incident["answerable"] and "evidence" in incident:
        verdicts = judge(ANSWER_RELEVANCY_PROMPT, 1, incident=incident["question"], answer=answer_text(answer))
        result["answer_relevancy"] = float(verdicts[0]) if verdicts is not None else None
    result["rewrites"] = answer["rewrites"]
    path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, help="only the first N test incidents")
    parser.add_argument("--tag", default="", help="store results separately, e.g. --tag v2 for the final system (default: earlier configuration)")
    parser.add_argument("--answers-only", action="store_true",
                        help="only produce the workflow answers (when the judge quota is exhausted)")
    parser.add_argument("--dataset", help=f"evaluation dataset (default: {DEFAULT_DATASET.name}); "
                                          "another dataset needs its own --tag")
    args = parser.parse_args()
    select_dataset(parser, args.dataset, args.tag, ("", "v2"))
    if args.tag in ("", "v2") and current_models() != HISTORICAL_MODELS:
        parser.error(f"the recorded results were produced with {HISTORICAL_MODELS}; "
                     f"evaluate {current_models()} with another --tag")
    global CACHE
    suffix = f"_{args.tag}" if args.tag else ""
    CACHE = RESULTS / f"generation{suffix}"
    CACHE.mkdir(parents=True, exist_ok=True)
    incidents = load_incidents("test", answerable_only=False)[:args.limit]

    error_log = RESULTS / f"judge_errors{suffix}.jsonl"
    daily_quota_used_up = False
    results = []
    for number, incident in enumerate(incidents, start=1):
        prefix = f"[{number}/{len(incidents)}] {incident['id']}"
        try:
            record = get_answer(incident)
            if args.answers_only:
                print(f"{prefix}: answer {record['answer']['status']}")
                continue
            if daily_quota_used_up and not (CACHE / f"{incident['id']}_judgement.json").exists():
                print(f"{prefix}: SKIPPED (daily quota of the judge used up)")
                continue
            results.append(score(incident, record))
            note = " (coverage read from the expected-cause mapping)" if results[-1].get("correctness_parsing") else ""
            print(f"{prefix}: {results[-1].get('status')}{note}")
        except JudgeError as error:   # rerun later: the judgements already saved are kept
            print(f"{prefix}: JUDGE FAILED ({error})")
            with open(error_log, "a", encoding="utf-8") as f:
                f.write(json.dumps({"date": time.strftime("%Y-%m-%d %H:%M:%S"), "id": incident["id"],
                                    "judge_model": config.JUDGE_MODEL, **error.record()}) + "\n")
            if error.kind == "daily_quota":   # every new judge call would fail: only read the cache now
                daily_quota_used_up = True
        except Exception as error:   # API limit or transient error: keep going, rerun later
            print(f"{prefix}: FAILED ({type(error).__name__}: {mask(str(error))[:1000]})")

    if args.answers_only:
        return
    metrics = ["correctness", "faithfulness", "context_relevance", "citation_validity", "source_match", "abstention"]
    # metrics of the benchmark fields, only when the dataset provides them
    metrics += [m for m in ("criteria_coverage", "answer_relevancy", "context_precision", "context_recall")
                if any(m in r for r in results)]
    summary = {"date": time.strftime("%Y-%m-%d %H:%M"), "tag": args.tag or "v1",
               "analyzer_model": config.ANALYZER_MODEL, "investigator_model": config.INVESTIGATOR_MODEL,
               "judge": config.JUDGE_MODEL,
               # answers of the earlier configuration are cached: they used its rule, not the current config
               "evidence_rule": f">= {config.EVIDENCE_MIN_PASSAGES} passages with reranker score >= {config.EVIDENCE_MIN_SCORE}"
                                if args.tag else ">= 2 passages with reranker score >= -0.22 (reranker order)",
               "dataset": dataset_info(), "collection": config.COLLECTION_NAME,
               "embedding_model": config.EMBEDDING_MODEL, "reranker": config.RERANKER_MODEL,
               "rerank_passages": config.RERANK_PASSAGES, "final_passages": config.FINAL_PASSAGES,
               "candidates_per_search": config.CANDIDATES_PER_SEARCH, "rrf_k": config.RRF_K,
               "evidence_matching_min_fragment_chars": MIN_FRAGMENT_CHARS,
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
