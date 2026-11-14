"""Integration tests on the real index, the real MCP server and (optionally) the real LLM.
They are skipped when the index is not built or GROQ_API_KEY is missing.
Note: the embedded Qdrant storage can be opened by one process at a time, so stop the
Streamlit app / MCP server before running these tests."""
import asyncio
import json
import shutil
import sys

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from incident_assistant import config, documents, indexing, retrieval

needs_index = pytest.mark.skipif(not config.REGISTRY_PATH.exists(), reason="index not built")
needs_llm = pytest.mark.skipif(not config.GROQ_API_KEY, reason="GROQ_API_KEY missing")


@pytest.mark.integration
@needs_index
@pytest.mark.parametrize("strategy", ["bm25", "semantic", "hybrid", "hybrid_rerank"])
def test_each_strategy_finds_the_right_guide(strategy):
    passages = retrieval.search_with_strategy("terraform apply fails, error acquiring the state lock", strategy, top_k=5)
    assert passages[0]["doc_id"] == "md-terraform-state-lock"
    assert all(p["text"] and p["chunk_id"] for p in passages)


@pytest.mark.integration
@needs_index
def test_domain_filter_is_applied():
    passages = retrieval.hybrid_search(["permission denied"], domains=["docker"], top_k=5)
    assert passages and all(p["domain"] == "docker" for p in passages)


@pytest.mark.integration
@needs_index
def test_pdf_passages_keep_their_page_number():
    passages = retrieval.search("git reflog recover lost commits after reset", "bm25", k=5, domains=["git"])
    pdf = [p for p in passages if p["doc_id"] == "pdf-progit"]
    assert pdf and all(isinstance(p["page"], int) for p in pdf)


@pytest.mark.integration
def test_incremental_update_adds_updates_and_removes(tmp_path, monkeypatch):
    """Index two guides into a temporary collection, then modify one and delete the other."""
    kb = tmp_path / "knowledge_base"
    (kb / "markdown").mkdir(parents=True)
    for name in ("kubernetes/k8s-crashloopbackoff.md", "linux/linux-disk-full-no-space-left.md"):
        shutil.copy(config.KNOWLEDGE_BASE_DIR / "markdown" / name, kb / "markdown" / name.split("/")[1])
    monkeypatch.setattr(config, "KNOWLEDGE_BASE_DIR", kb)
    monkeypatch.setattr(config, "COLLECTION_NAME", "pytest_incremental")
    monkeypatch.setattr(config, "REGISTRY_PATH", tmp_path / "registry.json")

    def sources():
        result = []
        for path in sorted((kb / "markdown").glob("*.md")):
            meta, _ = documents.read_markdown(path)
            result.append({"doc_id": meta["doc_id"], "path": path, "kind": "markdown", "info": meta,
                           "hash": documents.file_hash(path)})
        return result

    monkeypatch.setattr(indexing, "list_source_files", sources)
    client = indexing.get_client()
    try:
        first = indexing.update_index(rebuild=True)
        assert sorted(first["added"]) == ["md-k8s-crashloopbackoff", "md-linux-disk-full"]

        guide = kb / "markdown" / "k8s-crashloopbackoff.md"
        guide.write_text(guide.read_text(encoding="utf-8") + "\nExtra line.\n", encoding="utf-8")
        (kb / "markdown" / "linux-disk-full-no-space-left.md").unlink()
        second = indexing.update_index()
        assert second["updated"] == ["md-k8s-crashloopbackoff"]
        assert second["removed"] == ["md-linux-disk-full"]
        count = client.count("pytest_incremental", exact=True).count
        assert count == json.loads(config.REGISTRY_PATH.read_text())["md-k8s-crashloopbackoff"]["chunks"]
    finally:
        if client.collection_exists("pytest_incremental"):
            client.delete_collection("pytest_incremental")


async def call_mcp_server():
    server = StdioServerParameters(command=sys.executable, args=["-m", "incident_assistant.mcp_server"])
    async with stdio_client(server) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            search = await session.call_tool("search_knowledge_base",
                                             {"query": "kubectl shows ImagePullBackOff", "top_k": 3})
            metadata = await session.call_tool("get_document_metadata", {"doc_id": "md-k8s-imagepullbackoff"})
            unknown = await session.call_tool("get_document_metadata", {"doc_id": "nope"})
            bad_mode = await session.call_tool("search_knowledge_base", {"query": "x", "mode": "magic"})
            return tools, search, metadata, unknown, bad_mode


@pytest.mark.integration
@needs_index
def test_mcp_server_with_a_real_mcp_client():
    # The embedded Qdrant storage accepts one process at a time: release it for the server subprocess.
    indexing.get_client().close()
    indexing.get_client.cache_clear()
    tools, search, metadata, unknown, bad_mode = asyncio.run(call_mcp_server())
    assert {t.name for t in tools.tools} == {"search_knowledge_base", "get_document_metadata"}
    assert not search.isError
    passages = search.structuredContent["result"]
    assert len(passages) == 3 and passages[0]["doc_id"] == "md-k8s-imagepullbackoff"
    assert "reference" in passages[0] and "text" in passages[0]
    assert json.loads(metadata.content[0].text)["domain"] == "kubernetes"
    assert unknown.isError and bad_mode.isError


@pytest.mark.integration
@pytest.mark.llm
@needs_index
@needs_llm
def test_full_workflow_with_the_llm():
    from incident_assistant.workflow import run_investigation
    state = run_investigation("Our nginx reverse proxy returns 502 Bad Gateway for every API call since this morning's deployment.")
    answer = state["answer"]
    assert answer["status"] in ("ok", "insufficient_evidence")
    assert answer["possible_causes"] and answer["investigation_steps"]
    valid_ids = {p["id"] for p in answer["passages"]}
    assert all(e in valid_ids for c in answer["possible_causes"] for e in c["evidence"])
    assert any(r["doc_id"] == "md-net-http-502-503-504" for r in answer["references"])
