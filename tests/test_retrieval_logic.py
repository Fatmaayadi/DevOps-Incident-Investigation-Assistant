"""Pure logic of the retrieval module and of the metrics (no model, no index needed)."""
import pytest

from evaluation.metrics import precision_at_k, recall_at_k, reciprocal_rank
from incident_assistant import config, retrieval


def passage(chunk_id, doc_id="doc", rerank=None):
    p = {"chunk_id": chunk_id, "doc_id": doc_id, "text": chunk_id}
    if rerank is not None:
        p["rerank_score"] = rerank
    return p


def test_rrf_favours_passages_ranked_by_both_methods():
    dense = [passage("a"), passage("b"), passage("c")]
    bm25 = [passage("c"), passage("d"), passage("a")]
    fused = retrieval.reciprocal_rank_fusion([dense, bm25], k=60)
    scores = {p["chunk_id"]: p["rrf_score"] for p in fused}
    assert scores["a"] == pytest.approx(1 / 61 + 1 / 63)
    assert scores["d"] == pytest.approx(1 / 62)
    assert [p["chunk_id"] for p in fused][:2] == ["a", "c"]   # found by both lists
    assert len(fused) == 4                                     # duplicates merged


def test_evidence_check_uses_reranker_scores(monkeypatch):
    monkeypatch.setattr(config, "EVIDENCE_MIN_SCORE", 0.5)
    monkeypatch.setattr(config, "EVIDENCE_MIN_PASSAGES", 2)
    assert retrieval.evidence_is_sufficient([passage("a", rerank=0.9), passage("b", rerank=0.6)])
    assert not retrieval.evidence_is_sufficient([passage("a", rerank=0.9), passage("b", rerank=0.1)])
    assert not retrieval.evidence_is_sufficient([])


def test_score_passages_keeps_rrf_order_but_rerank_sorts(monkeypatch):
    class FakeReranker:
        def predict(self, pairs):
            return [len(text) for _, text in pairs]   # longer text = higher score
    monkeypatch.setattr(retrieval, "get_reranker", lambda: FakeReranker())
    passages = [passage("a"), passage("ccc"), passage("bb")]
    scored = retrieval.score_passages("q", passages)
    assert [p["chunk_id"] for p in scored] == ["a", "ccc", "bb"]          # order unchanged
    assert [p["rerank_score"] for p in scored] == [1, 3, 2]
    assert [p["chunk_id"] for p in retrieval.rerank("q", passages)] == ["ccc", "bb", "a"]


def test_domain_filter():
    assert retrieval.domain_filter(None) is None
    flt = retrieval.domain_filter(["docker"])
    assert flt.must[0].key == "metadata.domain"


def test_retrieval_metrics():
    docs = ["x", "a", "a", "y", "b"]
    assert recall_at_k(docs, {"a", "b"}, 3) == 0.5
    assert recall_at_k(docs, {"a", "b"}, 5) == 1.0
    assert precision_at_k(docs, {"a"}, 3) == pytest.approx(2 / 3)
    assert reciprocal_rank(docs, {"a"}) == 0.5
    assert reciprocal_rank(docs, {"z"}) == 0.0
    assert recall_at_k(docs, set(), 5) == 0.0
