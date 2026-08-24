"""Shared helpers for the three business-capability agent nodes: session
context gets injected into each agent's system prompt (so the LLM propagates
customer_id/thread_id into every tool call it makes) and structured tool
results get pulled back out of the resulting message list.
"""

import json

from langchain_core.messages import ToolMessage


def session_prefix(customer_id: str, thread_id: str) -> str:
    return (
        f"The current customer_id is '{customer_id}'. Always pass this exact "
        f"value as the customer_id argument to any tool you call.\n"
        f"The current thread_id is '{thread_id}'. Always pass this exact value "
        f"as the thread_id argument to any tool you call.\n\n"
    )


def extract_tool_result(messages: list, tool_name: str) -> dict | None:
    for m in reversed(messages):
        if isinstance(m, ToolMessage) and getattr(m, "name", None) == tool_name:
            content = m.content
            if isinstance(content, str):
                try:
                    return json.loads(content)
                except json.JSONDecodeError:
                    return None
            return content
    return None
