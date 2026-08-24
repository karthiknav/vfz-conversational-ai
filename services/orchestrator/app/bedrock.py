"""Bedrock (Claude) LLM wrapper, with Bedrock Guardrails wired on both input
and output when a guardrail ID is configured. Every agent node imports
get_llm() rather than constructing its own client, so the guardrail
attachment and model choice stay in one place.
"""

import os

from langchain_aws import ChatBedrockConverse

AWS_REGION = os.environ.get("AWS_REGION", "eu-west-1")
MODEL_ID = os.environ.get("BEDROCK_MODEL_ID", "anthropic.claude-3-5-sonnet-20241022-v2:0")
GUARDRAIL_ID = os.environ.get("BEDROCK_GUARDRAIL_ID") or None
GUARDRAIL_VERSION = os.environ.get("BEDROCK_GUARDRAIL_VERSION", "DRAFT")

_llm: ChatBedrockConverse | None = None


def get_llm() -> ChatBedrockConverse:
    global _llm
    if _llm is None:
        kwargs = dict(model=MODEL_ID, region_name=AWS_REGION, temperature=0)
        if GUARDRAIL_ID:
            kwargs["guardrail_config"] = {
                "guardrailIdentifier": GUARDRAIL_ID,
                "guardrailVersion": GUARDRAIL_VERSION,
                "trace": "enabled",
            }
        _llm = ChatBedrockConverse(**kwargs)
    return _llm
