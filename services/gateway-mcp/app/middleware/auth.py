import os

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

GATEWAY_API_KEY = os.environ["GATEWAY_API_KEY"]

# Paths any caller may reach without a key — infra health checks only.
UNAUTHENTICATED_PATHS = {"/health"}


class APIKeyAuthMiddleware(BaseHTTPMiddleware):
    """Dummy-but-real API-key check standing in for the RFP's AuthN/AuthZ
    box. In the AWS phase this is where an IAM-authenticated ALB/API Gateway
    call, or a real OAuth2 client-credentials check, would slot in — the
    downstream MCP tool code never needs to change.
    """

    async def dispatch(self, request: Request, call_next):
        if request.url.path in UNAUTHENTICATED_PATHS:
            return await call_next(request)

        api_key = request.headers.get("x-api-key")
        if api_key != GATEWAY_API_KEY:
            return JSONResponse({"error": "unauthorized"}, status_code=401)

        return await call_next(request)
