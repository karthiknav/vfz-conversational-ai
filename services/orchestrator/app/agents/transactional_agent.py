"""Transactional Agent — Configure tier. Bound only to get_catalog and
propose_order (see app/mcp_client.py); submit_order is not in this agent's
tool set at all, so "propose, don't execute" is a structural property of the
graph, not a prompt instruction the LLM could be talked out of.
"""

from langchain_core.messages import SystemMessage
from langgraph.prebuilt import create_react_agent

from app.agents.common import extract_tool_result, session_prefix
from app.bedrock import get_llm
from app.mcp_client import transactional_agent_tools

BASE_PROMPT = (
    "You are the Transactional Agent for VodafoneZiggo's conversational AI assistant. "
    "You help customers explore plan upgrades. Use get_catalog to see available plans "
    "and propose_order to build a proposal for a specific plan the customer wants. "
    "You can only propose — you never execute an order yourself. After proposing, "
    "clearly state the new monthly price, the price delta versus their current plan, "
    "and that they need to approve before anything changes."
)

_agent = None


async def _get_agent():
    global _agent
    if _agent is None:
        tools = await transactional_agent_tools()
        _agent = create_react_agent(get_llm(), tools=tools)
    return _agent


async def run(state: dict) -> dict:
    agent = await _get_agent()
    system = SystemMessage(content=session_prefix(state["customer_id"], state["thread_id"]) + BASE_PROMPT)
    result = await agent.ainvoke({"messages": [system] + state["messages"]})

    new_messages = result["messages"][len([system] + state["messages"]) :]
    proposal = extract_tool_result(new_messages, "propose_order")

    update = {"messages": new_messages, "phase": "configure"}
    if proposal is not None:
        update["pending_proposal"] = proposal
    return update
