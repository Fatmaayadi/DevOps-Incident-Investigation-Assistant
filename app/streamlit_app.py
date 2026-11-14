"""Web interface of the DevOps Incident Investigation Assistant.

Run: streamlit run app/streamlit_app.py   (the Dashboard page is in app/pages/)
"""
import logging
import sqlite3
import time
import uuid

import streamlit as st

from incident_assistant import feedback
from incident_assistant.agents import LLMUnavailable
from incident_assistant.workflow import run_investigation

DOMAINS = ["kubernetes", "docker", "networking", "linux", "git", "github", "gitlab",
           "terraform", "ansible", "aws", "sre"]
EXAMPLES = [
    "After deploying version 2.4 our pods restart in a loop and kubectl shows CrashLoopBackOff.",
    "Our nginx reverse proxy returns 502 Bad Gateway for /api since the last deployment.",
    "terraform apply fails because it cannot acquire the state lock; yesterday's pipeline was cancelled.",
    "On a fresh Ubuntu server docker ps gives permission denied on /var/run/docker.sock without sudo.",
    "my app is broken",
]
DIAGNOSIS_CHOICES = {"Not evaluated": None, "Correct": "correct", "Partially correct": "partial",
                     "Incorrect": "incorrect"}
SOURCE_CHOICES = {"Not evaluated": None, "Relevant": "yes", "Partly relevant": "partly", "Not relevant": "no"}
STORAGE_ERRORS = (OSError, sqlite3.Error, KeyError)   # the answer stays usable if the database is not


def sources(ids: list[str]) -> str:
    return " ".join(f"[{i}]" for i in ids) or "*(not sourced)*"


def record_feedback(answer_id: str, rating: str, **details):
    try:
        feedback.save_feedback(answer_id, rating, **details)
        st.session_state.feedback_rating = (answer_id, rating)
        st.rerun()   # refresh the statistics of the sidebar
    except STORAGE_ERRORS:
        logging.exception("feedback not saved")
        st.warning("Your feedback could not be saved.")


st.set_page_config(page_title="DevOps Incident Assistant", layout="wide")
st.title("DevOps Incident Investigation Assistant")
st.warning("The assistant has no access to your systems. It proposes causes and checks based on its "
           "documentation; every conclusion must be verified on your environment.")

if "incident" not in st.session_state:
    st.session_state.incident = ""
if "session_id" not in st.session_state:   # one id per browser session, for the usage statistics
    st.session_state.session_id = uuid.uuid4().hex

with st.sidebar:
    st.header("Examples")
    for example in EXAMPLES:
        if st.button(example[:60] + ("..." if len(example) > 60 else ""), use_container_width=True):
            st.session_state.incident = example
    st.header("Filter")
    domains = st.multiselect("Search only in these domains (optional)", DOMAINS)
    st.header("Feedback")
    try:
        stats = feedback.feedback_stats()
    except STORAGE_ERRORS:
        stats = {"rated": 0}
    if stats["rated"]:
        st.caption(f"{stats['up']} 👍 / {stats['down']} 👎 ({stats['rated']} rated answers). "
                   "Details on the Dashboard page.")
    else:
        st.caption("No answer rated yet.")

incident = st.text_area("Describe the incident (English works best)", key="incident", height=120)

if st.button("Investigate", type="primary") and incident.strip():
    with st.spinner("Analysing the incident and searching the documentation..."):
        # On any error no answer is kept: an incomplete investigation is never displayed.
        try:
            start = time.perf_counter()
            st.session_state.result = run_investigation(incident, domains=domains)
            seconds = time.perf_counter() - start
            # The feedback is linked to this answer and to the question really asked,
            # even if the text area is edited afterwards.
            st.session_state.answer_id = uuid.uuid4().hex
            st.session_state.asked_incident = incident
            try:   # usage log for the dashboard; a storage problem must not hide the answer
                feedback.log_interaction(st.session_state.answer_id, incident, st.session_state.result["answer"],
                                         seconds, session_id=st.session_state.session_id, domains=domains)
            except STORAGE_ERRORS:
                logging.exception("interaction not recorded")
        except LLMUnavailable as error:   # quota, network or configuration: the message is user-friendly
            st.session_state.result = None
            st.warning(f"No answer was produced. {error}")
        except Exception:   # e.g. index not built, Qdrant used by another process, invalid model output
            st.session_state.result = None
            logging.exception("investigation failed")   # details only in the server terminal
            st.error("The investigation could not be completed because of an internal error, so no answer is shown. "
                     "Check that the index is built and that no other process uses Qdrant, then try again.")

state = st.session_state.get("result")
if state:
    answer = state["answer"]
    analysis = answer["analysis"]

    if answer["status"] == "needs_clarification":
        st.info("The description is too vague to search the documentation. Please answer these questions:")
        for question in answer["questions"]:
            st.markdown(f"- {question}")
        st.stop()

    if answer["status"] == "insufficient_evidence":
        st.error("The knowledge base does not contain enough relevant information for this incident. "
                 "The causes below are hypotheses, not documented facts.")

    tab_analysis, tab_causes, tab_steps, tab_sources, tab_trace = st.tabs(
        ["Analysis", "Possible causes", "Investigation", "Sources", "Trace"])

    with tab_analysis:
        st.subheader(analysis["summary"])
        col1, col2 = st.columns(2)
        col1.markdown("**Technologies:** " + (", ".join(analysis["technologies"]) or "-"))
        col1.markdown("**Error messages:** " + (", ".join(f"`{e}`" for e in analysis["error_messages"]) or "-"))
        col2.markdown("**Symptoms:** " + ("; ".join(analysis["symptoms"]) or "-"))
        col2.markdown("**Recent changes:** " + ("; ".join(analysis["recent_changes"]) or "-"))
        st.markdown("**Information to collect:** " + ("; ".join(answer["missing_information"]) or "-"))
        st.caption(answer["confidence_note"])

    with tab_causes:
        for cause in answer["possible_causes"]:
            label = "documented" if cause["status"] == "documented" else "hypothesis (not supported by a source)"
            st.markdown(f"**{cause['cause']}** - *{label}* {sources(cause['evidence'])}")
            st.write(cause["explanation"])

    with tab_steps:
        for number, step in enumerate(answer["investigation_steps"], start=1):
            st.markdown(f"**{number}. {step['action']}** {sources(step['evidence'])}")
            if step["command"]:
                st.code(step["command"], language="bash")
            st.write(step["interpretation"])
        st.markdown("#### Possible solutions")
        for solution in answer["possible_solutions"]:
            st.markdown(f"- {solution['solution']} *(cause: {solution['for_cause']})* "
                        f"{sources(solution['evidence'])}")

    with tab_sources:
        cited = {ref["id"] for ref in answer["references"]}
        st.markdown("Passages given to the investigation agent (cited ones first). Page numbers are PDF page numbers.")
        for passage in sorted(answer["passages"], key=lambda p: p["id"] not in cited):
            location = f"PDF p. {passage['page']}" if passage["page"] else f"section {passage['section']}"
            title = f"[{passage['id']}] {passage['title']} - {location}" + ("  (cited)" if passage["id"] in cited else "")
            with st.expander(title):
                caption = f"{passage['source_path']} | reranker score {passage.get('rerank_score', 0):.2f}"
                if "rrf_rank" in passage:   # only when the reranker chose the passages
                    caption += f" | rank before reranking {passage['rrf_rank']}"
                st.caption(caption)
                st.text(passage["text"])

    with tab_trace:
        for line in state["trace"]:
            st.markdown(f"- {line}")

    answer_id = st.session_state.answer_id
    st.markdown("**Was this answer useful?**")
    col_useful, col_not_useful, _ = st.columns([1, 1, 4])
    if col_useful.button("👍 Useful", key=f"useful_{answer_id}"):
        record_feedback(answer_id, "up")
    if col_not_useful.button("👎 Not useful", key=f"not_useful_{answer_id}"):
        record_feedback(answer_id, "down")

    with st.expander("Detailed feedback (optional)"):
        with st.form(key=f"feedback_form_{answer_id}"):
            rating = st.radio("Overall", ["👍 Useful", "👎 Not useful"], horizontal=True)
            diagnosis = st.radio("Is the diagnosis correct?", list(DIAGNOSIS_CHOICES), horizontal=True)
            relevance = st.radio("Are the sources relevant?", list(SOURCE_CHOICES), horizontal=True)
            solutions = [s["solution"] for s in answer["possible_solutions"]]
            failed = st.selectbox("A proposed solution that did not work", ["None"] + solutions)
            correction = st.text_area("Correction: what really solved the incident?")
            comment = st.text_area("Comment")
            if st.form_submit_button("Send feedback"):
                record_feedback(answer_id, "up" if rating.startswith("👍") else "down",
                                diagnosis=DIAGNOSIS_CHOICES[diagnosis], sources_relevant=SOURCE_CHOICES[relevance],
                                failed_solution=None if failed == "None" else failed,
                                correction=correction, comment=comment)

    if st.session_state.get("feedback_rating", (None, None))[0] == answer_id:
        label = "useful" if st.session_state.feedback_rating[1] == "up" else "not useful"
        st.caption(f"Thank you: this answer is recorded as {label}. You can still change your evaluation.")
