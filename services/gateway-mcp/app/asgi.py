"""Outer ASGI app: owns AuthN, rate limiting, and health checks as ordinary
middleware, then mounts the real MCP protocol server as a sub-app. This
split exists because the MCP SDK's own middleware ergonomics are thin — the
cross-cutting Gateway concerns belong in code we control directly, not
fought into the protocol server object. See docs/architecture-decisions.md.
"""

from contextlib import AsyncExitStack, asynccontextmanager

from fastapi import FastAPI
from starlette.routing import Mount

from app.db import close_pool, get_pool
from app.http_clients import close_clients
from app.mcp_server import mcp
from app.middleware.auth import APIKeyAuthMiddleware
from app.middleware.rate_limit import RateLimitMiddleware

mcp_app = mcp.streamable_http_app()


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with AsyncExitStack() as stack:
        await get_pool()
        await stack.enter_async_context(mcp.session_manager.run())
        yield
    await close_pool()
    await close_clients()


app = FastAPI(title="VZ MCP Gateway", lifespan=lifespan)

app.add_middleware(RateLimitMiddleware)
app.add_middleware(APIKeyAuthMiddleware)

app.router.routes.append(Mount("/", app=mcp_app))


@app.get("/health")
async def health():
    return {"status": "ok"}
