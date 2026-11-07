"""Web interface of the DevOps Incident Investigation Assistant.

Run: streamlit run app/streamlit_app.py
"""
import logging

import streamlit as st

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



def sources(ids: list[str]) -> str:
    return " ".join(f"[{i}]" for i in ids) or "*(not sourced)*"


st.set_page_config(page_title="DevOps Incident Assistant", layout="wide")
st.title("DevOps Incident Investigation Assistant")
st.warning("The assistant has no access to your systems. It proposes causes and checks based on its "
           "documentation; every conclusion must be verified on your environment.")

if "incident" not in st.session_state:
    st.session_state.incident = ""

with st.sidebar:
    st.header("Examples")
    for example in EXAMPLES:
        if st.button(example[:60] + ("..." if len(example) > 60 else ""), use_container_width=True):
            st.session_state.incident = example
    st.header("Filter")
    domains = st.multiselect("Search only in these domains (optional)", DOMAINS)

incident = st.text_area("Describe the incident (English works best)", key="incident", height=120)

if st.button("Investigate", type="primary") and incident.strip():
    with st.spinner("Analysing the incident and searching the documentation..."):
        # On any error no answer is kept: an incomplete investigation is never displayed.
        try:
            st.session_state.result = run_investigation(incident, domains=domains)
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
                st.caption(f"{passage['source_path']} | reranker score {passage.get('rerank_score', 0):.2f}")
                st.text(passage["text"])

    with tab_trace:
        for line in state["trace"]:
            st.markdown(f"- {line}")
