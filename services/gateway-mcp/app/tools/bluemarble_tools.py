"""Bluemarble-mock tools. get_catalog and propose_order are pure reads —
propose_order builds a proposal object and never writes anything. submit_order
is the one write path, and is the concrete implementation of the RFP's
"AI can request, platform decides execution" principle: it independently
re-derives the price delta and eligibility server-side and enforces the
governance threshold itself, rather than trusting a decision claimed by the
calling LLM agent. It is the only tool in this Gateway bound to the
Governance Agent's LangGraph node.
"""

import os
import uuid

from app.db import get_pool
from app.http_clients import bluemarble_client
from app.middleware.audit_logging import record_audit
from app.middleware.idempotency import check_cached_result

AUTO_APPROVE_DELTA_EUR = float(os.environ.get("GOVERNANCE_AUTO_APPROVE_DELTA_EUR", "15.00"))


def _normalize_offering(raw: dict) -> dict:
    """Anti-corruption-layer normalization: real TMF622 nests price under
    productOfferingPrice[0].price.taxIncludedAmount.value — agents only ever
    see the flat canonical shape below.
    """
    price = raw["productOfferingPrice"][0]["price"]["taxIncludedAmount"]["value"]
    return {
        "id": raw["id"],
        "name": raw["name"],
        "monthlyPriceEur": price,
        "dataAllowanceGb": raw.get("dataAllowanceGb"),
    }


async def get_catalog(thread_id: str) -> dict:
    """List available mobile plan offerings (Configure tier)."""
    resp = await bluemarble_client().get("/catalog")
    resp.raise_for_status()
    offerings = [_normalize_offering(o) for o in resp.json()["productOffering"]]

    await record_audit(
        thread_id=thread_id,
        phase="configure",
        actor_agent="transactional_agent",
        requested_by="system",
        action_type="get_catalog",
        target_system="bluemarble",
        outcome_status="success",
        outcome_detail={"result": {"offerings": offerings}},
    )
    return {"offerings": offerings}


async def _current_and_target_price(customer_id: str, target_offer_id: str) -> tuple[float, dict]:
    pool = await get_pool()
    current = await pool.fetchrow(
        "SELECT spend_current_month FROM analytics.vw_customer_usage_spend WHERE customer_id = $1",
        customer_id,
    )
    if current is None:
        raise ValueError(f"Unknown customer {customer_id}")

    resp = await bluemarble_client().get("/catalog")
    resp.raise_for_status()
    offerings = {o["id"]: _normalize_offering(o) for o in resp.json()["productOffering"]}
    target = offerings.get(target_offer_id)
    if target is None:
        raise ValueError(f"Unknown offer {target_offer_id}")

    return float(current["spend_current_month"]), target


async def propose_order(customer_id: str, target_offer_id: str, thread_id: str) -> dict:
    """Build a proposed upgrade — reads only, executes nothing.
    Configure-tier: propose, don't commit.
    """
    current_price, target = await _current_and_target_price(customer_id, target_offer_id)
    delta = round(target["monthlyPriceEur"] - current_price, 2)
    proposal_id = f"PROP-{uuid.uuid4().hex[:6].upper()}"

    proposal = {
        "proposal_id": proposal_id,
        "customer_id": customer_id,
        "target_offer_id": target_offer_id,
        "target_offer_name": target["name"],
        "target_monthly_price_eur": target["monthlyPriceEur"],
        "current_monthly_price_eur": current_price,
        "delta_eur": delta,
    }

    await record_audit(
        thread_id=thread_id,
        phase="configure",
        actor_agent="transactional_agent",
        requested_by=customer_id,
        action_type="propose_order",
        target_system="bluemarble",
        request_payload={"customer_id": customer_id, "target_offer_id": target_offer_id},
        outcome_status="success",
        outcome_detail={"result": proposal},
    )
    return proposal


async def submit_order(
    customer_id: str, target_offer_id: str, idempotency_key: str, thread_id: str
) -> dict:
    """Execute an approved upgrade. The only write tool in this module —
    bound exclusively to the Governance Agent's node. Independently
    re-verifies eligibility and the price-delta policy threshold before
    doing anything; a caller claiming "approved" does not skip this check.
    """
    cached = await check_cached_result(idempotency_key)
    if cached is not None:
        return cached

    pool = await get_pool()
    eligibility = await pool.fetchrow(
        "SELECT upgrade_eligible, outstanding_balance, credit_flag FROM analytics.vw_order_eligibility WHERE customer_id = $1",
        customer_id,
    )
    if eligibility is None:
        raise ValueError(f"Unknown customer {customer_id}")

    current_price, target = await _current_and_target_price(customer_id, target_offer_id)
    delta = round(target["monthlyPriceEur"] - current_price, 2)

    request_payload = {
        "customer_id": customer_id,
        "target_offer_id": target_offer_id,
        "idempotency_key": idempotency_key,
    }

    if not eligibility["upgrade_eligible"] or eligibility["outstanding_balance"] > 0 or eligibility["credit_flag"] != "green":
        reason = "not eligible: failed credit/outstanding-balance/eligibility check"
        await record_audit(
            thread_id=thread_id, phase="action", actor_agent="governance_agent",
            requested_by=customer_id, action_type="submit_order", target_system="bluemarble",
            idempotency_key=None, request_payload=request_payload,
            governance_decision="blocked", governance_reason=reason,
            outcome_status="success", outcome_detail={"delta_eur": delta},
        )
        return {"status": "blocked", "reason": reason}

    if delta > AUTO_APPROVE_DELTA_EUR:
        reason = f"price delta EUR {delta} exceeds auto-approve threshold EUR {AUTO_APPROVE_DELTA_EUR}"
        await record_audit(
            thread_id=thread_id, phase="action", actor_agent="governance_agent",
            requested_by=customer_id, action_type="submit_order", target_system="bluemarble",
            idempotency_key=None, request_payload=request_payload,
            governance_decision="escalated", governance_reason=reason,
            outcome_status="success", outcome_detail={"delta_eur": delta},
        )
        return {"status": "escalated", "reason": reason}

    try:
        resp = await bluemarble_client().post(
            "/productOrderingManagement/v4/productOrder",
            json={"customer_id": customer_id, "product_offering_id": target_offer_id},
        )
        resp.raise_for_status()
        order = resp.json()
    except Exception as exc:
        await record_audit(
            thread_id=thread_id, phase="action", actor_agent="governance_agent",
            requested_by=customer_id, action_type="submit_order", target_system="bluemarble",
            idempotency_key=None, request_payload=request_payload,
            governance_decision="approved", governance_reason="policy passed, execution failed",
            outcome_status="failure", outcome_detail={"error": str(exc)},
        )
        raise

    result = {"status": "success", "order": order}
    await record_audit(
        thread_id=thread_id, phase="action", actor_agent="governance_agent",
        requested_by=customer_id, action_type="submit_order", target_system="bluemarble",
        idempotency_key=idempotency_key, request_payload=request_payload,
        governance_decision="approved", governance_reason="within auto-approve threshold",
        outcome_status="success", outcome_detail={"result": result},
        correlation_order_id=order["id"],
    )
    return result
