"""Tool Calling through MCP: the LLM decides by itself when to call the MCP tools.

The tools are discovered from the MCP server with langchain-mcp-adapters, bound to the LLM
with bind_tools, and a small agent loop executes the tool calls (same loop as lab 09).

Usage: python scripts/mcp_agent_demo.py "How do I release a stale Terraform state lock?"
"""
import asyncio
import sys

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_mcp_adapters.client import MultiServerMCPClient

from incident_assistant.agents import get_llm

SYSTEM = SystemMessage("""You are a DevOps assistant. Use the search_knowledge_base tool to find
documentation before answering, and get_document_metadata if you need details about a source.
Answer briefly and cite the references returned by the tools.""")


async def main(question: str, max_steps: int = 5):
    client = MultiServerMCPClient({"kb": {"command": sys.executable,
                                          "args": ["-m", "incident_assistant.mcp_server"],
                                          "transport": "stdio"}})
    tools = await client.get_tools()
    tools_by_name = {tool.name: tool for tool in tools}
    llm = get_llm().bind_tools(tools)
    messages = [SYSTEM, HumanMessage(question)]

    for _ in range(max_steps):
        response = await llm.ainvoke(messages)
        messages.append(response)
        if not response.tool_calls:
            print("\nAI:", response.content)
            return
        for call in response.tool_calls:
            print(f"-> tool call: {call['name']}({call['args']})")
            try:
                result = await tools_by_name[call["name"]].ainvoke(call["args"])
            except Exception as error:   # unknown tool or invalid arguments: tell the model
                result = f"error: {error}"
            messages.append(ToolMessage(content=str(result), tool_call_id=call["id"]))
    print("Stopped: too many steps.")


if __name__ == "__main__":
    asyncio.run(main(" ".join(sys.argv[1:]) or "How do I release a stale Terraform state lock?"))
