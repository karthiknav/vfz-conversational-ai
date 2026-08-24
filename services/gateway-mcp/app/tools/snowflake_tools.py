"""Snowflake-mock tools — the governed, fixed-shape read path. Every query
here goes through a named function against a named view in
db/init/004_governed_views.sql; there is no raw-SQL or dynamic-query path
exposed to an agent anywhere in this module, by design.
"""

from app.db import get_pool
from app.middleware.audit_logging import record_audit

ACTOR_AGENT = "knowledge_agent"


async def get_customer_usage(customer_id: str, thread_id: str) -> dict:
    """Current data/minutes usage and spend for a customer (Advise tier)."""
    pool = await get_pool()
    row = await pool.fetchrow(
        "SELECT * FROM analytics.vw_customer_usage_spend WHERE customer_id = $1",
        customer_id,
    )
    result = dict(row) if row else None

    await record_audit(
        thread_id=thread_id,
        phase="advise",
        actor_agent=ACTOR_AGENT,
        requested_by=customer_id,
        action_type="get_customer_usage",
        target_system="snowflake",
        request_payload={"customer_id": customer_id},
        outcome_status="success" if result else "failure",
        outcome_detail={"result": _jsonable(result)} if result else {"error": "customer not found"},
    )

    if result is None:
        raise ValueError(f"No usage data for customer {customer_id}")
    return _jsonable(result)


async def get_customer_profile(customer_id: str, thread_id: str) -> dict:
    """Tenure, churn risk, current product, and channel preference for a customer."""
    pool = await get_pool()
    row = await pool.fetchrow(
        "SELECT * FROM analytics.vw_customer_profile_360 WHERE customer_id = $1",
        customer_id,
    )
    result = dict(row) if row else None

    await record_audit(
        thread_id=thread_id,
        phase="advise",
        actor_agent=ACTOR_AGENT,
        requested_by=customer_id,
        action_type="get_customer_profile",
        target_system="snowflake",
        request_payload={"customer_id": customer_id},
        outcome_status="success" if result else "failure",
        outcome_detail={"result": _jsonable(result)} if result else {"error": "customer not found"},
    )

    if result is None:
        raise ValueError(f"No profile data for customer {customer_id}")
    return _jsonable(result)


async def get_order_eligibility(customer_id: str, thread_id: str) -> dict:
    """Contract, credit and eligibility facts used by the Governance Agent's
    policy check — bound to the Governance Agent's tool set, not the
    Knowledge/Transactional agents.
    """
    pool = await get_pool()
    row = await pool.fetchrow(
        "SELECT * FROM analytics.vw_order_eligibility WHERE customer_id = $1",
        customer_id,
    )
    result = dict(row) if row else None

    await record_audit(
        thread_id=thread_id,
        phase="action",
        actor_agent="governance_agent",
        requested_by=customer_id,
        action_type="get_order_eligibility",
        target_system="snowflake",
        request_payload={"customer_id": customer_id},
        outcome_status="success" if result else "failure",
        outcome_detail={"result": _jsonable(result)} if result else {"error": "customer not found"},
    )

    if result is None:
        raise ValueError(f"No eligibility data for customer {customer_id}")
    return _jsonable(result)


def _jsonable(row: dict | None) -> dict | None:
    if row is None:
        return None
    return {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in row.items()}
