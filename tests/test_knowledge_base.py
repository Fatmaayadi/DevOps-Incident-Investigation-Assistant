"""Consistency of the knowledge base and separation from the evaluation dataset."""
import json
import re

import pytest
import yaml

from incident_assistant import config
from incident_assistant.documents import list_source_files, read_markdown

REQUIRED_FIELDS = ["doc_id", "title", "domain", "technology", "category", "document_type",
                   "difficulty", "keywords", "source_type", "references"]
SECTIONS = ["Overview", "Symptoms", "Possible Causes", "Investigation Steps", "Diagnostic Commands",
            "Interpretation of Results", "Possible Solutions", "Prevention", "Related Concepts",
            "References", "Metadata"]
GUIDES = sorted((config.KNOWLEDGE_BASE_DIR / "markdown").rglob("*.md"))
EVAL_PATH = config.ROOT_DIR / "evaluation" / "datasets" / "incidents_eval.json"


def all_doc_ids():
    manifest = yaml.safe_load(config.MANIFEST_PATH.read_text(encoding="utf-8"))
    pdf_ids = {d["doc_id"] for d in manifest["documents"] if d["included"]}
    return pdf_ids | {read_markdown(p)[0]["doc_id"] for p in GUIDES}


def test_there_are_23_guides_with_unique_ids():
    ids = [read_markdown(p)[0]["doc_id"] for p in GUIDES]
    assert len(ids) == 23
    assert len(set(ids)) == len(ids)


@pytest.mark.parametrize("path", GUIDES, ids=lambda p: p.stem)
def test_guide_structure_and_citations(path):
    meta, body = read_markdown(path)
    for field in REQUIRED_FIELDS:
        assert meta.get(field), f"missing {field}"
    assert meta["source_type"] == "team_written_from_official_docs"
    assert [l[3:].strip() for l in body.splitlines() if l.startswith("## ")] == SECTIONS
    declared = {r["id"] for r in meta["references"]}
    text = body.split("\n## References")[0]
    cited = set(re.findall(r"R\d+", " ".join(re.findall(r"\[(R\d+(?:,\s*R\d+)*)\]", text))))
    assert declared == cited, "every reference must be cited and every citation declared"
    assert all(r["url"].startswith("https://") and r["accessed"] for r in meta["references"])


@pytest.mark.parametrize("path", GUIDES, ids=lambda p: p.stem)
def test_links_between_guides_exist(path):
    known = all_doc_ids()
    text = path.read_text(encoding="utf-8")
    for doc_id in re.findall(r"`(md-[a-z0-9-]+)`", text):
        assert doc_id in known, f"link to unknown guide {doc_id}"
    for related in read_markdown(path)[0].get("related_corpus_documents") or []:
        assert related["doc_id"] in known


def test_evaluation_dataset_is_separate_and_consistent():
    assert not EVAL_PATH.is_relative_to(config.KNOWLEDGE_BASE_DIR)
    incidents = json.loads(EVAL_PATH.read_text(encoding="utf-8"))["incidents"]
    assert len(incidents) >= 50
    assert sum(i["split"] == "test" for i in incidents) >= 50
    known = all_doc_ids()
    for incident in incidents:
        assert set(incident["expected_doc_ids"]) <= known, incident["id"]
        assert incident["answerable"] == bool(incident["expected_doc_ids"])


def test_no_indexed_file_comes_from_the_evaluation_folder():
    for source in list_source_files():
        assert source["path"].is_relative_to(config.KNOWLEDGE_BASE_DIR)
