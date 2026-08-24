"""Shared governance/observability resources consumed by other stacks: the
Bedrock Guardrail (content moderation + PII handling on every LLM call, via
orchestrator/app/bedrock.py's guardrail_config) and the app-level secrets
that don't belong to any one service (Gateway API key, Langfuse keys).
Per-service CloudWatch log groups are created inline in each service's own
stack via ecs.LogDrivers.aws_logs, not centralized here.
"""

from aws_cdk import Stack
from aws_cdk import aws_bedrock as bedrock
from aws_cdk import aws_secretsmanager as secretsmanager
from constructs import Construct


class ObservabilityStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.gateway_api_key_secret = secretsmanager.Secret(
            self, "GatewayApiKeySecret",
            generate_secret_string=secretsmanager.SecretStringGenerator(exclude_punctuation=True, password_length=32),
        )

        self.langfuse_secret = secretsmanager.Secret(
            self, "LangfuseSecret",
            description="Langfuse Cloud (EU) public_key/secret_key — populate manually after cdk deploy",
        )

        self.guardrail = bedrock.CfnGuardrail(
            self, "VzPocGuardrail",
            name="vz-poc-guardrail",
            blocked_input_messaging="I can't help with that request.",
            blocked_outputs_messaging="I can't share that.",
            content_policy_config=bedrock.CfnGuardrail.ContentPolicyConfigProperty(
                filters_config=[
                    bedrock.CfnGuardrail.ContentFilterConfigProperty(
                        type=t, input_strength="HIGH", output_strength="HIGH",
                    )
                    for t in ["PROMPT_ATTACK", "INSULTS", "HATE", "SEXUAL", "VIOLENCE", "MISCONDUCT"]
                ]
            ),
            sensitive_information_policy_config=bedrock.CfnGuardrail.SensitiveInformationPolicyConfigProperty(
                pii_entities_config=[
                    bedrock.CfnGuardrail.PiiEntityConfigProperty(type=t, action="ANONYMIZE")
                    for t in ["EMAIL", "PHONE", "NAME", "ADDRESS", "CREDIT_DEBIT_CARD_NUMBER"]
                ]
            ),
        )
