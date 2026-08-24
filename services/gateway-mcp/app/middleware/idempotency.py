"""Idempotency-key dedup, enforced against the audit trail itself rather than
a separate table — the audit_trail's partial unique index on
(idempotency_key WHERE outcome_status='success') is the single source of
truth for "has this write already happened."

MCP has no built-in Idempotency-Key convention (unlike a REST header), so
each write tool (submit_order, create_case) accepts idempotency_key as an
explicit argument and calls check_cached_result() before doing any backend
work.
"""

import json

from app.db import get_pool


async def check_cached_result(idempotency_key: str | None) -> dict | None:
    if not idempotency_key:
        return None

    pool = await get_pool()
    row = await pool.fetchrow(
        """
        SELECT outcome_detail FROM audit.audit_trail
        WHERE idempotency_key = $1 AND outcome_status = 'success'
        ORDER BY occurred_at DESC LIMIT 1
        """,
        idempotency_key,
    )
    if row is None or row["outcome_detail"] is None:
        return None

    detail = json.loads(row["outcome_detail"])
    return detail.get("result")
