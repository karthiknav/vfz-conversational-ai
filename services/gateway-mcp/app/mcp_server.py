"""The real MCP protocol surface. Each @mcp.tool() here is a thin wrapper
around the implementation in app/tools/*.py — this module exists purely to
own tool registration/discovery (tools/list, tools/call), while the actual
logic, DB access, and audit logging live in the tools modules so they stay
testable without an MCP client in the loop.

Tool-to-agent binding (enforced by which tools each LangGraph agent node
binds via MultiServerMCPClient, not by anything in this file — see
services/orchestrator/app/agents/):
  knowledge_agent      -> get_customer_usage, get_customer_profile
  transactional_agent  -> get_catalog, propose_order
  governance_agent      -> get_order_eligibility, submit_order, create_case
"""

from mcp.server.fastmcp import FastMCP

from app.tools import bluemarble_tools, salesforce_tools, snowflake_tools

mcp = FastMCP("vz-gateway")


@mcp.tool()
async def get_customer_usage(customer_id: str, thread_id: str) -> dict:
    """Current data/minutes usage and spend for a customer (Advise tier, read-only)."""
    return await snowflake_tools.get_customer_usage(customer_id, thread_id)


@mcp.tool()
async def get_customer_profile(customer_id: str, thread_id: str) -> dict:
    """Tenure, churn risk, current product, and channel preference for a customer."""
    return await snowflake_tools.get_customer_profile(customer_id, thread_id)


@mcp.tool()
async def get_order_eligibility(customer_id: str, thread_id: str) -> dict:
    """Contract, credit and upgrade-eligibility facts for a customer (Governance Agent only)."""
    return await snowflake_tools.get_order_eligibility(customer_id, thread_id)


@mcp.tool()
async def get_catalog(thread_id: str) -> dict:
    """List available mobile plan offerings (Configure tier, read-only)."""
    return await bluemarble_tools.get_catalog(thread_id)


@mcp.tool()
async def propose_order(customer_id: str, target_offer_id: str, thread_id: str) -> dict:
    """Build a proposed plan upgrade for customer approval. Reads only — never executes."""
    return await bluemarble_tools.propose_order(customer_id, target_offer_id, thread_id)


@mcp.tool()
async def submit_order(
    customer_id: str, target_offer_id: str, idempotency_key: str, thread_id: str
) -> dict:
    """Execute an approved plan upgrade (Action tier). Governance Agent only.
    Independently re-verifies eligibility and the price-delta policy
    threshold before writing anything — a caller cannot bypass the gate by
    claiming the proposal was already approved.
    """
    return await bluemarble_tools.submit_order(customer_id, target_offer_id, idempotency_key, thread_id)


@mcp.tool()
async def create_case(
    customer_id: str,
    subject: str,
    thread_id: str,
    reason: str | None = None,
    force_fail: bool = False,
    is_compensation: bool = False,
    correlation_order_id: str | None = None,
) -> dict:
    """Create a Salesforce-mock CRM case. Used both for ordinary case
    creation and, with is_compensation=True, as the escalation step when an
    Action-tier write partially fails downstream.
    """
    return await salesforce_tools.create_case(
        customer_id, subject, thread_id, reason, force_fail, is_compensation, correlation_order_id
    )
