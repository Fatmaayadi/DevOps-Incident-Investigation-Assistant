"""Interactions and user feedback, stored in a local SQLite database (storage/assistant.db).

Two tables:
  - interactions: one row per answer produced by the assistant (question, status, technologies,
    causes, solutions, cited documents, response time, RAG configuration). Filled automatically.
  - feedback: at most one row per interaction (a new vote replaces the previous one): thumbs
    up / down, diagnosis correct / partial / incorrect, relevance of the sources, comment,
    solution that did not work and proposed correction.

The passage texts, the trace and the API key are never stored.
SQLite is part of the Python standard library: no server and no extra dependency.

Statistics:             python -m incident_assistant.feedback
Evaluation candidates:  python -m incident_assistant.feedback --export-candidates candidates.jsonl
"""
import argparse
import json
import sqlite3
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from incident_assistant import config

RATINGS = ("up", "down")
DIAGNOSES = ("correct", "partial", "incorrect")
SOURCE_RELEVANCE = ("yes", "partly", "no")

SCHEMA = """
CREATE TABLE IF NOT EXISTS interactions (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    session_id TEXT,
    question TEXT NOT NULL,
    domains TEXT,            -- JSON list: domain filter chosen in the interface
    status TEXT NOT NULL,    -- ok | insufficient_evidence | needs_clarification
    summary TEXT,
    technologies TEXT,       -- JSON list (from the Incident Analyzer)
    causes TEXT,             -- JSON list of proposed causes
    solutions TEXT,          -- JSON list of proposed solutions
    cited_doc_ids TEXT,      -- JSON list
    passage_doc_ids TEXT,    -- JSON list: documents of the passages given to the agent
    n_passages INTEGER,
    rewrites INTEGER,
    seconds REAL,
    rag_config TEXT          -- JSON object: models, collection, reranking, evidence rule
);
CREATE TABLE IF NOT EXISTS feedback (
    interaction_id TEXT PRIMARY KEY REFERENCES interactions(id),
    created_at TEXT NOT NULL,
    rating TEXT NOT NULL CHECK (rating IN ('up', 'down')),
    diagnosis TEXT CHECK (diagnosis IN ('correct', 'partial', 'incorrect')),
    sources_relevant TEXT CHECK (sources_relevant IN ('yes', 'partly', 'no')),
    comment TEXT,
    failed_solution TEXT,
    correction TEXT
);
"""
JSON_COLUMNS = ("domains", "technologies", "causes", "solutions", "cited_doc_ids", "passage_doc_ids", "rag_config")


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def database():
    """Open the database (created on first use), commit on success, and always close it."""
    config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(config.DB_PATH)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(SCHEMA)
        with connection:   # one transaction: committed, or rolled back on error
            yield connection
    finally:
        connection.close()


def rag_config() -> dict:
    """The settings that define the answer, so that feedback can be compared between configurations."""
    return {"analyzer_model": config.ANALYZER_MODEL, "investigator_model": config.INVESTIGATOR_MODEL,
            "collection": config.COLLECTION_NAME, "embedding_model": config.EMBEDDING_MODEL,
            "rerank_passages": config.RERANK_PASSAGES, "final_passages": config.FINAL_PASSAGES,
            "evidence_rule": f">= {config.EVIDENCE_MIN_PASSAGES} passages >= {config.EVIDENCE_MIN_SCORE}"}


def log_interaction(interaction_id: str, question: str, answer: dict, seconds: float,
                    session_id: str | None = None, domains: list[str] | None = None) -> None:
    """Record an answer of the workflow (called by the interface after each investigation)."""
    analysis = answer.get("analysis") or {}
    passages = answer.get("passages", [])
    row = {
        "id": interaction_id, "created_at": now(), "session_id": session_id, "question": question,
        "domains": domains or [], "status": answer["status"], "summary": analysis.get("summary", ""),
        "technologies": analysis.get("technologies", []),
        "causes": [c["cause"] for c in answer.get("possible_causes", [])],
        "solutions": [s["solution"] for s in answer.get("possible_solutions", [])],
        "cited_doc_ids": sorted({r["doc_id"] for r in answer.get("references", [])}),
        "passage_doc_ids": [p["doc_id"] for p in passages],
        "n_passages": len(passages), "rewrites": answer.get("rewrites"), "seconds": round(seconds, 2),
        "rag_config": rag_config(),
    }
    values = {k: json.dumps(v, ensure_ascii=False) if k in JSON_COLUMNS else v for k, v in row.items()}
    with database() as connection:
        connection.execute(f"INSERT OR REPLACE INTO interactions ({', '.join(values)}) "
                           f"VALUES ({', '.join('?' * len(values))})", list(values.values()))


def save_feedback(interaction_id: str, rating: str, diagnosis: str | None = None,
                  sources_relevant: str | None = None, comment: str = "", failed_solution: str | None = None,
                  correction: str = "") -> dict:
    """Store the user's evaluation of an answer. A new evaluation of the same answer replaces the previous one."""
    for value, allowed, name in ((rating, RATINGS, "rating"), (diagnosis, DIAGNOSES + (None,), "diagnosis"),
                                 (sources_relevant, SOURCE_RELEVANCE + (None,), "sources_relevant")):
        if value not in allowed:
            raise ValueError(f"{name} must be one of {allowed}")
    record = {"interaction_id": interaction_id, "created_at": now(), "rating": rating, "diagnosis": diagnosis,
              "sources_relevant": sources_relevant, "comment": comment.strip(),
              "failed_solution": failed_solution or None, "correction": correction.strip()}
    with database() as connection:
        if not connection.execute("SELECT 1 FROM interactions WHERE id = ?", (interaction_id,)).fetchone():
            raise KeyError(f"unknown interaction {interaction_id}")
        connection.execute(f"INSERT OR REPLACE INTO feedback ({', '.join(record)}) "
                           f"VALUES ({', '.join('?' * len(record))})", list(record.values()))
    return record


def load_interactions() -> list[dict]:
    """All interactions, each with its feedback (None when the answer was not rated)."""
    if not config.DB_PATH.exists():
        return []
    with database() as connection:
        rows = connection.execute(
            "SELECT i.*, f.created_at AS feedback_at, f.rating, f.diagnosis, f.sources_relevant, f.comment, "
            "f.failed_solution, f.correction FROM interactions i LEFT JOIN feedback f ON f.interaction_id = i.id "
            "ORDER BY i.created_at").fetchall()
    records = []
    for row in rows:
        record = dict(row)
        for column in JSON_COLUMNS:
            record[column] = json.loads(record[column]) if record[column] else ([] if column != "rag_config" else {})
        records.append(record)
    return records


def feedback_stats(records: list[dict] | None = None) -> dict:
    records = load_interactions() if records is None else records
    rated = [r for r in records if r["rating"]]
    up = sum(r["rating"] == "up" for r in rated)
    seconds = [r["seconds"] for r in records if r["seconds"] is not None]
    return {
        "questions": len(records),
        "sessions": len({r["session_id"] for r in records if r["session_id"]}),
        "diagnostics": sum(r["status"] in ("ok", "insufficient_evidence") for r in records),
        "mean_seconds": round(sum(seconds) / len(seconds), 1) if seconds else None,
        "rated": len(rated),
        "up": up,
        "down": len(rated) - up,
        "up_rate": round(up / len(rated), 2) if rated else None,
        "diagnosis": dict(Counter(r["diagnosis"] for r in rated if r["diagnosis"])),
        "sources_relevant": dict(Counter(r["sources_relevant"] for r in rated if r["sources_relevant"])),
        "down_by_status": dict(Counter(r["status"] for r in rated if r["rating"] == "down")),
    }


def evaluation_candidates(records: list[dict] | None = None) -> list[dict]:
    """Rated answers that could enrich the evaluation dataset, AFTER a human review.

    - "confirmed": diagnosis judged correct and sources relevant: the question and its cited documents
      are a candidate (question, expected documents) pair for the retrieval benchmark;
    - "to_fix": negative vote or diagnosis judged partial / incorrect: a candidate hard case, with the
      user's correction if any.
    Nothing is used automatically: every candidate keeps review_status = "to_review"."""
    records = load_interactions() if records is None else records
    candidates = []
    for r in records:
        if not r["rating"]:
            continue
        if r["rating"] == "up" and r["diagnosis"] == "correct" and r["sources_relevant"] == "yes":
            kind = "confirmed"
        elif r["rating"] == "down" or r["diagnosis"] in ("partial", "incorrect"):
            kind = "to_fix"
        else:
            continue
        candidates.append({"interaction_id": r["id"], "kind": kind, "question": r["question"],
                           "technologies": r["technologies"], "status": r["status"], "causes": r["causes"],
                           "cited_doc_ids": r["cited_doc_ids"], "diagnosis": r["diagnosis"],
                           "sources_relevant": r["sources_relevant"], "comment": r["comment"],
                           "failed_solution": r["failed_solution"], "correction": r["correction"],
                           "review_status": "to_review"})
    return candidates


def main(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(description="Usage and feedback statistics of the assistant.")
    parser.add_argument("--export-candidates", type=Path, help="write the evaluation candidates to this JSONL file")
    args = parser.parse_args(argv)
    stats = feedback_stats()
    if not stats["questions"]:
        print(f"No interaction recorded yet ({config.DB_PATH}).")
        return
    print(f"Questions: {stats['questions']}  sessions: {stats['sessions']}  mean time: {stats['mean_seconds']} s")
    if stats["rated"]:
        print(f"Rated answers: {stats['rated']}  up: {stats['up']} ({stats['up_rate']:.0%})  down: {stats['down']}")
        print(f"Diagnosis: {stats['diagnosis']}  sources relevant: {stats['sources_relevant']}")
    else:
        print("No answer rated yet.")
    if args.export_candidates:
        candidates = evaluation_candidates()
        args.export_candidates.write_text("".join(json.dumps(c, ensure_ascii=False) + "\n" for c in candidates),
                                          encoding="utf-8")
        print(f"{len(candidates)} candidates written to {args.export_candidates} (to review before any use).")


if __name__ == "__main__":
    main()
