"""Verifies the MCP Gateway is a real, working MCP server (Phase 3 verify
step in the plan). Checks: tool discovery over real MCP protocol, auth
rejection, and one authenticated round-trip tool call.

    pip install -r scripts/requirements.txt
    python scripts/mcp_smoke_test.py
"""

import asyncio
import os
import sys

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

GATEWAY_URL = os.environ.get("GATEWAY_MCP_URL", "http://localhost:8090/mcp")
GATEWAY_HEALTH_URL = os.environ.get("GATEWAY_HEALTH_URL", "http://localhost:8090")
GATEWAY_API_KEY = os.environ.get("GATEWAY_API_KEY", "dev-gateway-key-change-me")

EXPECTED_TOOLS = {
    "get_customer_usage",
    "get_customer_profile",
    "get_order_eligibility",
    "get_catalog",
    "propose_order",
    "submit_order",
    "create_case",
}


async def check_auth_rejected() -> bool:
    async with httpx.AsyncClient() as client:
        resp = await client.post(f"{GATEWAY_URL}", headers={}, json={})
        if resp.status_code == 401:
            print("OK: unauthenticated request rejected with 401")
            return True
        print(f"FAIL: expected 401 without API key, got {resp.status_code}")
        return False


async def check_tools_and_call() -> bool:
    ok = True
    headers = {"x-api-key": GATEWAY_API_KEY}

    async with streamablehttp_client(GATEWAY_URL, headers=headers) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools_result = await session.list_tools()
            found = {t.name for t in tools_result.tools}
            missing = EXPECTED_TOOLS - found
            if missing:
                print(f"FAIL: missing tools from tools/list: {missing}")
                ok = False
            else:
                print(f"OK: all {len(EXPECTED_TOOLS)} expected tools advertised: {sorted(found)}")

            result = await session.call_tool(
                "get_customer_usage",
                arguments={"customer_id": "CUST-1001", "thread_id": "smoke-test"},
            )
            print(f"OK: get_customer_usage call returned: {result.content}")

    return ok


async def main() -> bool:
    results = [
        await check_auth_rejected(),
        await check_tools_and_call(),
    ]
    return all(results)


if __name__ == "__main__":
    passed = asyncio.run(main())
    sys.exit(0 if passed else 1)
