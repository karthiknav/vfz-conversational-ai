"""Salesforce-mock tools. create_case is used two ways in the golden path:
plain CRM case creation, and — when called with is_compensation=True after a
failed downstream sync — as the compensation step in the induced
partial-failure branch (plan gap #3 demo). The distinction only affects how
the resulting audit row is labeled; the write itself is identical.
"""

from app.http_clients import salesforce_client
from app.middleware.audit_logging import record_audit


def _normalize_case(raw: dict) -> dict:
    """Anti-corruption-layer normalization: real Salesforce uses a
    picklist-style Case_Status__c field; agents only ever see the flat
    canonical shape below.
    """
    return {
        "id": raw["Id"],
        "status": raw["Case_Status__c"],
        "subject": raw["Subject"],
        "customer_id": raw["CustomerId__c"],
        "reason": raw.get("Reason__c"),
    }


async def create_case(
    customer_id: str,
    subject: str,
    thread_id: str,
    reason: str | None = None,
    force_fail: bool = False,
    is_compensation: bool = False,
    correlation_order_id: str | None = None,
) -> dict:
    request_payload = {"customer_id": customer_id, "subject": subject, "reason": reason}

    try:
        resp = await salesforce_client().post(
            "/Case",
            json={
                "customer_id": customer_id,
                "subject": subject,
                "reason": reason,
                "force_fail": force_fail,
            },
        )
        resp.raise_for_status()
        case = _normalize_case(resp.json())
    except Exception as exc:
        await record_audit(
            thread_id=thread_id,
            phase="action",
            actor_agent="governance_agent",
            requested_by=customer_id,
            action_type="create_case" if not force_fail else "sync_order_to_crm",
            target_system="salesforce",
            request_payload=request_payload,
            governance_decision="not_required",
            outcome_status="failure",
            outcome_detail={"error": str(exc)},
            correlation_order_id=correlation_order_id,
        )
        raise

    await record_audit(
        thread_id=thread_id,
        phase="action",
        actor_agent="governance_agent",
        requested_by=customer_id,
        action_type="create_case",
        target_system="salesforce",
        request_payload=request_payload,
        governance_decision="not_required",
        outcome_status="partial_failure" if is_compensation else "success",
        outcome_detail={"result": case, "compensation": is_compensation},
        correlation_order_id=correlation_order_id,
        correlation_case_id=case["id"],
    )
    return case
