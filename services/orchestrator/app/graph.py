"""The LangGraph StateGraph implementing the supervisor/router pattern
described in the plan. Two important implementation notes versus the
original sketch in docs/architecture-decisions.md:

1. Router intent classification only distinguishes "knowledge" vs.
   "transactional" vs. "out_of_scope" — approval is a structural UI action
   (the /approve/{proposal_id} endpoint), never a chat message the router
   has to interpret. This keeps "propose, don't execute" enforced by which
   endpoint is called, not by LLM judgement.

2. The Action-tier hand-off does not use LangGraph's interrupt()/Command
   primitive. Each HTTP request (a /chat turn or an /approve call) is
   already its own separate graph invocation against the same persisted
   thread — that already gives "pause across turns" for free via the
   checkpointer. The /approve endpoint (see api.py) calls
   governance_agent.run() directly and folds the result back into the
   checkpoint with graph.aupdate_state(..., as_node="governance_agent"),
   which is the documented pattern for an update driven by something other
   than a normal graph step. This sidesteps interrupt/resume edge cases
   around a thread receiving an unrelated chat message while a proposal is
   still open — the plan's "what's my usage" example.
"""

import os
from typing import Literal
from urllib.parse import quote

from langchain_core.messages import AIMessage, SystemMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph
from pydantic import BaseModel

from app.agents import governance_agent, knowledge_agent, transactional_agent
from app.bedrock import get_llm
from app.state import JourneyState


class RouterDecision(BaseModel):
    """Routing decision for a customer message: which internal agent should handle it."""

    intent: Literal["knowledge", "transactional", "out_of_scope"]


ROUTER_SYSTEM = (
    "You route customer messages to the right internal agent for a telecom "
    "assistant. Reply intent='knowledge' for questions about current usage, "
    "spend, or account info. Reply intent='transactional' when the customer "
    "wants to explore or request a plan upgrade/change. Reply "
    "intent='out_of_scope' for anything unrelated to mobile plans, usage, or "
    "billing."
)


async def router_node(state: JourneyState) -> dict:
    router_llm = get_llm().with_structured_output(RouterDecision)
    system = SystemMessage(content=ROUTER_SYSTEM)
    decision: RouterDecision = await router_llm.ainvoke([system] + state["messages"])
    return {"intent": decision.intent}


def route_after_router(state: JourneyState) -> str:
    return {
        "knowledge": "knowledge_agent",
        "transactional": "transactional_agent",
        "out_of_scope": "out_of_scope",
    }[state["intent"]]


async def out_of_scope_node(state: JourneyState) -> dict:
    msg = AIMessage(
        content=(
            "I can help with your VodafoneZiggo mobile plan — usage, spend, "
            "or upgrading your bundle. Could you rephrase your question "
            "around one of those?"
        )
    )
    return {"messages": [msg]}


def build_graph(checkpointer) -> StateGraph:
    graph = StateGraph(JourneyState)

    graph.add_node("router", router_node)
    graph.add_node("knowledge_agent", knowledge_agent.run)
    graph.add_node("transactional_agent", transactional_agent.run)
    # governance_agent is registered so aupdate_state(as_node="governance_agent")
    # attributes the /approve-driven state update correctly in history, even
    # though no chat-routed edge ever leads into it — see module docstring.
    graph.add_node("governance_agent", governance_agent.run)
    graph.add_node("out_of_scope", out_of_scope_node)

    graph.set_entry_point("router")
    graph.add_conditional_edges("router", route_after_router)
    graph.add_edge("knowledge_agent", END)
    graph.add_edge("transactional_agent", END)
    graph.add_edge("governance_agent", END)
    graph.add_edge("out_of_scope", END)

    return graph.compile(checkpointer=checkpointer)


def _postgres_conninfo() -> str | None:
    host = os.environ.get("POSTGRES_HOST")
    if not host:
        return None
    port = os.environ.get("POSTGRES_PORT", "5432")
    db = os.environ.get("POSTGRES_DB", "vfz_poc")
    user = quote(os.environ["POSTGRES_USER"], safe="")
    password = quote(os.environ["POSTGRES_PASSWORD"], safe="")
    return f"postgresql://{user}:{password}@{host}:{port}/{db}"


_checkpointer_cm = None
_checkpointer = None
_compiled_graph = None


async def get_graph():
    """Local (no POSTGRES_HOST): MemorySaver, in-process, lost on restart.
    AWS (POSTGRES_HOST set, per infra/k8s/orchestrator/deployment.yaml):
    AsyncPostgresSaver against the shared RDS instance — required once the
    orchestrator runs with replicas > 1, since conversation/proposal state
    (the /approve hand-off) must survive pod restarts and be visible across
    replicas, not just the process that handled the /chat turn.
    """
    global _checkpointer_cm, _checkpointer, _compiled_graph
    if _compiled_graph is not None:
        return _compiled_graph

    conninfo = _postgres_conninfo()
    if conninfo is None:
        _checkpointer = MemorySaver()
    else:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

        _checkpointer_cm = AsyncPostgresSaver.from_conn_string(conninfo)
        _checkpointer = await _checkpointer_cm.__aenter__()
        await _checkpointer.setup()

    _compiled_graph = build_graph(_checkpointer)
    return _compiled_graph
