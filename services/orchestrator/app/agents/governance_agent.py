"""Governance Agent — Action tier. Bound to get_order_eligibility,
submit_order, and create_case. submit_order is the only tool in the whole
system that writes an order, and it independently re-checks eligibility and
the price-delta policy threshold server-side (see
services/gateway-mcp/app/tools/bluemarble_tools.py) — this node's job is to
call it, relay the outcome, and, in the induced-failure demo path, drive the
compensation/escalation flow when a downstream CRM sync fails.
"""

from langchain_core.messages import SystemMessage
from langgraph.prebuilt import create_react_agent

from app.agents.common import extract_tool_result, session_prefix
from app.bedrock import get_llm
from app.mcp_client import governance_agent_tools

BASE_PROMPT = """You are the Governance Agent for VodafoneZiggo's conversational AI
assistant. A customer has just approved the following plan-upgrade proposal:

{proposal}

Steps:
1. Call submit_order with target_offer_id='{target_offer_id}' and
   idempotency_key='{idempotency_key}'.
2. If the result status is "success": tell the customer their upgrade is complete.
3. If "blocked" or "escalated": tell the customer clearly why, in plain language,
   without technical jargon.
{compensation_instructions}
Be concise and factual. Never claim an order succeeded unless submit_order
returned status "success".
"""

COMPENSATION_INSTRUCTIONS = """4. After a successful submit_order, take the order id from its result and
   call create_case with subject="CRM sync for order <that order id>",
   reason="Recording upgrade in CRM", force_fail=true, and
   correlation_order_id set to that same order id — this call is expected to
   fail in this scenario.
5. If step 4 fails, immediately call create_case again with the same subject,
   reason and correlation_order_id, this time with force_fail=false and
   is_compensation=true, to open a follow-up case for the advisor team. Then
   tell the customer their upgrade is complete but a follow-up case has been
   opened to confirm everything synced correctly.
"""

_agent = None


async def _get_agent():
    global _agent
    if _agent is None:
        tools = await governance_agent_tools()
        _agent = create_react_agent(get_llm(), tools=tools)
    return _agent


async def run(state: dict) -> dict:
    proposal = state["pending_proposal"]
    idempotency_key = f"idem-{proposal['proposal_id']}"

    compensation = COMPENSATION_INSTRUCTIONS if state.get("simulate_partial_failure") else ""
    prompt = BASE_PROMPT.format(
        proposal=proposal,
        target_offer_id=proposal["target_offer_id"],
        idempotency_key=idempotency_key,
        compensation_instructions=compensation,
    )

    agent = await _get_agent()
    system = SystemMessage(content=session_prefix(state["customer_id"], state["thread_id"]) + prompt)
    result = await agent.ainvoke({"messages": [system] + state["messages"]})

    new_messages = result["messages"][len([system] + state["messages"]) :]
    order_result = extract_tool_result(new_messages, "submit_order")

    return {
        "messages": new_messages,
        "phase": "action",
        "pending_proposal": None,
        "last_action_result": order_result,
    }
