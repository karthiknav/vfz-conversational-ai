"""Verifies the seed data from db/init/*.sql landed correctly. Run after
`docker compose up` (Phase 2 verify step in the plan):

    pip install -r scripts/requirements.txt
    python scripts/seed_db.py --check
"""

import argparse
import asyncio
import os
import sys

import asyncpg

async def check() -> bool:
    conn = await asyncpg.connect(
        user=os.environ.get("POSTGRES_USER", "vz_poc"),
        password=os.environ.get("POSTGRES_PASSWORD", "change-me-locally"),
        host=os.environ.get("POSTGRES_HOST", "localhost"),
        port=int(os.environ.get("POSTGRES_PORT", "5432")),
        database=os.environ.get("POSTGRES_DB", "vz_poc"),
    )
    ok = True
    try:
        offerings = await conn.fetch("SELECT id, monthly_price FROM bluemarble.product_offering ORDER BY id")
        expected_offers = {"OFFER-20GB", "OFFER-50GB", "OFFER-UNLIMITED"}
        found_offers = {o["id"] for o in offerings}
        if found_offers != expected_offers:
            print(f"FAIL: expected offers {expected_offers}, found {found_offers}")
            ok = False
        else:
            print(f"OK: catalogue seeded — {[dict(o) for o in offerings]}")

        customer = await conn.fetchrow(
            "SELECT * FROM analytics.vw_customer_usage_spend WHERE customer_id = 'CUST-1001'"
        )
        if customer is None:
            print("FAIL: CUST-1001 not found in vw_customer_usage_spend")
            ok = False
        else:
            print(f"OK: customer seeded — {dict(customer)}")

        eligibility = await conn.fetchrow(
            "SELECT * FROM analytics.vw_order_eligibility WHERE customer_id = 'CUST-1001'"
        )
        if eligibility is None:
            print("FAIL: CUST-1001 not found in vw_order_eligibility")
            ok = False
        else:
            print(f"OK: eligibility view — {dict(eligibility)}")

        audit_count = await conn.fetchval("SELECT count(*) FROM audit.audit_trail")
        print(f"OK: audit_trail table reachable, {audit_count} row(s)")

    finally:
        await conn.close()
    return ok


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    if not args.check:
        parser.print_help()
        sys.exit(1)

    passed = asyncio.run(check())
    sys.exit(0 if passed else 1)
