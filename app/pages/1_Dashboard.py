"""Dashboard: usage, user feedback, retrieval and generation results, incident analysis.

Every number is computed from real data:
  - the interactions and feedback recorded by the interface (storage/assistant.db);
  - the benchmark result files written by the evaluation scripts (evaluation/results/*.json).
Nothing is invented: when a source has no data yet, the section says so.
"""
import json
from collections import Counter

import pandas as pd
import streamlit as st

from incident_assistant import config, feedback

RESULTS = config.ROOT_DIR / "evaluation" / "results"
STRATEGIES = {"bm25": "BM25", "semantic": "Dense (semantic)", "hybrid": "Hybrid (RRF)",
              "hybrid_rerank": "Hybrid + reranking"}
GENERATION_METRICS = ["correctness", "faithfulness", "answer_relevancy", "context_recall", "citation_validity"]


def counts(values: list, label: str) -> pd.DataFrame:
    """Frequency table, most frequent first."""
    return pd.DataFrame(Counter(values).most_common(), columns=[label, "count"]).set_index(label)


def benchmark_files(pattern: str) -> dict[str, dict]:
    return {path.stem: json.loads(path.read_text(encoding="utf-8")) for path in sorted(RESULTS.glob(pattern))}


st.set_page_config(page_title="Dashboard - DevOps Incident Assistant", layout="wide")
st.title("Dashboard")
st.caption("Usage and feedback come from the interactions recorded by this application; retrieval and "
           "generation quality come from the benchmark result files. No value is simulated.")

try:
    records = feedback.load_interactions()
except Exception:   # damaged or locked database: the benchmark sections stay available
    records = []
    st.warning("The interaction database could not be read.")

data = pd.DataFrame(records)
if not data.empty:
    data["created_at"] = pd.to_datetime(data["created_at"])
    data["day"] = data["created_at"].dt.date
    with st.sidebar:
        st.header("Filters")
        first, last = data["day"].min(), data["day"].max()
        period = st.date_input("Period", (first, last), min_value=first, max_value=last)
        technologies = sorted({t for ts in data["technologies"] for t in ts})
        chosen = st.multiselect("Technologies", technologies)
    if isinstance(period, tuple) and len(period) == 2:
        data = data[(data["day"] >= period[0]) & (data["day"] <= period[1])]
    if chosen:
        data = data[data["technologies"].apply(lambda ts: bool(set(ts) & set(chosen)))]

# ------------------------------------------------------------------ A. usage
st.header("A. Usage of the assistant")
if data.empty:
    st.info("No interaction recorded yet: ask a question on the main page to fill this section.")
else:
    stats = feedback.feedback_stats(data.to_dict("records"))
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Questions", stats["questions"])
    col2.metric("Sessions", stats["sessions"])
    col3.metric("Diagnostics generated", stats["diagnostics"])
    col4.metric("Mean response time", f"{stats['mean_seconds']} s" if stats["mean_seconds"] is not None else "-")
    st.subheader("Questions per day")
    st.bar_chart(data.groupby("day").size().rename("questions"))
    st.subheader("Answer status")
    st.bar_chart(counts(list(data["status"]), "status"))

# ------------------------------------------------------------------ B. quality (user feedback)
st.header("B. Quality of the answers (user feedback)")
rated = data[data["rating"].notna()] if not data.empty else data
if rated.empty:
    st.info("No answer rated yet: use the 👍 / 👎 buttons or the detailed feedback under an answer.")
else:
    stats = feedback.feedback_stats(data.to_dict("records"))
    col1, col2, col3 = st.columns(3)
    col1.metric("Rated answers", stats["rated"])
    col2.metric("Positive feedback", f"{stats['up_rate']:.0%}")
    col3.metric("Negative feedback", f"{1 - stats['up_rate']:.0%}")
    col_diag, col_src = st.columns(2)
    with col_diag:
        st.subheader("Diagnosis")
        if stats["diagnosis"]:
            st.bar_chart(pd.Series(stats["diagnosis"], name="answers"))
        else:
            st.caption("No detailed evaluation of the diagnosis yet.")
    with col_src:
        st.subheader("Relevance of the sources")
        if stats["sources_relevant"]:
            st.bar_chart(pd.Series(stats["sources_relevant"], name="answers"))
        else:
            st.caption("No evaluation of the sources yet.")
    st.subheader("Satisfaction over time (share of 👍 per day)")
    st.line_chart(rated.assign(up=rated["rating"].eq("up")).groupby("day")["up"].mean().rename("positive share"))
    st.subheader("Answers with a negative evaluation")
    negative = rated[rated["rating"].eq("down") | rated["diagnosis"].isin(["partial", "incorrect"])]
    if negative.empty:
        st.caption("None.")
    else:
        st.dataframe(negative[["created_at", "question", "status", "diagnosis", "sources_relevant",
                               "failed_solution", "correction", "comment"]], hide_index=True)
    st.caption(f"{len(feedback.evaluation_candidates(data.to_dict('records')))} rated answers are candidates for the "
               "evaluation dataset (`python -m incident_assistant.feedback --export-candidates FILE`). "
               "They must be reviewed by a person before any use.")

# ------------------------------------------------------------------ C. retrieval and generation (benchmarks)
st.header("C. Retrieval and generation performance (benchmarks)")
retrieval = benchmark_files("retrieval_summary_*.json")
if not retrieval:
    st.info("No retrieval benchmark result yet: run `python -m evaluation.run_retrieval_benchmark`.")
else:
    name = st.selectbox("Retrieval benchmark", list(retrieval), format_func=lambda n: n.removeprefix("retrieval_summary_"))
    summary = retrieval[name]
    st.caption(f"Run on {summary.get('date', '?')} - collection `{summary.get('collection', '?')}`, "
               f"embeddings `{summary.get('embedding_model', '?')}`, reranker `{summary.get('reranker', '?')}`. "
               "Relevance at document level (recall@k, MRR); evidence level when the dataset provides it.")
    rows = pd.DataFrame(summary["results"])
    rows["configuration"] = rows["setting"] + " / " + rows["strategy"].map(STRATEGIES).fillna(rows["strategy"])
    columns = [c for c in ["recall@1", "recall@5", "recall@10", "mrr", "evidence_recall@5", "evidence_recall@10",
                           "evidence_mrr", "seconds_per_query"] if c in rows]
    st.dataframe(rows.set_index("configuration")[columns], width="stretch")
    st.bar_chart(rows.set_index("configuration")[[c for c in ("recall@5", "mrr") if c in rows]])
    for setting in rows["setting"].unique():
        by_strategy = rows[rows["setting"] == setting].set_index("strategy")
        if {"hybrid", "hybrid_rerank"} <= set(by_strategy.index):
            delta = by_strategy.loc["hybrid_rerank", "mrr"] - by_strategy.loc["hybrid", "mrr"]
            st.markdown(f"**Impact of reranking** ({setting} queries): MRR {by_strategy.loc['hybrid', 'mrr']:.3f} → "
                        f"{by_strategy.loc['hybrid_rerank', 'mrr']:.3f} ({delta:+.3f}).")
if not data.empty:
    st.markdown(f"**Mean number of passages given to the agent** (recorded interactions): {data['n_passages'].mean():.1f}")

generation = benchmark_files("generation_summary*.json")
if generation:
    st.subheader("Generation quality (LLM judge, benchmark runs)")
    table = pd.DataFrame({name.removeprefix("generation_summary").strip("_") or "v1":
                          {**{m: run[m]["mean"] for m in GENERATION_METRICS if isinstance(run.get(m), dict)},
                           "questions": run.get("questions_scored"), "mean s / question": run.get("mean_seconds_per_question"),
                           "date": run.get("date")} for name, run in generation.items()}).T
    st.dataframe(table, width="stretch")
    st.caption("Faithfulness, answer relevancy and correctness are judged by an LLM; see evaluation/results/README.md.")

# ------------------------------------------------------------------ D. incidents
st.header("D. Incident analysis")
if data.empty:
    st.info("No interaction recorded yet.")
else:
    col_tech, col_docs = st.columns(2)
    with col_tech:
        st.subheader("Technologies concerned")
        technologies = [t for ts in data["technologies"] for t in ts]
        if technologies:
            st.bar_chart(counts(technologies, "technology"))
        else:
            st.caption("None detected.")
    with col_docs:
        st.subheader("Most cited documents")
        documents = [d for ds in data["cited_doc_ids"] for d in ds]
        if documents:
            st.bar_chart(counts(documents, "document").head(10))
        else:
            st.caption("No document cited.")
    col_causes, col_solutions = st.columns(2)
    with col_causes:
        st.subheader("Most frequent proposed causes")
        st.dataframe(counts([c for cs in data["causes"] for c in cs], "cause").head(10), width="stretch")
    with col_solutions:
        st.subheader("Most frequent proposed solutions")
        st.dataframe(counts([s for ss in data["solutions"] for s in ss], "solution").head(10), width="stretch")
