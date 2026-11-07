"""Semantic search, BM25 search, Reciprocal Rank Fusion, reranking and evidence check.

The same functions are used by the LangGraph workflow, the MCP server and the benchmark.
"""
from functools import lru_cache

from langchain_qdrant import RetrievalMode
from qdrant_client import models
from sentence_transformers import CrossEncoder

from incident_assistant import config
from incident_assistant.indexing import get_vector_store

MODES = {"semantic": RetrievalMode.DENSE, "bm25": RetrievalMode.SPARSE}


@lru_cache
def get_reranker() -> CrossEncoder:
    return CrossEncoder(config.RERANKER_MODEL)


def domain_filter(domains: list[str] | None) -> models.Filter | None:
    if not domains:
        return None
    return models.Filter(must=[models.FieldCondition(key="metadata.domain", match=models.MatchAny(any=domains))])


def to_passage(document, score: float) -> dict:
    meta = document.metadata
    return {
        "chunk_id": meta["chunk_id"],
        "doc_id": meta["doc_id"],
        "title": meta["title"],
        "source_path": meta["source_path"],
        "domain": meta["domain"],
        "page": meta.get("page"),
        "section": meta.get("section"),
        "text": document.page_content,
        "score": float(score),
    }


def search(query: str, mode: str, k: int = config.CANDIDATES_PER_SEARCH, domains: list[str] | None = None,
           collection: str = config.COLLECTION_NAME, model_name: str = config.EMBEDDING_MODEL) -> list[dict]:
    """Single search with one method: 'semantic' (dense embeddings) or 'bm25' (sparse vectors)."""
    store = get_vector_store(MODES[mode], collection=collection, model_name=model_name)
    results = store.similarity_search_with_score(query, k=k, filter=domain_filter(domains))
    return [to_passage(doc, score) for doc, score in results]


def reciprocal_rank_fusion(ranked_lists: list[list[dict]], k: int = config.RRF_K) -> list[dict]:
    """RRF(d) = sum over lists of 1 / (k + rank of d in the list). Only ranks are used,
    so dense cosine scores and BM25 scores never need to be put on the same scale."""
    fused = {}
    for ranked in ranked_lists:
        for rank, passage in enumerate(ranked, start=1):
            entry = fused.setdefault(passage["chunk_id"], {**passage, "rrf_score": 0.0, "ranks": []})
            entry["rrf_score"] += 1.0 / (k + rank)
            entry["ranks"].append(rank)
    return sorted(fused.values(), key=lambda p: p["rrf_score"], reverse=True)


def score_passages(query: str, passages: list[dict]) -> list[dict]:
    """Add a cross-encoder relevance score to each passage, without changing their order.
    The workflow uses these scores to decide whether the evidence is sufficient."""
    if passages:
        scores = get_reranker().predict([(query, p["text"]) for p in passages])
        for passage, score in zip(passages, scores):
            passage["rerank_score"] = float(score)
    return passages


def rerank(query: str, passages: list[dict]) -> list[dict]:
    return sorted(score_passages(query, passages), key=lambda p: p["rerank_score"], reverse=True)


def hybrid_search(queries: list[str], domains: list[str] | None = None, use_reranker: bool = False,
                  rerank_query: str | None = None, top_k: int = config.FINAL_PASSAGES,
                  collection: str = config.COLLECTION_NAME, model_name: str = config.EMBEDDING_MODEL) -> list[dict]:
    """Dense + BM25 search for every query, fused with RRF. Reranking is optional and off by
    default: on the benchmark, RRF alone gave a better MRR than RRF + reranker."""
    ranked_lists = []
    for query in queries:
        for mode in MODES:
            ranked_lists.append(search(query, mode, domains=domains, collection=collection, model_name=model_name))
    fused = reciprocal_rank_fusion(ranked_lists)
    if not use_reranker:
        return fused[:top_k]
    candidates = fused[:config.RERANK_CANDIDATES]
    return rerank(rerank_query or queries[0], candidates)[:top_k]


def search_with_strategy(query: str, strategy: str, top_k: int = 10, collection: str = config.COLLECTION_NAME,
                         model_name: str = config.EMBEDDING_MODEL) -> list[dict]:
    """Entry point used by the benchmark: 'bm25', 'semantic', 'hybrid' or 'hybrid_rerank'."""
    if strategy in MODES:
        return search(query, strategy, k=top_k, collection=collection, model_name=model_name)
    return hybrid_search([query], use_reranker=(strategy == "hybrid_rerank"), top_k=top_k,
                         collection=collection, model_name=model_name)


def evidence_is_sufficient(passages: list[dict]) -> bool:
    """Enough passages judged relevant by the reranker (thresholds in config)."""
    strong = [p for p in passages if p.get("rerank_score", 0.0) >= config.EVIDENCE_MIN_SCORE]
    return len(strong) >= config.EVIDENCE_MIN_PASSAGES
