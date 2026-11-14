"""Document-level and evidence-level metrics, on synthetic passages (no index, no model)."""
import pytest

from evaluation import metrics

PDF_PASSAGE = "The scheduler places Pods according to their requests, not their limits, and only on nodes with enough capacity."
MD_PASSAGE = "Inodes exhausted while blocks remain [R2]"
INCIDENT = {"evidence": [
    {"doc_id": "pdf-a", "page_number": 12, "printed_page": 2, "section": "Chapter 1", "exact_evidence_passage": PDF_PASSAGE},
    {"doc_id": "md-b", "page_number": None, "printed_page": None, "section": "Possible Causes",
     "exact_evidence_passage": MD_PASSAGE},
]}
UNITS = metrics.evidence_units(INCIDENT)

PDF_FULL = {"doc_id": "pdf-a", "page": 12, "section": None, "text": f"Some context. {PDF_PASSAGE} More text."}
PDF_PRINTED_PAGE = {**PDF_FULL, "page": 2}          # the printed page number is never used
PDF_OTHER_DOC = {**PDF_FULL, "doc_id": "pdf-z"}
MD_SECTION = {"doc_id": "md-b", "page": None, "section": "Possible Causes",
              "text": f"Guide > Possible Causes\n| **Many small files** | {MD_PASSAGE} |"}
MD_OTHER_SECTION = {**MD_SECTION, "section": "Prevention"}
UNRELATED = {"doc_id": "pdf-a", "page": 12, "section": None, "text": "Nothing about the evidence here."}


def test_document_level_metrics_are_unchanged():
    docs = ["x", "a", "b"]
    assert metrics.recall_at_k(docs, {"a", "c"}, 2) == 0.5
    assert metrics.precision_at_k(docs, {"a"}, 2) == 0.5
    assert metrics.reciprocal_rank(docs, {"b"}) == pytest.approx(1 / 3)


def test_hit_rate_at_k():
    docs = ["x", "a", "b"]
    assert metrics.hit_rate_at_k(docs, {"a", "c"}, 1) == 0.0
    assert metrics.hit_rate_at_k(docs, {"a", "c"}, 2) == 1.0   # one expected document is enough
    assert metrics.hit_rate_at_k(docs, set(), 3) == 0.0


def test_evidence_units_group_passages_by_physical_page_or_section():
    incident = {"evidence": INCIDENT["evidence"] + [
        {"doc_id": "pdf-a", "page_number": 12, "printed_page": 2, "section": "Chapter 1", "exact_evidence_passage": "Second."}]}
    units = metrics.evidence_units(incident)
    assert set(units) == {("pdf-a", 12), ("md-b", "Possible Causes")}
    assert len(units[("pdf-a", 12)]) == 2
    assert metrics.evidence_units({"id": "historical"}) == {}


def test_pdf_passage_matches_only_on_its_physical_page_and_document():
    unit = ("pdf-a", 12)
    assert metrics.passage_matches_unit(PDF_FULL, unit, UNITS[unit])
    assert not metrics.passage_matches_unit(PDF_PRINTED_PAGE, unit, UNITS[unit])
    assert not metrics.passage_matches_unit(PDF_OTHER_DOC, unit, UNITS[unit])
    assert not metrics.passage_matches_unit(UNRELATED, unit, UNITS[unit])


def test_markdown_passage_matches_only_in_its_section():
    unit = ("md-b", "Possible Causes")
    assert metrics.passage_matches_unit(MD_SECTION, unit, UNITS[unit])
    assert not metrics.passage_matches_unit(MD_OTHER_SECTION, unit, UNITS[unit])


def test_passage_split_over_two_overlapping_chunks_matches_both():
    long_passage = ("All init containers are executed in a sequence, one by one, and all of them have to terminate "
                    "successfully before the application containers are started up.")
    unit = ("pdf-a", 5)
    units = metrics.evidence_units({"evidence": [{"doc_id": "pdf-a", "page_number": 5, "section": None,
                                                  "exact_evidence_passage": long_passage}]})
    first = {"doc_id": "pdf-a", "page": 5, "text": "Previous text. " + long_passage[:90]}
    second = {"doc_id": "pdf-a", "page": 5, "text": long_passage[-80:] + " Next text."}
    middle_only = {"doc_id": "pdf-a", "page": 5, "text": long_passage[40:70]}   # 30 characters: too short
    assert metrics.passage_matches_unit(first, unit, units[unit])
    assert metrics.passage_matches_unit(second, unit, units[unit])
    assert not metrics.passage_matches_unit(middle_only, unit, units[unit])


def test_normalization_absorbs_pdf_extraction_artifacts():
    passage = "Kubernetes isn’t ready — the application needs “warm-up” time."
    extracted = {"doc_id": "pdf-a", "page": 3,
                 "text": "Kuber‐\nnetes isn't  ready - the\napplication needs \"warm-up\" time."}
    units = metrics.evidence_units({"evidence": [{"doc_id": "pdf-a", "page_number": 3, "section": None,
                                                  "exact_evidence_passage": passage}]})
    assert metrics.passage_matches_unit(extracted, ("pdf-a", 3), units[("pdf-a", 3)])


def test_evidence_recall_precision_and_rank():
    passages = [UNRELATED, PDF_FULL, MD_SECTION]
    assert metrics.evidence_recall_at_k(passages, UNITS, 1) == 0.0
    assert metrics.evidence_recall_at_k(passages, UNITS, 2) == 0.5
    assert metrics.evidence_recall_at_k(passages, UNITS, 3) == 1.0
    assert metrics.evidence_precision_at_k(passages, UNITS, 3) == pytest.approx(2 / 3)
    assert metrics.evidence_precision_at_k(passages[:1], UNITS, 5) == 0.0   # divided by k, like precision_at_k
    assert metrics.evidence_reciprocal_rank(passages, UNITS) == 0.5
    assert metrics.evidence_recall_at_k(passages, {}, 3) == 0.0


def test_two_chunks_of_the_same_unit_count_once_in_recall_and_twice_in_precision():
    passages = [PDF_FULL, {**PDF_FULL, "text": PDF_PASSAGE}]
    assert metrics.evidence_recall_at_k(passages, UNITS, 2) == 0.5
    assert metrics.evidence_precision_at_k(passages, UNITS, 2) == 1.0


def test_context_precision_and_recall():
    assert metrics.context_precision([PDF_FULL, UNRELATED], UNITS) == 0.5
    assert metrics.context_recall([PDF_FULL, UNRELATED], UNITS) == 0.5
    assert metrics.context_recall([PDF_FULL, MD_SECTION], UNITS) == 1.0
    assert metrics.context_precision([], UNITS) is None      # no passage given
    assert metrics.context_recall([], UNITS) == 0.0
    assert metrics.context_recall([PDF_FULL], {}) is None    # out-of-scope question: no evidence unit
