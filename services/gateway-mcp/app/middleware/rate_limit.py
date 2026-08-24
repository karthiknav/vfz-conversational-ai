import os
import time
from collections import defaultdict

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

RATE_LIMIT_PER_MIN = int(os.environ.get("GATEWAY_RATE_LIMIT_PER_MIN", "60"))
WINDOW_SECONDS = 60

UNTHROTTLED_PATHS = {"/health"}

# In-memory fixed-window counter per API key. Good enough for a single-task
# POC; AWS phase notes this as a known scaling gap — API Gateway usage plans
# are the real mechanism once there's more than one gateway task.
_windows: dict[str, tuple[int, int]] = defaultdict(lambda: (0, 0))


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path in UNTHROTTLED_PATHS:
            return await call_next(request)

        api_key = request.headers.get("x-api-key", "anonymous")
        window_start, count = _windows[api_key]
        now = int(time.time())

        if now - window_start >= WINDOW_SECONDS:
            window_start, count = now, 0

        count += 1
        _windows[api_key] = (window_start, count)

        if count > RATE_LIMIT_PER_MIN:
            return JSONResponse({"error": "rate limit exceeded"}, status_code=429)

        return await call_next(request)
