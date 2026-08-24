"""Knowledge Agent — Advise tier. Bound only to the two read-only
usage/profile tools (see app/mcp_client.py); has no path to any write tool,
so this node cannot commit a state change no matter what the LLM decides.
"""

from langchain_core.messages import SystemMessage
from langgraph.prebuilt import create_react_agent

from app.agents.common import session_prefix
from app.bedrock import get_llm
from app.mcp_client import knowledge_agent_tools

BASE_PROMPT = (
    "You are the Knowledge Agent for VodafoneZiggo's conversational AI assistant. "
    "You answer questions about a customer's current usage, spend, and account "
    "profile using your tools. You are strictly read-only — you never propose or "
    "execute any change. Answer in a short, friendly, factual style, citing the "
    "real numbers your tools return."
)

_agent = None


async def _get_agent():
    global _agent
    if _agent is None:
        tools = await knowledge_agent_tools()
        _agent = create_react_agent(get_llm(), tools=tools)
    return _agent


async def run(state: dict) -> dict:
    agent = await _get_agent()
    system = SystemMessage(content=session_prefix(state["customer_id"], state["thread_id"]) + BASE_PROMPT)
    result = await agent.ainvoke({"messages": [system] + state["messages"]})

    new_messages = result["messages"][len([system] + state["messages"]) :]
    return {"messages": new_messages, "phase": "advise"}
