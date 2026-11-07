"""Pure logic of the retrieval module and of the metrics (no model, no index needed)."""
from types import SimpleNamespace

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


def test_rrf_default_is_k_60_with_ranks_starting_at_one():
    assert config.RRF_K == 60
    fused = retrieval.reciprocal_rank_fusion([[passage("a"), passage("b")]])
    assert [p["rrf_score"] for p in fused] == pytest.approx([1 / 61, 1 / 62])
    assert [p["ranks"] for p in fused] == [[1], [2]]


def test_rrf_with_no_list_or_a_single_non_empty_list():
    assert retrieval.reciprocal_rank_fusion([]) == []
    assert retrieval.reciprocal_rank_fusion([[], []]) == []
    assert [p["chunk_id"] for p in retrieval.reciprocal_rank_fusion([[], [passage("a"), passage("b")]])] == ["a", "b"]


def test_rrf_equal_scores_keep_the_first_seen_order():
    fused = retrieval.reciprocal_rank_fusion([[passage("b")], [passage("a")]])
    assert fused[0]["rrf_score"] == fused[1]["rrf_score"]
    assert [p["chunk_id"] for p in fused] == ["b", "a"]


def test_rrf_merges_the_same_chunks_without_changing_the_input_lists():
    dense = [passage("a"), passage("b")]
    bm25 = [passage("b"), passage("a")]
    fused = retrieval.reciprocal_rank_fusion([dense, bm25])
    assert sorted(p["chunk_id"] for p in fused) == ["a", "b"]
    assert all(p["rrf_score"] == pytest.approx(1 / 61 + 1 / 62) and sorted(p["ranks"]) == [1, 2] for p in fused)
    assert "rrf_score" not in dense[0] and "ranks" not in bm25[0]


def fake_search(results):
    """Replaces retrieval.search: results maps (query, mode) to a list of passages."""
    def search(query, mode, **kwargs):
        return results.get((query, mode), [])
    return search


def test_hybrid_search_with_only_one_method_finding_results(monkeypatch):
    monkeypatch.setattr(retrieval, "search", fake_search({("q", "semantic"): [passage("a"), passage("b")]}))
    assert [p["chunk_id"] for p in retrieval.hybrid_search(["q"])] == ["a", "b"]


def test_hybrid_search_keeps_the_rrf_order_without_calling_the_reranker(monkeypatch):
    def no_reranker():
        pytest.fail("the production search must not use the reranker")

    results = {("q", "semantic"): [passage("a"), passage("b")], ("q", "bm25"): [passage("b"), passage("c")]}
    monkeypatch.setattr(retrieval, "search", fake_search(results))
    monkeypatch.setattr(retrieval, "get_reranker", no_reranker)
    assert [p["chunk_id"] for p in retrieval.hybrid_search(["q"], top_k=2)] == ["b", "a"]


def test_hybrid_search_with_the_reranker_and_no_query_returns_nothing():
    assert retrieval.hybrid_search([], use_reranker=True) == []


def test_search_errors_are_not_hidden(monkeypatch):
    def unavailable(*args, **kwargs):
        raise ConnectionError("qdrant unavailable")

    monkeypatch.setattr(retrieval, "search", unavailable)
    with pytest.raises(ConnectionError):
        retrieval.hybrid_search(["q"])


class FakeStore:
    def __init__(self):
        self.queries = []

    def similarity_search_with_score(self, query, k, filter):
        self.queries.append(query)
        return []


@pytest.mark.parametrize("query", ["", "   ", " \n\t "])
def test_blank_query_is_not_searched(monkeypatch, query):
    store = FakeStore()
    monkeypatch.setattr(retrieval, "get_vector_store", lambda *args, **kwargs: store)
    assert retrieval.search(query, "semantic") == []
    assert retrieval.hybrid_search([query]) == []
    assert store.queries == []


def test_blank_query_does_not_add_a_ranked_list_to_the_fusion(monkeypatch):
    store = FakeStore()
    monkeypatch.setattr(retrieval, "get_vector_store", lambda *args, **kwargs: store)
    retrieval.hybrid_search(["  ", "disk full"])
    assert store.queries == ["disk full", "disk full"]


METADATA = {"chunk_id": "doc#2", "doc_id": "doc", "title": "Doc", "source_path": "markdown/linux/doc.md",
            "domain": "linux", "technology": ["linux", "systemd"], "page": None, "section": "Overview"}


def test_passage_keeps_the_indexed_metadata():
    p = retrieval.to_passage(SimpleNamespace(metadata=METADATA, page_content="text"), 0.5)
    assert {key: p[key] for key in METADATA} == METADATA
    assert p["text"] == "text" and p["score"] == 0.5


def test_passage_accepts_an_absent_page_section_or_technology():
    meta = {key: value for key, value in METADATA.items() if key not in ("page", "section", "technology")}
    p = retrieval.to_passage(SimpleNamespace(metadata=meta, page_content="text"), 0.5)
    assert p["page"] is None and p["section"] is None and p["technology"] == []


def test_passage_without_chunk_id_is_refused_instead_of_being_merged_by_the_fusion():
    meta = {key: value for key, value in METADATA.items() if key != "chunk_id"}
    with pytest.raises(KeyError):
        retrieval.to_passage(SimpleNamespace(metadata=meta, page_content="text"), 0.5)


def test_passages_without_reranker_score_are_not_evidence(monkeypatch):
    monkeypatch.setattr(config, "EVIDENCE_MIN_SCORE", -2.86)
    monkeypatch.setattr(config, "EVIDENCE_MIN_PASSAGES", 3)
    assert not retrieval.evidence_is_sufficient([passage("a"), passage("b"), passage("c")])


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
