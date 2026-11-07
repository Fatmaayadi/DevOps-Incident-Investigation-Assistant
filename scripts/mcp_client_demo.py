"""Minimal MCP client: starts the MCP server as a subprocess (stdio), lists its tools and calls them.

Usage: python scripts/mcp_client_demo.py
"""
import asyncio
import json
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

SERVER = StdioServerParameters(command=sys.executable, args=["-m", "incident_assistant.mcp_server"])


async def main():
    async with stdio_client(SERVER) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools = await session.list_tools()
            print("Tools exposed by the server:")
            for tool in tools.tools:
                print(f" - {tool.name}: {tool.description.splitlines()[0]}")

            print("\nCalling search_knowledge_base ...")
            result = await session.call_tool("search_knowledge_base", {
                "query": "terraform apply fails because the state is locked", "top_k": 3})
            passages = result.structuredContent["result"]   # FastMCP wraps list results in "result"
            for passage in passages:
                print(f" {passage['rank']}. {passage['reference']} (score {passage['score']})")

            print("\nCalling get_document_metadata ...")
            result = await session.call_tool("get_document_metadata", {"doc_id": passages[0]["doc_id"]})
            metadata = json.loads(result.content[0].text)
            print(json.dumps({k: metadata[k] for k in ("doc_id", "title", "domain", "source_type", "chunks")}, indent=2))

            print("\nCalling get_document_metadata with an unknown id (error expected) ...")
            result = await session.call_tool("get_document_metadata", {"doc_id": "does-not-exist"})
            print(" isError =", result.isError, "|", result.content[0].text)


if __name__ == "__main__":
    asyncio.run(main())
