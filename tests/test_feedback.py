"""Interactions and user feedback (SQLite), the feedback controls of the Streamlit page and the
Dashboard page. The database is redirected to a temporary folder; no LLM and no index are used."""
import sqlite3

import pytest
from streamlit.testing.v1 import AppTest

from incident_assistant import config, feedback, workflow

APP = str(config.ROOT_DIR / "app" / "streamlit_app.py")
DASHBOARD = str(config.ROOT_DIR / "app" / "pages" / "1_Dashboard.py")


def make_answer(summary="Pod restarts in CrashLoopBackOff", status="ok"):
    return {
        "status": status, "rewrites": 0,
        "analysis": {"summary": summary, "technologies": ["kubernetes"], "error_messages": [],
                     "symptoms": [], "recent_changes": []},
        "missing_information": [], "confidence_note": "ok",
        "possible_causes": [{"cause": "Application error", "explanation": "exits", "evidence": ["S1"],
                             "status": "documented"}],
        "investigation_steps": [],
        "possible_solutions": [{"solution": "Fix the start command", "for_cause": "Application error",
                                "evidence": ["S1"]}],
        "references": [{"id": "S1", "doc_id": "md-k8s-crashloopbackoff"}],
        "passages": [{"id": "S1", "doc_id": "md-k8s-crashloopbackoff", "title": "CrashLoopBackOff", "page": None,
                      "section": "Overview", "source_path": "markdown/kubernetes/k8s-crashloopbackoff.md",
                      "text": "PASSAGE TEXT NOT STORED", "rerank_score": 4.2}],
    }


@pytest.fixture
def database(isolated_database):   # temporary database set up in conftest.py
    return isolated_database


def test_interaction_is_recorded_with_question_answer_documents_and_configuration(database):
    feedback.log_interaction("id-1", "pod in CrashLoopBackOff", make_answer(), 12.345, session_id="s1",
                             domains=["kubernetes"])
    [record] = feedback.load_interactions()
    assert record["question"] == "pod in CrashLoopBackOff" and record["status"] == "ok"
    assert record["technologies"] == ["kubernetes"] and record["causes"] == ["Application error"]
    assert record["solutions"] == ["Fix the start command"]
    assert record["cited_doc_ids"] == ["md-k8s-crashloopbackoff"] and record["n_passages"] == 1
    assert record["seconds"] == 12.35 and record["session_id"] == "s1"
    assert record["rag_config"]["collection"] == config.COLLECTION_NAME
    assert record["created_at"].endswith("+00:00") and record["rating"] is None
    with sqlite3.connect(database) as connection:   # no passage text in the database
        dump = "\n".join(connection.iterdump())
    assert "PASSAGE TEXT NOT STORED" not in dump


def test_detailed_feedback_is_linked_to_the_answer_and_a_new_vote_replaces_it():
    feedback.log_interaction("id-1", "q1", make_answer(), 1.0)
    feedback.log_interaction("id-2", "q2", make_answer(), 1.0)
    feedback.save_feedback("id-1", "up")
    feedback.save_feedback("id-2", "up")
    feedback.save_feedback("id-1", "down", diagnosis="incorrect", sources_relevant="no",
                           failed_solution="Fix the start command", correction="  restart the node  ", comment="no")
    records = {r["id"]: r for r in feedback.load_interactions()}
    assert records["id-1"]["rating"] == "down" and records["id-1"]["diagnosis"] == "incorrect"
    assert records["id-1"]["correction"] == "restart the node" and records["id-2"]["rating"] == "up"
    assert feedback.feedback_stats()["rated"] == 2


@pytest.mark.parametrize("arguments", [{"rating": "maybe"}, {"rating": "up", "diagnosis": "wrong"},
                                       {"rating": "up", "sources_relevant": "maybe"}])
def test_invalid_values_are_refused(arguments):
    feedback.log_interaction("id-1", "q", make_answer(), 1.0)
    with pytest.raises(ValueError):
        feedback.save_feedback("id-1", **arguments)
    assert feedback.feedback_stats()["rated"] == 0


def test_feedback_on_an_unknown_answer_is_refused():
    with pytest.raises(KeyError):
        feedback.save_feedback("missing", "up")


def test_statistics_and_evaluation_candidates():
    for number, status in enumerate(["ok", "ok", "insufficient_evidence", "needs_clarification"]):
        feedback.log_interaction(f"id-{number}", f"q{number}", make_answer(status=status), 2.0 * (number + 1),
                                 session_id="s1" if number < 2 else "s2")
    feedback.save_feedback("id-0", "up", diagnosis="correct", sources_relevant="yes")
    feedback.save_feedback("id-1", "down", diagnosis="partial", correction="use kubectl describe")
    feedback.save_feedback("id-2", "up")   # positive but not detailed: not a candidate
    stats = feedback.feedback_stats()
    assert (stats["questions"], stats["sessions"], stats["diagnostics"], stats["mean_seconds"]) == (4, 2, 3, 5.0)
    assert (stats["rated"], stats["up"], stats["down"], stats["up_rate"]) == (3, 2, 1, 0.67)
    assert stats["diagnosis"] == {"correct": 1, "partial": 1} and stats["down_by_status"] == {"ok": 1}
    candidates = {c["interaction_id"]: c for c in feedback.evaluation_candidates()}
    assert set(candidates) == {"id-0", "id-1"}
    assert candidates["id-0"]["kind"] == "confirmed" and candidates["id-1"]["kind"] == "to_fix"
    assert {c["review_status"] for c in candidates.values()} == {"to_review"}


def test_statistics_without_data():
    stats = feedback.feedback_stats()
    assert stats["questions"] == 0 and stats["rated"] == 0 and stats["up_rate"] is None
    assert feedback.load_interactions() == [] and feedback.evaluation_candidates() == []


def test_command_line_exports_candidates(tmp_path, capsys):
    feedback.log_interaction("id-1", "q1", make_answer(), 1.0)
    feedback.save_feedback("id-1", "down", diagnosis="incorrect")
    output = tmp_path / "candidates.jsonl"
    feedback.main(["--export-candidates", str(output)])
    assert '"kind": "to_fix"' in output.read_text(encoding="utf-8")
    assert "1 candidates written" in capsys.readouterr().out


# ---------------------------------------------------------------- Streamlit pages

def button(app, label):
    return next(b for b in app.button if b.label == label)


def run_app(monkeypatch):
    monkeypatch.setattr(workflow, "run_investigation",
                        lambda incident, domains=None: {"answer": make_answer(), "trace": ["done"]})
    return AppTest.from_file(APP, default_timeout=60).run()


def test_streamlit_buttons_record_one_vote_per_answer(monkeypatch):
    app = run_app(monkeypatch)
    app.text_area[0].input("pod in CrashLoopBackOff").run()
    button(app, "Investigate").click().run()
    app.text_area[0].input("text typed after the answer").run()   # must not be linked to the answer
    button(app, "👍 Useful").click().run()
    button(app, "👎 Not useful").click().run()
    assert not app.exception
    [record] = feedback.load_interactions()
    assert record["question"] == "pod in CrashLoopBackOff" and record["rating"] == "down"
    assert any("recorded as not useful" in c.value for c in app.caption)
    assert any("0 👍 / 1 👎" in c.value for c in app.sidebar.caption)

    app.text_area[0].input("docker ps permission denied").run()
    button(app, "Investigate").click().run()
    button(app, "👍 Useful").click().run()
    records = feedback.load_interactions()
    assert [r["question"] for r in records] == ["pod in CrashLoopBackOff", "docker ps permission denied"]
    assert records[0]["id"] != records[1]["id"] and records[0]["session_id"] == records[1]["session_id"]


def test_streamlit_detailed_feedback_form(monkeypatch):
    app = run_app(monkeypatch)
    app.text_area[0].input("pod in CrashLoopBackOff").run()
    button(app, "Investigate").click().run()
    next(r for r in app.radio if r.label == "Overall").set_value("👎 Not useful")
    next(r for r in app.radio if r.label == "Is the diagnosis correct?").set_value("Partially correct")
    next(r for r in app.radio if r.label == "Are the sources relevant?").set_value("Not relevant")
    app.selectbox[0].set_value("Fix the start command")
    next(t for t in app.text_area if t.label.startswith("Correction")).input("the node was out of memory")
    button(app, "Send feedback").click().run()
    assert not app.exception
    [record] = feedback.load_interactions()
    assert (record["rating"], record["diagnosis"], record["sources_relevant"]) == ("down", "partial", "no")
    assert record["failed_solution"] == "Fix the start command"
    assert record["correction"] == "the node was out of memory"


def test_dashboard_without_data_explains_what_is_missing():
    app = AppTest.from_file(DASHBOARD, default_timeout=60).run()
    assert not app.exception
    assert any("No interaction recorded yet" in i.value for i in app.info)
    assert any("No answer rated yet" in i.value for i in app.info)


def test_dashboard_shows_the_recorded_data():
    feedback.log_interaction("id-1", "q1", make_answer(), 3.0, session_id="s1")
    feedback.log_interaction("id-2", "q2", make_answer(status="insufficient_evidence"), 5.0, session_id="s2")
    feedback.save_feedback("id-1", "up", diagnosis="correct", sources_relevant="yes")
    feedback.save_feedback("id-2", "down", diagnosis="incorrect", comment="wrong cause")
    app = AppTest.from_file(DASHBOARD, default_timeout=60).run()
    assert not app.exception
    metrics = {m.label: m.value for m in app.metric}
    assert metrics["Questions"] == "2" and metrics["Sessions"] == "2" and metrics["Mean response time"] == "4.0 s"
    assert metrics["Rated answers"] == "2" and metrics["Positive feedback"] == "50%"
    assert any("wrong cause" in str(d.value.to_dict()) for d in app.dataframe)   # table of negative feedback
