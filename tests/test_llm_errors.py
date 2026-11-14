"""LLM error handling, retries and model configuration. No network: Groq errors are built by hand."""
import importlib.util
import json
import os
import subprocess
import sys
from types import SimpleNamespace

import groq
import httpx
import pytest

from incident_assistant import agents, config

REQUEST = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
TPD = ("Error code: 429 - {'error': {'message': 'Rate limit reached for model `openai/gpt-oss-120b` in organization "
       "`org_123abc` service tier `on_demand` on tokens per day (TPD): Limit 200000, Used 199860, Requested 4172. "
       "Please try again in 29m1.824s. Need more tokens?', 'type': 'tokens', 'code': 'rate_limit_exceeded'}}")
TPM = ("Error code: 429 - {'error': {'message': 'Rate limit reached for model `openai/gpt-oss-120b` in organization "
       "`org_123abc` service tier `on_demand` on tokens per minute (TPM): Limit 8000, Used 7000, Requested 2500. "
       "Please try again in 7.5s.'}}")


def status_error(cls, status, message="error", headers=None):
    return cls(message, response=httpx.Response(status, request=REQUEST, headers=headers or {}), body=None)


class FakeChain:
    """Raises the given errors one after the other, then returns "answer"."""

    def __init__(self, *errors):
        self.errors, self.calls = list(errors), 0

    def invoke(self, values):
        self.calls += 1
        if self.errors:
            raise self.errors.pop(0)
        return "answer"


# ---------------------------------------------------------------- error categories

def test_daily_quota_uses_the_delay_given_by_groq():
    problem = agents.classify_llm_error(status_error(groq.RateLimitError, 429, TPD), "openai/gpt-oss-120b")
    assert problem.kind == "daily_quota"
    assert problem.retry_after == pytest.approx(29 * 60 + 1.824)
    assert "daily quota" in str(problem) and "about 29 min" in str(problem)


def test_per_minute_limit():
    problem = agents.classify_llm_error(status_error(groq.RateLimitError, 429, TPM), "m")
    assert problem.kind == "rate_limit" and problem.retry_after == 7.5
    assert "per-minute" in str(problem) and "about 8 s" in str(problem)


def test_retry_after_header_is_preferred_and_no_delay_is_ever_invented():
    with_header = status_error(groq.RateLimitError, 429, TPM, headers={"retry-after": "12"})
    assert agents.classify_llm_error(with_header, "m").retry_after == 12
    without_delay = agents.classify_llm_error(status_error(groq.RateLimitError, 429, "rate limit"), "m")
    assert without_delay.retry_after is None and str(without_delay).endswith("Try again later.")


def test_network_error():
    assert agents.classify_llm_error(groq.APIConnectionError(request=REQUEST), "m").kind == "network"
    assert agents.classify_llm_error(groq.APITimeoutError(request=REQUEST), "m").kind == "network"


@pytest.mark.parametrize("cls, status", [(groq.AuthenticationError, 401), (groq.PermissionDeniedError, 403),
                                         (groq.NotFoundError, 404)])
def test_configuration_errors(cls, status):
    assert agents.classify_llm_error(status_error(cls, status), "m").kind == "configuration"


def test_missing_api_key_is_a_configuration_error(monkeypatch):
    monkeypatch.setattr(config, "GROQ_API_KEY", "")
    agents.get_llm.cache_clear()
    with pytest.raises(agents.LLMUnavailable) as error:
        agents.get_llm("some-model", max_retries=0)
    agents.get_llm.cache_clear()
    assert error.value.kind == "configuration"


def test_server_error_is_temporary():
    assert agents.classify_llm_error(status_error(groq.InternalServerError, 503), "m").kind == "service"


def test_other_errors_are_not_classified():
    assert agents.classify_llm_error(status_error(groq.BadRequestError, 400), "m") is None
    assert agents.classify_llm_error(ValueError("x"), "m") is None


def test_messages_hide_internal_details():
    for error in (status_error(groq.RateLimitError, 429, TPD), status_error(groq.RateLimitError, 429, TPM),
                  groq.APIConnectionError(request=REQUEST), status_error(groq.AuthenticationError, 401, "bad key")):
        message = str(agents.classify_llm_error(error, "openai/gpt-oss-120b"))
        assert "org_" not in message and "Error code" not in message and "Traceback" not in message


# ---------------------------------------------------------------- retries

def test_daily_quota_stops_at_once_without_retrying():
    chain, waits = FakeChain(status_error(groq.RateLimitError, 429, TPD)), []
    with pytest.raises(agents.LLMUnavailable) as error:
        agents.call_llm(chain, {}, "m", sleep=waits.append)
    assert error.value.kind == "daily_quota" and chain.calls == 1 and waits == []


def test_configuration_error_stops_at_once():
    chain, waits = FakeChain(status_error(groq.AuthenticationError, 401)), []
    with pytest.raises(agents.LLMUnavailable):
        agents.call_llm(chain, {}, "m", sleep=waits.append)
    assert chain.calls == 1 and waits == []


def test_per_minute_limit_waits_the_groq_delay_then_succeeds():
    chain, waits = FakeChain(status_error(groq.RateLimitError, 429, TPM)), []
    assert agents.call_llm(chain, {}, "m", sleep=waits.append) == "answer"
    assert chain.calls == 2 and waits == [7.5]


def test_network_errors_are_retried_with_a_bounded_backoff():
    errors = [groq.APIConnectionError(request=REQUEST) for _ in range(agents.MAX_RETRIES + 1)]
    chain, waits = FakeChain(*errors), []
    with pytest.raises(agents.LLMUnavailable) as error:
        agents.call_llm(chain, {}, "m", sleep=waits.append)
    assert error.value.kind == "network"
    assert chain.calls == agents.MAX_RETRIES + 1
    assert waits == [1, 2, 4, 8, 8, 8, 8, 8]


def test_unknown_errors_are_raised_unchanged_without_retry():
    chain, waits = FakeChain(status_error(groq.BadRequestError, 400, "tool call validation failed")), []
    with pytest.raises(groq.BadRequestError):
        agents.call_llm(chain, {}, "m", sleep=waits.append)
    assert chain.calls == 1 and waits == []


# ---------------------------------------------------------------- model configuration

def models_in_subprocess(**env_vars) -> dict:
    env = {k: v for k, v in os.environ.items() if k not in ("LLM_MODEL", "ANALYZER_MODEL", "INVESTIGATOR_MODEL")}
    env.update(env_vars)
    code = ("import json; from incident_assistant import config; "
            "print(json.dumps([config.LLM_MODEL, config.ANALYZER_MODEL, config.INVESTIGATOR_MODEL]))")
    out = subprocess.run([sys.executable, "-c", code], env=env, cwd=config.ROOT_DIR,
                         capture_output=True, text=True, check=True).stdout
    return dict(zip(["llm", "analyzer", "investigator"], json.loads(out)))


def test_both_agents_default_to_the_historical_model():
    assert models_in_subprocess() == {"llm": "openai/gpt-oss-120b", "analyzer": "openai/gpt-oss-120b",
                                      "investigator": "openai/gpt-oss-120b"}


def test_agents_follow_llm_model_when_not_set():
    assert models_in_subprocess(LLM_MODEL="x/model")["analyzer"] == "x/model"
    assert models_in_subprocess(LLM_MODEL="x/model")["investigator"] == "x/model"


def test_agent_models_are_independent():
    models = models_in_subprocess(ANALYZER_MODEL="a/small", INVESTIGATOR_MODEL="b/large")
    assert models == {"llm": "openai/gpt-oss-120b", "analyzer": "a/small", "investigator": "b/large"}


def test_each_agent_calls_its_own_model(monkeypatch):
    monkeypatch.setattr(config, "ANALYZER_MODEL", "a/small")
    monkeypatch.setattr(config, "INVESTIGATOR_MODEL", "b/large")
    built, called = [], []

    class FakeLLM:
        def with_structured_output(self, schema):
            return lambda values: values

    monkeypatch.setattr(agents, "get_llm", lambda model, max_retries=8: built.append((model, max_retries)) or FakeLLM())
    monkeypatch.setattr(agents, "call_llm", lambda chain, values, model: called.append(model) or SimpleNamespace(queries=["q"]))
    analysis = agents.IncidentAnalysis(summary="s", technologies=[], symptoms=[], error_messages=[], recent_changes=[],
                                       search_queries=[], missing_information=[], needs_clarification=False,
                                       clarification_questions=[])
    agents.analyze_incident("incident")
    agents.rewrite_queries(analysis, ["old"])
    agents.investigate(analysis, [], evidence_insufficient=False)
    assert called == ["a/small", "a/small", "b/large"]
    assert built == [("a/small", 0), ("a/small", 0), ("b/large", 0)]   # agents retry themselves with call_llm


# ---------------------------------------------------------------- command line

def load_ask():
    spec = importlib.util.spec_from_file_location("ask", config.ROOT_DIR / "scripts" / "ask.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("error, expected", [
    (agents.LLMUnavailable("daily_quota", "The LLM service is temporarily unavailable."), "temporarily unavailable"),
    (RuntimeError("Storage folder storage/qdrant is already accessed"), "internal error"),
])
def test_ask_prints_a_clear_message_and_no_answer(monkeypatch, capsys, error, expected):
    ask = load_ask()

    def failing(incident, domains=None):
        raise error

    monkeypatch.setattr(ask, "run_investigation", failing)
    monkeypatch.setattr(sys, "argv", ["ask.py", "pod in CrashLoopBackOff"])
    with pytest.raises(SystemExit) as exit_info:
        ask.main()
    assert expected in str(exit_info.value.code) and "storage/qdrant" not in str(exit_info.value.code)
    assert "Possible causes" not in capsys.readouterr().out


# ---------------------------------------------------------------- benchmark: models are never mixed

def test_benchmark_refuses_another_model_for_v1_and_v2(monkeypatch):
    from evaluation import run_generation_benchmark as bench
    monkeypatch.setattr(config, "INVESTIGATOR_MODEL", "openai/gpt-oss-20b")
    for tag in ([], ["--tag", "v2"]):
        monkeypatch.setattr(sys, "argv", ["bench", *tag, "--answers-only"])
        with pytest.raises(SystemExit) as exit_info:
            bench.main()
        assert exit_info.value.code == 2   # argparse error, nothing is run or written


def test_new_answers_record_their_models_and_cached_ones_are_checked(monkeypatch, tmp_path):
    from evaluation import run_generation_benchmark as bench
    monkeypatch.setattr(bench, "CACHE", tmp_path)
    monkeypatch.setattr(bench, "run_investigation", lambda question: {"answer": {"status": "ok"}, "trace": []})
    record = bench.get_answer({"id": "x-001", "question": "q"})
    assert record["models"] == {"analyzer": config.ANALYZER_MODEL, "investigator": config.INVESTIGATOR_MODEL}
    monkeypatch.setattr(config, "INVESTIGATOR_MODEL", "another/model")
    with pytest.raises(SystemExit):
        bench.get_answer({"id": "x-001", "question": "q"})
