"""MCP server exposing the knowledge base to MCP clients (stdio transport).

Run:  python -m incident_assistant.mcp_server
Test: python scripts/mcp_client_demo.py   (or the MCP Inspector)
"""
from mcp.server.fastmcp import FastMCP

from incident_assistant.agents import reference_label
from incident_assistant.documents import document_metadata
from incident_assistant.indexing import load_registry
from incident_assistant.retrieval import hybrid_search, search

mcp = FastMCP("devops-knowledge-base")

SEARCH_MODES = ("hybrid", "semantic", "bm25")


@mcp.tool()
def search_knowledge_base(query: str, top_k: int = 5, domain: str | None = None, mode: str = "hybrid") -> list[dict]:
    """Search the DevOps troubleshooting knowledge base.

    Args:
        query: incident description, error message or question (English works best).
        top_k: number of passages to return (1-20).
        domain: optional filter, e.g. kubernetes, docker, networking, linux, git, github,
            gitlab, terraform, ansible, aws, sre.
        mode: "hybrid" (BM25 + semantic, fused with RRF), "semantic" or "bm25".

    Returns passages with their text, score and a precise reference (document + page or section).
    """
    if mode not in SEARCH_MODES:
        raise ValueError(f"mode must be one of {SEARCH_MODES}")
    if not 1 <= top_k <= 20:
        raise ValueError("top_k must be between 1 and 20")
    if not load_registry():
        raise ValueError("the knowledge base is not indexed yet: run python -m incident_assistant.indexing")
    domains = [domain] if domain else None
    if mode == "hybrid":
        passages = hybrid_search([query], domains=domains, top_k=top_k)
    else:
        passages = search(query, mode, k=top_k, domains=domains)
    return [{
        "rank": rank,
        "doc_id": p["doc_id"],
        "reference": reference_label(p),
        "page": p["page"],
        "section": p["section"],
        "score": round(p.get("rrf_score", p["score"]), 4),
        "text": p["text"],
    } for rank, p in enumerate(passages, start=1)]


@mcp.tool()
def get_document_metadata(doc_id: str) -> dict:
    """Return the metadata of a knowledge base document: title, domain, technologies,
    type, source type, licence or official references, and indexing information.

    Args:
        doc_id: document identifier as returned by search_knowledge_base (e.g. md-k8s-crashloopbackoff).
    """
    metadata = document_metadata(doc_id)
    if metadata is None:
        raise ValueError(f"unknown document: {doc_id}")
    indexed = load_registry().get(doc_id)
    metadata["indexed"] = indexed is not None
    if indexed:
        metadata["chunks"] = indexed["chunks"]
        metadata["indexed_at"] = indexed["indexed_at"]
    return metadata


if __name__ == "__main__":
    mcp.run()  # stdio transport by default
