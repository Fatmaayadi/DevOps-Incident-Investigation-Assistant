"""The Streamlit page is executed with Streamlit's AppTest. The workflow is replaced by a recorded
answer (from the generation benchmark cache) so the test needs neither the LLM nor the index."""
import json

import pytest
from streamlit.testing.v1 import AppTest

from incident_assistant import config, workflow

RECORDED = config.ROOT_DIR / "evaluation" / "results" / "generation" / "k8s-007_answer.json"
APP = str(config.ROOT_DIR / "app" / "streamlit_app.py")


def investigate_button(app):
    return next(b for b in app.button if b.label == "Investigate")


def recorded_state():
    record = json.loads(RECORDED.read_text(encoding="utf-8"))
    return {"answer": record["answer"], "trace": record["trace"]}


@pytest.mark.skipif(not RECORDED.exists(), reason="no recorded answer (run the generation benchmark first)")
def test_page_shows_analysis_causes_steps_and_sources(monkeypatch):
    monkeypatch.setattr(workflow, "run_investigation", lambda incident, domains=None: recorded_state())
    app = AppTest.from_file(APP, default_timeout=60).run()
    app.text_area[0].input("Service returns connection refused, endpointslices show no endpoints").run()
    investigate_button(app).click().run()
    assert not app.exception
    assert [tab.label for tab in app.tabs] == ["Analysis", "Possible causes", "Investigation", "Sources", "Trace"]
    page_text = " ".join(m.value for m in app.markdown)
    assert "documented" in page_text or "hypothesis" in page_text
    assert len(app.expander) == len(recorded_state()["answer"]["passages"])   # one expander per source passage


def test_clarification_questions_are_displayed(monkeypatch):
    state = {"answer": {"status": "needs_clarification", "analysis": {},
                        "questions": ["Which technology is involved?"]}, "trace": []}
    monkeypatch.setattr(workflow, "run_investigation", lambda incident, domains=None: state)
    app = AppTest.from_file(APP, default_timeout=60).run()
    app.text_area[0].input("my app is broken").run()
    investigate_button(app).click().run()
    assert not app.exception
    assert any("Which technology is involved?" in m.value for m in app.markdown)


def failing_investigation(error):
    def run(incident, domains=None):
        raise error
    return run


def test_llm_unavailable_shows_a_clear_message_and_no_answer(monkeypatch):
    from incident_assistant.agents import LLMUnavailable
    message = "The LLM service is temporarily unavailable: the daily quota of model m is used up. Try again in about 29 min."
    monkeypatch.setattr(workflow, "run_investigation", failing_investigation(LLMUnavailable("daily_quota", message, 1741)))
    app = AppTest.from_file(APP, default_timeout=60).run()
    app.text_area[0].input("pod in CrashLoopBackOff").run()
    investigate_button(app).click().run()
    assert not app.exception
    assert any("about 29 min" in w.value for w in app.warning)
    assert not app.tabs and not app.error   # no (incomplete) answer is displayed


def test_internal_error_hides_technical_details(monkeypatch):
    error = RuntimeError("Error code: 400 - {'error': {'message': 'Tool call validation failed', 'org': 'org_123'}}")
    monkeypatch.setattr(workflow, "run_investigation", failing_investigation(error))
    app = AppTest.from_file(APP, default_timeout=60).run()
    app.text_area[0].input("pod in CrashLoopBackOff").run()
    investigate_button(app).click().run()
    assert not app.exception and not app.tabs
    shown = " ".join(e.value for e in app.error)
    assert "internal error" in shown and "org_" not in shown and "Error code" not in shown
