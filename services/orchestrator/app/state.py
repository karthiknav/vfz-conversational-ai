"""Journey state — the concrete implementation of the RFP's "Journey State
Manager / Context & Memory Manager" box. Persisted per thread_id by the
LangGraph checkpointer (MemorySaver locally, PostgresSaver on AWS — see
graph.py), so a customer's conversation and any pending proposal survive
across turns without the orchestrator holding anything in process memory.
"""

from typing import Annotated, Literal, Optional, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages


class PendingProposal(TypedDict):
    proposal_id: str
    target_offer_id: str
    target_offer_name: str
    target_monthly_price_eur: float
    current_monthly_price_eur: float
    delta_eur: float


class JourneyState(TypedDict):
    customer_id: str
    thread_id: str
    messages: Annotated[list[AnyMessage], add_messages]
    phase: Literal["advise", "configure", "action"]
    intent: Optional[str]
    pending_proposal: Optional[PendingProposal]
    last_action_result: Optional[dict]
    # Demo-only injection hook for the induced partial-failure /
    # compensation walkthrough (plan Turn 3''). Set only by the /approve
    # endpoint when explicitly requested; never true in a real approval.
    simulate_partial_failure: Optional[bool]
