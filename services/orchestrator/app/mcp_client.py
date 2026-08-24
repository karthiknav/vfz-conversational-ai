"""MCP client wrapper. Connects to the Gateway's real MCP server over
streamable HTTP and exposes least-privilege tool subsets per agent — this is
where the "Transactional Agent physically cannot call submit_order" property
actually comes from: it is simply never given that tool.
"""

import os

from langchain_mcp_adapters.client import MultiServerMCPClient

GATEWAY_URL = os.environ.get("GATEWAY_MCP_URL", "http://gateway-mcp:8090/mcp")
GATEWAY_API_KEY = os.environ["GATEWAY_API_KEY"]

KNOWLEDGE_TOOLS = {"get_customer_usage", "get_customer_profile"}
TRANSACTIONAL_TOOLS = {"get_catalog", "propose_order"}
GOVERNANCE_TOOLS = {"get_order_eligibility", "submit_order", "create_case"}

_client: MultiServerMCPClient | None = None


def _client_config() -> dict:
    return {
        "gateway": {
            "url": GATEWAY_URL,
            "transport": "streamable_http",
            "headers": {"x-api-key": GATEWAY_API_KEY},
        }
    }


async def get_client() -> MultiServerMCPClient:
    global _client
    if _client is None:
        _client = MultiServerMCPClient(_client_config())
    return _client


async def get_tools_for(agent_names: set[str]) -> list:
    client = await get_client()
    all_tools = await client.get_tools()
    return [t for t in all_tools if t.name in agent_names]


async def knowledge_agent_tools() -> list:
    return await get_tools_for(KNOWLEDGE_TOOLS)


async def transactional_agent_tools() -> list:
    return await get_tools_for(TRANSACTIONAL_TOOLS)


async def governance_agent_tools() -> list:
    return await get_tools_for(GOVERNANCE_TOOLS)
