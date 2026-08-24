"""Audit-trail helper, called from inside each MCP tool (not as generic ASGI
middleware) — tool functions are the only place with enough semantic context
(which agent, which args, success/failure, governance outcome) to write a
meaningful row. Every tool call in this Gateway goes through record_audit(),
with no exceptions, per the plan's "no money-or-state action skips the
governance/audit gate" rule.
"""

import json
from typing import Any

from app.db import get_pool


async def record_audit(
    *,
    thread_id: str | None,
    phase: str,
    actor_agent: str,
    requested_by: str,
    action_type: str,
    target_system: str,
    outcome_status: str,
    idempotency_key: str | None = None,
    request_payload: dict[str, Any] | None = None,
    governance_decision: str = "not_required",
    governance_reason: str | None = None,
    outcome_detail: dict[str, Any] | None = None,
    correlation_order_id: str | None = None,
    correlation_case_id: str | None = None,
    trace_id: str | None = None,
) -> None:
    pool = await get_pool()
    await pool.execute(
        """
        INSERT INTO audit.audit_trail (
            trace_id, thread_id, phase, actor_agent, requested_by, action_type,
            target_system, idempotency_key, request_payload, governance_decision,
            governance_reason, outcome_status, outcome_detail,
            correlation_order_id, correlation_case_id
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15)
        """,
        trace_id,
        thread_id,
        phase,
        actor_agent,
        requested_by,
        action_type,
        target_system,
        idempotency_key,
        json.dumps(request_payload) if request_payload is not None else None,
        governance_decision,
        governance_reason,
        outcome_status,
        json.dumps(outcome_detail) if outcome_detail is not None else None,
        correlation_order_id,
        correlation_case_id,
    )
