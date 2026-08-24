import os

import httpx

BLUEMARBLE_BASE_URL = os.environ.get("BLUEMARBLE_BASE_URL", "http://mock-bluemarble:8081")
SALESFORCE_BASE_URL = os.environ.get("SALESFORCE_BASE_URL", "http://mock-salesforce:8082")

_bluemarble_client: httpx.AsyncClient | None = None
_salesforce_client: httpx.AsyncClient | None = None


def bluemarble_client() -> httpx.AsyncClient:
    global _bluemarble_client
    if _bluemarble_client is None:
        _bluemarble_client = httpx.AsyncClient(base_url=BLUEMARBLE_BASE_URL, timeout=10.0)
    return _bluemarble_client


def salesforce_client() -> httpx.AsyncClient:
    global _salesforce_client
    if _salesforce_client is None:
        _salesforce_client = httpx.AsyncClient(base_url=SALESFORCE_BASE_URL, timeout=10.0)
    return _salesforce_client


async def close_clients() -> None:
    global _bluemarble_client, _salesforce_client
    if _bluemarble_client is not None:
        await _bluemarble_client.aclose()
        _bluemarble_client = None
    if _salesforce_client is not None:
        await _salesforce_client.aclose()
        _salesforce_client = None
