"""Drives the full golden path against the orchestrator's HTTP API (Phase 4/5
verify step in the plan) — the two end-to-end gates referenced in the plan's
Verification Summary. Requires the orchestrator to have real AWS Bedrock
credentials configured (it calls Claude via Bedrock for every turn), so this
cannot run against mocked-out LLM calls; it is meant to be run against a
live docker-compose stack, then re-run unmodified against the deployed AWS
stack in the CDK phase by pointing ORCHESTRATOR_URL at the ALB/CloudFront URL.

    pip install -r scripts/requirements.txt
    python scripts/golden_path_test.py --branch auto_approve
    python scripts/golden_path_test.py --branch escalate
    python scripts/golden_path_test.py --branch partial_failure
"""

import argparse
import asyncio
import os
import sys
import uuid

import httpx

ORCHESTRATOR_URL = os.environ.get("ORCHESTRATOR_URL", "http://localhost:8000")
CUSTOMER_ID = "CUST-1001"

BRANCH_UPGRADES = {
    "auto_approve": "50GB",
    "escalate": "Unlimited",
    "partial_failure": "50GB",
}


async def run_branch(branch: str) -> bool:
    thread_id = f"golden-path-{branch}-{uuid.uuid4().hex[:6]}"
    ok = True

    async with httpx.AsyncClient(timeout=60.0) as client:
        # Turn 1 — Advise
        r1 = await client.post(f"{ORCHESTRATOR_URL}/chat", json={
            "customer_id": CUSTOMER_ID, "thread_id": thread_id,
            "message": "What's my current data usage this month?",
        })
        r1.raise_for_status()
        t1 = r1.json()
        print(f"[{branch}] Turn 1 (advise) -> phase={t1['phase']} reply={t1['reply'][:120]!r}")
        if t1["phase"] != "advise" or t1.get("pending_proposal"):
            print(f"FAIL[{branch}]: Turn 1 should be advise with no pending proposal")
            ok = False

        # Turn 2 — Configure
        target = BRANCH_UPGRADES[branch]
        r2 = await client.post(f"{ORCHESTRATOR_URL}/chat", json={
            "customer_id": CUSTOMER_ID, "thread_id": thread_id,
            "message": f"I'm close to my limit, can I upgrade to {target}?",
        })
        r2.raise_for_status()
        t2 = r2.json()
        print(f"[{branch}] Turn 2 (configure) -> phase={t2['phase']} proposal={t2.get('pending_proposal')}")
        proposal = t2.get("pending_proposal")
        if t2["phase"] != "configure" or not proposal:
            print(f"FAIL[{branch}]: Turn 2 should be configure with a pending proposal")
            return False

        # Turn 3 — Action
        r3 = await client.post(
            f"{ORCHESTRATOR_URL}/approve/{proposal['proposal_id']}",
            json={
                "thread_id": thread_id,
                "customer_id": CUSTOMER_ID,
                "simulate_failure": branch == "partial_failure",
            },
        )
        r3.raise_for_status()
        t3 = r3.json()
        print(f"[{branch}] Turn 3 (action) -> reply={t3['reply'][:200]!r} result={t3.get('result')}")

        result = t3.get("result") or {}
        expected_status = {
            "auto_approve": "success",
            "escalate": "escalated",
            "partial_failure": "success",
        }[branch]
        if result.get("status") != expected_status:
            print(f"FAIL[{branch}]: expected result.status={expected_status!r}, got {result.get('status')!r}")
            ok = False

    return ok


async def main(branches: list[str]) -> bool:
    results = [await run_branch(b) for b in branches]
    return all(results)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--branch", choices=list(BRANCH_UPGRADES) + ["all"], default="all")
    args = parser.parse_args()

    branches = list(BRANCH_UPGRADES) if args.branch == "all" else [args.branch]
    passed = asyncio.run(main(branches))
    sys.exit(0 if passed else 1)
