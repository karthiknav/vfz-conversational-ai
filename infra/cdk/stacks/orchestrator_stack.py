"""ECS Fargate service for the orchestrator behind a public ALB — this is
the only service the UI (and end users) can reach. Task role is scoped to
Bedrock InvokeModel/Guardrails only: no RDS grant, no direct network path to
the mocks. Everything the orchestrator needs from the data layer goes
through the Gateway over MCP, same as in docker-compose.
"""

from aws_cdk import Duration, Stack
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_ecs as ecs
from aws_cdk import aws_ecs_patterns as ecs_patterns
from aws_cdk import aws_iam as iam
from aws_cdk import aws_logs as logs
from aws_cdk import aws_secretsmanager as secretsmanager
from constructs import Construct


class OrchestratorStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        cluster: ecs.Cluster,
        gateway_url: str,
        gateway_api_key_secret: secretsmanager.ISecret,
        langfuse_secret: secretsmanager.ISecret,
        bedrock_model_id: str,
        bedrock_guardrail_id: str,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        task_def = ecs.FargateTaskDefinition(self, "OrchestratorTaskDef", cpu=1024, memory_limit_mib=2048)

        task_def.task_role.add_to_principal_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream", "bedrock:ApplyGuardrail"],
                resources=[
                    f"arn:aws:bedrock:{self.region}::foundation-model/{bedrock_model_id}",
                    f"arn:aws:bedrock:{self.region}:{self.account}:guardrail/{bedrock_guardrail_id}",
                ],
            )
        )

        task_def.add_container(
            "OrchestratorContainer",
            image=ecs.ContainerImage.from_asset("../../services/orchestrator"),
            logging=ecs.LogDrivers.aws_logs(stream_prefix="orchestrator", log_retention=logs.RetentionDays.ONE_WEEK),
            port_mappings=[ecs.PortMapping(container_port=8000)],
            environment={
                "GATEWAY_MCP_URL": gateway_url,
                "AWS_REGION": self.region,
                "BEDROCK_MODEL_ID": bedrock_model_id,
                "BEDROCK_GUARDRAIL_ID": bedrock_guardrail_id,
                "BEDROCK_GUARDRAIL_VERSION": "DRAFT",
                "LANGFUSE_HOST": "https://cloud.langfuse.com",
                "GOVERNANCE_AUTO_APPROVE_DELTA_EUR": "15.00",
            },
            secrets={
                "GATEWAY_API_KEY": ecs.Secret.from_secrets_manager(gateway_api_key_secret),
                "LANGFUSE_PUBLIC_KEY": ecs.Secret.from_secrets_manager(langfuse_secret, field="public_key"),
                "LANGFUSE_SECRET_KEY": ecs.Secret.from_secrets_manager(langfuse_secret, field="secret_key"),
            },
        )

        self.service = ecs_patterns.ApplicationLoadBalancedFargateService(
            self, "OrchestratorFargateService",
            cluster=cluster,
            task_definition=task_def,
            desired_count=1,
            public_load_balancer=True,
            health_check_grace_period=Duration.seconds(30),
        )
        self.service.target_group.configure_health_check(path="/health")
