"""Langfuse tracing (Cloud, EU region — see docs/architecture-decisions.md
for why self-hosting was skipped for this thin slice). One callback handler
per request, tagged with thread_id/customer_id, so a single trace covers
router -> agent node -> MCP tool call -> Bedrock call for that turn.
"""

import os

from langfuse.callback import CallbackHandler

LANGFUSE_PUBLIC_KEY = os.environ.get("LANGFUSE_PUBLIC_KEY")
LANGFUSE_SECRET_KEY = os.environ.get("LANGFUSE_SECRET_KEY")
LANGFUSE_HOST = os.environ.get("LANGFUSE_HOST", "https://cloud.langfuse.com")


def get_callback_handler(thread_id: str, customer_id: str) -> CallbackHandler | None:
    if not (LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY):
        return None
    return CallbackHandler(
        public_key=LANGFUSE_PUBLIC_KEY,
        secret_key=LANGFUSE_SECRET_KEY,
        host=LANGFUSE_HOST,
        session_id=thread_id,
        user_id=customer_id,
    )
