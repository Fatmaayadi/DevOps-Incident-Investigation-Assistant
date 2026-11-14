"""Generation benchmark: new metrics and isolation of the results, with a fake workflow and a fake
judge (no LLM call, no index)."""
import hashlib
import json
import sys
from types import SimpleNamespace

import groq
import httpx
import pytest
from langchain_core.exceptions import OutputParserException

from evaluation import run_generation_benchmark as bench
from evaluation import run_retrieval_benchmark as retrieval_bench

EVIDENCE_TEXT = "Readiness describes when a container is ready to serve user requests."
BENCH_INCIDENT = {
    "id": "b-001", "split": "test", "answerable": True, "domain": "kubernetes", "question": "pods get traffic too early",
    "expected_doc_ids": ["pdf-a"], "expected_causes": ["no readiness probe"],
    "expected_answer_criteria": ["recommends a readiness probe", "distinguishes liveness and readiness"],
    "reference_answer": "Add a readiness probe.",
    "evidence": [{"doc_id": "pdf-a", "page_number": 7, "printed_page": 55, "section": "Readiness",
                  "exact_evidence_passage": EVIDENCE_TEXT}],
}
OOS_INCIDENT = {"id": "b-oos", "split": "test", "answerable": False, "domain": "out_of_scope", "question": "kerberos",
                "expected_doc_ids": [], "expected_causes": [], "expected_answer_criteria": [], "evidence": []}
HISTORICAL_INCIDENT = {k: v for k, v in BENCH_INCIDENT.items()
                       if k not in ("expected_answer_criteria", "reference_answer", "evidence")}


def make_answer(status="ok"):
    passages = [{"id": "S1", "doc_id": "pdf-a", "page": 7, "section": None, "text": f"Intro. {EVIDENCE_TEXT}"},
                {"id": "S2", "doc_id": "pdf-b", "page": 2, "section": None, "text": "unrelated"}]
    return {
        "status": status, "analysis": {"summary": "pods receive traffic before they are ready"},
        "possible_causes": [{"cause": "no readiness probe", "explanation": "x", "evidence": ["S1"], "status": "documented"}],
        "investigation_steps": [{"action": "check probes", "command": "kubectl describe pod", "interpretation": "y",
                                 "evidence": ["S1"]}],
        "possible_solutions": [{"solution": "add a readiness probe", "for_cause": "no readiness probe", "evidence": ["S1"]}],
        "references": [{"doc_id": "pdf-a"}], "passages": passages,
        "citations_before_check": 3, "citations_removed": [], "rewrites": 0,
    }


@pytest.fixture
def judge(monkeypatch):
    calls = []

    def fake_judge(prompt, expected_count, **values):
        calls.append(prompt)
        return [True] * expected_count

    monkeypatch.setattr(bench, "judge", fake_judge)
    return calls


def test_benchmark_question_gets_the_new_metrics(tmp_path, monkeypatch, judge):
    monkeypatch.setattr(bench, "CACHE", tmp_path)
    result = bench.score(BENCH_INCIDENT, {"answer": make_answer(), "seconds": 1.0})
    assert result["context_precision"] == 0.5 and result["context_recall"] == 1.0
    assert result["criteria_coverage"] == 1.0 and result["answer_relevancy"] == 1.0
    assert {"correctness", "faithfulness", "context_relevance", "citation_validity", "source_match"} <= set(result)
    assert judge.count(bench.CRITERIA_PROMPT) == 1 and judge.count(bench.ANSWER_RELEVANCY_PROMPT) == 1


def test_deterministic_metrics_do_not_depend_on_the_judge(tmp_path, monkeypatch):
    monkeypatch.setattr(bench, "CACHE", tmp_path)
    monkeypatch.setattr(bench, "judge", lambda prompt, expected_count, **values: None)   # malformed judgements
    result = bench.score(BENCH_INCIDENT, {"answer": make_answer(), "seconds": 1.0})
    assert result["context_precision"] == 0.5 and result["context_recall"] == 1.0
    assert result["criteria_coverage"] is None and result["answer_relevancy"] is None


def test_historical_question_is_scored_exactly_as_before(tmp_path, monkeypatch, judge):
    monkeypatch.setattr(bench, "CACHE", tmp_path)
    result = bench.score(HISTORICAL_INCIDENT, {"answer": make_answer(), "seconds": 1.0})
    new = {"criteria_coverage", "answer_relevancy", "context_precision", "context_recall"}
    assert not new & set(result)
    assert judge == [bench.COVERAGE_PROMPT, bench.SUPPORT_PROMPT, bench.RELEVANCE_PROMPT]


def test_out_of_scope_question_has_no_context_or_criteria_metric(tmp_path, monkeypatch, judge):
    monkeypatch.setattr(bench, "CACHE", tmp_path)
    answer = make_answer("insufficient_evidence")
    answer["possible_causes"][0]["status"] = "hypothesis"
    result = bench.score(OOS_INCIDENT, {"answer": answer, "seconds": 1.0})
    assert result["abstention"] == 1.0
    assert not {"criteria_coverage", "answer_relevancy", "context_precision", "context_recall"} & set(result)


def test_answer_text_contains_causes_steps_and_solutions():
    text = bench.answer_text(make_answer())
    assert "no readiness probe" in text and "kubectl describe pod" in text and "add a readiness probe" in text


@pytest.fixture
def dataset(tmp_path, monkeypatch):
    path = tmp_path / "bench.json"
    path.write_text(json.dumps({"version": "test", "incidents": [BENCH_INCIDENT, OOS_INCIDENT]}), encoding="utf-8")
    monkeypatch.setattr(retrieval_bench, "DATASET", retrieval_bench.DATASET)   # restored after the test
    monkeypatch.setattr(bench, "CACHE", bench.CACHE)
    results = tmp_path / "results"
    results.mkdir()
    monkeypatch.setattr(bench, "RESULTS", results)
    return path


@pytest.mark.parametrize("tag", [[], ["--tag", "v2"]])
def test_historical_tags_are_refused_for_another_dataset(dataset, monkeypatch, tag):
    monkeypatch.setattr(bench, "run_investigation", lambda question: pytest.fail("the workflow was run"))
    monkeypatch.setattr(sys, "argv", ["bench", "--dataset", str(dataset), *tag, "--answers-only"])
    with pytest.raises(SystemExit) as exit_info:
        bench.main()
    assert exit_info.value.code == 2
    assert list(bench.RESULTS.iterdir()) == []


def test_benchmark_run_is_isolated_and_traced(dataset, monkeypatch, judge):
    monkeypatch.setattr(bench, "run_investigation", lambda question: {"answer": make_answer(), "trace": []})
    monkeypatch.setattr(sys, "argv", ["bench", "--dataset", str(dataset), "--tag", "bench_test"])
    bench.main()
    results = bench.RESULTS
    assert sorted(p.name for p in results.iterdir()) == [
        "generation_bench_test", "generation_per_question_bench_test.json", "generation_summary_bench_test.json"]
    summary = json.loads((results / "generation_summary_bench_test.json").read_text(encoding="utf-8"))
    assert summary["dataset"]["sha256"] == hashlib.sha256(dataset.read_bytes()).hexdigest()
    assert summary["questions_total"] == 2 and summary["tag"] == "bench_test"
    for field in ("collection", "embedding_model", "rerank_passages", "final_passages", "judge", "investigator_model"):
        assert field in summary
    assert summary["context_recall"] == {"mean": 1.0, "n": 1}
    assert summary["criteria_coverage"]["n"] == 1 and summary["abstention"]["n"] == 1


# ---------------------------------------------------------------- judge errors and retries (fake Groq client)

REQUEST = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
TOO_LARGE = ("Error code: 429 - {'error': {'message': 'Request too large for model `qwen/qwen3.8-27b` in organization "
             "`org_123abc` service tier `on_demand` on tokens per minute (TPM): Limit 6000, Requested 7016, please "
             "reduce your message size and try again.', 'type': 'tokens', 'code': 'rate_limit_exceeded'}}")
TPD = ("Error code: 429 - {'error': {'message': 'Rate limit reached for model `qwen/qwen3.8-27b` in organization "
       "`org_123abc` service tier `on_demand` on tokens per day (TPD): Limit 200000, Used 199860, Requested 4172. "
       "Please try again in 29m1.824s.', 'type': 'tokens', 'code': 'rate_limit_exceeded'}}")
TPM = ("Error code: 429 - {'error': {'message': 'Rate limit reached for model `qwen/qwen3.8-27b` in organization "
       "`org_123abc` service tier `on_demand` on tokens per minute (TPM): Limit 6000, Used 5000, Requested 2500. "
       "Please try again in 7.5s.'}}")
VALUES = {"items": "CLAIM 1: x\nSOURCE PASSAGES:\n[S1] y\n\nCLAIM 2: z\nSOURCE PASSAGES:\n[S2] w"}


def status_error(cls, status, message):
    return cls(message, response=httpx.Response(status, request=REQUEST), body=None)


@pytest.fixture
def llm(monkeypatch):
    """Fake Groq client: each call takes the next outcome (an exception is raised, anything else returned)."""
    state = SimpleNamespace(outcomes=[], calls=0, max_retries=[], sleeps=[])

    def respond(prompt_value):
        state.calls += 1
        outcome = state.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    def fake_get_llm(model, max_retries=8):
        state.max_retries.append(max_retries)
        return SimpleNamespace(with_structured_output=lambda schema, method: respond)

    monkeypatch.setattr(bench, "get_llm", fake_get_llm)
    monkeypatch.setattr(bench, "SLEEP", state.sleeps.append)
    return state


def verdicts(*values):
    return bench.Verdicts(verdicts=list(values), justification="test")


@pytest.mark.parametrize("error", [status_error(groq.RateLimitError, 429, TOO_LARGE),
                                   status_error(groq.APIStatusError, 413, TOO_LARGE)])
def test_request_too_large_is_sent_once_and_fully_diagnosed(llm, error):
    llm.outcomes = [error, verdicts(True, True)]
    with pytest.raises(bench.JudgeError) as failure:
        bench.judge(bench.SUPPORT_PROMPT, 2, **VALUES)
    problem = failure.value
    assert llm.calls == 1 and llm.sleeps == []          # the same request is not sent again
    assert llm.max_retries == [0]                       # nor resent by the Groq client
    assert problem.kind == "request_too_large" and problem.prompt == "support"
    assert problem.request_chars == len(bench.SUPPORT_PROMPT.format(**VALUES))
    assert problem.limits == {"unit": "TPM", "limit": 6000, "requested": 7016}
    assert "Requested 7016" in str(problem)             # no longer cut before the limits
    assert [h["kind"] for h in problem.history] == ["request_too_large"]
    assert "org_123abc" not in str(problem) and "org_123abc" not in json.dumps(problem.record())


def test_malformed_judgement_is_retried_once(llm):
    llm.outcomes = [OutputParserException("bad json"), verdicts(True, False)]
    assert bench.judge(bench.SUPPORT_PROMPT, 2, **VALUES) == [True, False]
    assert llm.calls == 2


def test_judgement_still_malformed_after_one_retry_fails(llm):
    llm.outcomes = [OutputParserException("bad json"), None, verdicts(True, True)]
    with pytest.raises(bench.JudgeError) as failure:
        bench.judge(bench.CRITERIA_PROMPT, 2, items="1. a\n2. b", answer="x")
    assert failure.value.kind == "malformed" and failure.value.prompt == "criteria" and llm.calls == 2


def test_per_minute_limit_waits_the_delay_given_by_groq(llm):
    llm.outcomes = [status_error(groq.RateLimitError, 429, TPM), verdicts(True)]
    assert bench.judge(bench.ANSWER_RELEVANCY_PROMPT, 1, incident="q", answer="a") == [True]
    assert llm.calls == 2 and llm.sleeps == [7.5]


def test_per_minute_limit_is_not_retried_forever(llm):
    llm.outcomes = [status_error(groq.RateLimitError, 429, TPM)] * (bench.MAX_JUDGE_RETRIES + 1)
    with pytest.raises(bench.JudgeError) as failure:
        bench.judge(bench.SUPPORT_PROMPT, 2, **VALUES)
    assert failure.value.kind == "rate_limit" and llm.calls == bench.MAX_JUDGE_RETRIES + 1


@pytest.mark.parametrize(("error", "kind"), [(status_error(groq.RateLimitError, 429, TPD), "daily_quota"),
                                             (ValueError("unexpected"), "other")])
def test_daily_quota_and_unknown_errors_are_not_retried(llm, error, kind):
    llm.outcomes = [error, verdicts(True, True)]
    with pytest.raises(bench.JudgeError) as failure:
        bench.judge(bench.SUPPORT_PROMPT, 2, **VALUES)
    assert failure.value.kind == kind and llm.calls == 1 and llm.sleeps == []


JSON_FAILED = ("Error code: 400 - {'error': {'message': \"Failed to generate JSON. Please adjust your prompt. See "
               "'failed_generation' for more details.\", 'type': 'invalid_request_error', 'code': "
               "'json_validate_failed', 'failed_generation': 'max completion tokens reached before generating a "
               "valid document'}}")


def test_every_attempt_is_recorded_with_its_kind(llm):
    llm.outcomes = [status_error(groq.BadRequestError, 400, JSON_FAILED), status_error(groq.RateLimitError, 429, TPM),
                    status_error(groq.RateLimitError, 429, TPM), OutputParserException('Failed to parse {"Ans": 1}')]
    with pytest.raises(bench.JudgeError) as failure:
        bench.judge(bench.RELEVANCE_PROMPT, 2, incident="q", items="1. a\n2. b")
    problem = failure.value
    assert problem.attempts == 4 and llm.calls == 4
    assert [h["kind"] for h in problem.history] == ["malformed", "rate_limit", "rate_limit", "malformed"]
    assert [h["attempt"] for h in problem.history] == [1, 2, 3, 4]
    first, second, last = problem.history[0], problem.history[1], problem.history[-1]
    assert first["status_code"] == 400 and first["error_code"] == "json_validate_failed"
    assert first["failed_generation"] == "max completion tokens reached before generating a valid document"
    assert first["waited_seconds"] is None
    assert second["limits"] == {"unit": "TPM", "limit": 6000, "used": 5000, "requested": 2500}
    assert second["waited_seconds"] == 7.5 and llm.sleeps == [7.5, 7.5]
    assert last["error_type"] == "OutputParserException" and last["status_code"] is None
    assert "malformed -> rate_limit -> rate_limit -> malformed" in str(problem)
    record = json.dumps(problem.record())
    assert '"history"' in record and "org_123abc" not in record


def test_successful_judgement_is_unchanged(llm):
    llm.outcomes = [verdicts(True, False)]
    assert bench.judge(bench.SUPPORT_PROMPT, 2, **VALUES) == [True, False]
    llm.outcomes = [verdicts(True)]
    assert bench.judge(bench.SUPPORT_PROMPT, 2, **VALUES) is None   # wrong number of verdicts: ignored
    assert bench.judge(bench.SUPPORT_PROMPT, 0, items="") == [] and llm.calls == 2


def test_judge_failure_is_logged_and_a_used_up_daily_quota_stops_new_judge_calls(dataset, monkeypatch, capsys):
    incidents = [BENCH_INCIDENT, {**BENCH_INCIDENT, "id": "b-002"}, OOS_INCIDENT]
    dataset.write_text(json.dumps({"incidents": incidents}), encoding="utf-8")
    cache = bench.RESULTS / "generation_bench_test"
    cache.mkdir()
    cached = {"id": "b-oos", "domain": "out_of_scope", "answerable": False, "status": "insufficient_evidence",
              "seconds": 1.0, "abstention": 1.0, "rewrites": 0}
    (cache / "b-oos_judgement.json").write_text(json.dumps(cached), encoding="utf-8")
    calls = []

    def quota_used_up(prompt, expected_count, **values):
        calls.append(prompt)
        raise bench.JudgeError("daily_quota", bench.prompt_name(prompt), 100,
                               status_error(groq.RateLimitError, 429, TPD), 1)

    monkeypatch.setattr(bench, "judge", quota_used_up)
    monkeypatch.setattr(bench, "run_investigation", lambda question: {"answer": make_answer(), "trace": []})
    monkeypatch.setattr(sys, "argv", ["bench", "--dataset", str(dataset), "--tag", "bench_test"])
    bench.main()
    assert calls == [bench.COVERAGE_PROMPT]              # b-002 is skipped, no new judge call
    assert sorted(p.name for p in cache.glob("*_judgement.json")) == ["b-oos_judgement.json"]
    summary = json.loads((bench.RESULTS / "generation_summary_bench_test.json").read_text(encoding="utf-8"))
    assert summary["questions_scored"] == 1              # the cached judgement is still read
    lines = (bench.RESULTS / "judge_errors_bench_test.jsonl").read_text(encoding="utf-8").splitlines()
    logged = json.loads(lines[0])
    assert len(lines) == 1 and logged["id"] == "b-001" and logged["kind"] == "daily_quota"
    assert logged["prompt"] == "coverage" and logged["limits"]["unit"] == "TPD"
    output = capsys.readouterr().out
    assert "SKIPPED" in output and "org_123abc" not in output and "org_123abc" not in "\n".join(lines)


# ---------------------------------------------------------------- COVERAGE: strict expected-cause mapping

# the two expected causes of bench-k8s-net-01 and the two outputs of the judge logged on 2026-11-14 08:56
CAUSES = ["kube-proxy not running or failing on worker-3",
          "missing or stale iptables rules for the Service virtual IPs on worker-3"]
OBSERVED_TEXT_KEYS = {CAUSES[0]: True, CAUSES[1]: False}
OBSERVED_NUMBERED_KEYS = {"EXPECTED_CAUSE_1": True, "EXPECTED_CAUSE_2": False}
COVERAGE_VALUES = {"items": "1. " + CAUSES[0] + "\n2. " + CAUSES[1], "answer": "1. kube-proxy problem on worker-3: x"}


def parse_failure(output):
    """The exception PydanticOutputParser raises for a JSON object that is not a Verdicts object."""
    text = json.dumps(output, ensure_ascii=False)
    return OutputParserException(f"Failed to parse Verdicts from completion {text}. Got: ...", llm_output=text)


@pytest.mark.parametrize("output", [OBSERVED_TEXT_KEYS, OBSERVED_NUMBERED_KEYS])
def test_observed_mappings_give_the_judge_verdicts_in_order(output):
    assert bench.verdicts_from_expected_cause_mapping(output, CAUSES) == [True, False]


@pytest.mark.parametrize("output", [{CAUSES[1]: False, CAUSES[0]: True},
                                    {"EXPECTED_CAUSE_2": False, "EXPECTED_CAUSE_1": True}])
def test_mapping_verdicts_follow_the_order_of_the_expected_causes(output):
    assert bench.verdicts_from_expected_cause_mapping(output, CAUSES) == [True, False]


@pytest.mark.parametrize("output", [
    {CAUSES[0].upper(): True, CAUSES[1]: False},                         # approximate key: case
    {CAUSES[0] + " ": True, CAUSES[1]: False},                           # approximate key: space
    {CAUSES[0] + ".": True, CAUSES[1]: False},                           # approximate key: punctuation
    {CAUSES[0].replace("-", "‑"): True, CAUSES[1]: False},          # approximate key: non-breaking hyphen
    {"1. " + CAUSES[0]: True, "2. " + CAUSES[1]: False},                 # numbered line, not the cause text
    {CAUSES[0]: True},                                                   # missing cause
    {"EXPECTED_CAUSE_1": True},                                          # missing number
    {CAUSES[0]: True, CAUSES[1]: False, "DNS resolution failure": True},  # extra key
    {**OBSERVED_TEXT_KEYS, "justification": "x"},                        # extra field
    {"verdicts": [True, False], "justification": "x"},                  # a Verdicts object is not a mapping
    {CAUSES[0]: 1, CAUSES[1]: 0},                                        # not booleans
    {CAUSES[0]: "true", CAUSES[1]: "false"},
    {CAUSES[0]: True, CAUSES[1]: None},
    {"1": True, "2": False},                                             # ambiguous: answer items are numbered too
    {"CAUSE_1": True, "CAUSE_2": False},
    {"EXPECTED_CAUSE_01": True, "EXPECTED_CAUSE_2": False},              # not the exact number
    {"expected_cause_1": True, "expected_cause_2": False},
    {"EXPECTED_CAUSE_1": True, "EXPECTED_CAUSE_3": False},               # number out of range
    {"EXPECTED_CAUSE_0": True, "EXPECTED_CAUSE_1": False},
    {CAUSES[0]: True, "EXPECTED_CAUSE_2": False},                        # mixed forms
    {"kube-proxy problem on worker-3": True, "NetworkPolicy blocking ingress on worker-3": False},  # proposed causes
    [True, False],                                                       # not an object
    {"Ans": 1},
    None,
])
def test_any_other_output_is_refused(output):
    assert bench.verdicts_from_expected_cause_mapping(output, CAUSES) is None


def test_identical_expected_causes_are_refused():
    assert bench.verdicts_from_expected_cause_mapping({"a": True}, ["a", "a"]) is None
    assert bench.verdicts_from_expected_cause_mapping({}, []) is None


@pytest.mark.parametrize("output", [OBSERVED_TEXT_KEYS, OBSERVED_NUMBERED_KEYS])
def test_coverage_mapping_is_read_without_a_new_call(llm, output):
    llm.outcomes = [parse_failure(output), verdicts(False, False)]
    parsing = {}
    assert bench.judge(bench.COVERAGE_PROMPT, 2, expected_causes=CAUSES, parsing=parsing,
                       **COVERAGE_VALUES) == [True, False]
    assert llm.calls == 1 and llm.sleeps == []          # no second call to the judge
    assert parsing == {"correctness_parsing": "expected_cause_mapping", "correctness_judge_output": output}


def test_refused_coverage_mapping_keeps_the_current_behaviour(llm):
    approximate = {CAUSES[0] + ".": True, CAUSES[1]: False}
    llm.outcomes = [parse_failure(approximate), parse_failure(approximate)]
    parsing = {}
    with pytest.raises(bench.JudgeError) as failure:
        bench.judge(bench.COVERAGE_PROMPT, 2, expected_causes=CAUSES, parsing=parsing, **COVERAGE_VALUES)
    assert failure.value.kind == "malformed" and llm.calls == 2   # one retry, as before, then no verdict
    assert parsing == {}


def test_coverage_retry_can_still_succeed_normally(llm):
    llm.outcomes = [parse_failure({"Ans": 1}), verdicts(True, True)]
    parsing = {}
    assert bench.judge(bench.COVERAGE_PROMPT, 2, expected_causes=CAUSES, parsing=parsing,
                       **COVERAGE_VALUES) == [True, True]
    assert llm.calls == 2 and parsing == {}


@pytest.mark.parametrize(("prompt", "values"), [
    (bench.SUPPORT_PROMPT, VALUES), (bench.RELEVANCE_PROMPT, {"incident": "q", "items": "1. a\n2. b"})])
def test_support_and_relevance_never_read_a_mapping(llm, prompt, values):
    llm.outcomes = [parse_failure(OBSERVED_NUMBERED_KEYS), parse_failure(OBSERVED_NUMBERED_KEYS)]
    with pytest.raises(bench.JudgeError) as failure:
        bench.judge(prompt, 2, **values)
    assert failure.value.kind == "malformed" and llm.calls == 2


def test_score_passes_the_expected_causes_to_coverage_only(tmp_path, monkeypatch):
    monkeypatch.setattr(bench, "CACHE", tmp_path)
    seen = {}

    def fake_judge(prompt, expected_count, expected_causes=None, parsing=None, **values):
        seen[bench.prompt_name(prompt)] = expected_causes
        return [True] * expected_count

    monkeypatch.setattr(bench, "judge", fake_judge)
    result = bench.score(BENCH_INCIDENT, {"answer": make_answer(), "seconds": 1.0})
    assert seen == {"coverage": ["no readiness probe"], "support": None, "relevance": None, "criteria": None,
                    "answer_relevancy": None}
    assert "correctness_parsing" not in result   # normal parsing: no trace


def test_score_records_the_mapping_trace_in_the_judgement(tmp_path, monkeypatch, llm):
    monkeypatch.setattr(bench, "CACHE", tmp_path)
    mapping = {"no readiness probe": True}
    # coverage (mapping), support (2 claims), relevance (2 passages), criteria (2), answer relevancy (1)
    llm.outcomes = [parse_failure(mapping), verdicts(True, True), verdicts(True, False), verdicts(True, True),
                    verdicts(True)]
    result = bench.score(BENCH_INCIDENT, {"answer": make_answer(), "seconds": 1.0})
    assert llm.calls == 5                                # one call per prompt, none added
    assert result["correctness"] == 1.0 and result["correctness_parsing"] == "expected_cause_mapping"
    assert result["correctness_judge_output"] == mapping
    saved = json.loads((tmp_path / "b-001_judgement.json").read_text(encoding="utf-8"))
    assert saved["correctness_parsing"] == "expected_cause_mapping"


def test_cached_judgement_is_returned_unchanged_without_any_call(tmp_path, monkeypatch, llm):
    monkeypatch.setattr(bench, "CACHE", tmp_path)
    path = tmp_path / "b-001_judgement.json"
    path.write_text('{"id": "b-001", "correctness": 0.5}', encoding="utf-8")
    before = path.read_bytes()
    assert bench.score(BENCH_INCIDENT, {"answer": make_answer(), "seconds": 1.0}) == {"id": "b-001",
                                                                                     "correctness": 0.5}
    assert llm.calls == 0 and path.read_bytes() == before
