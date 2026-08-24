"""ECS Fargate service for gateway-mcp behind an internal ALB. Internal ALB
is the pragmatic POC choice; API Gateway + VPC Link is the closer 1:1 to the
RFP's "API Catalogue + SLA Lifecycle" sub-box — documented as a stretch
upgrade in docs/mapping.md, not built here.
"""

from aws_cdk import Duration, Stack
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_ecs as ecs
from aws_cdk import aws_ecs_patterns as ecs_patterns
from aws_cdk import aws_iam as iam
from aws_cdk import aws_logs as logs
from aws_cdk import aws_rds as rds
from aws_cdk import aws_secretsmanager as secretsmanager
from constructs import Construct


class GatewayStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        cluster: ecs.Cluster,
        db_cluster: rds.DatabaseCluster,
        db_security_group: ec2.SecurityGroup,
        gateway_api_key_secret: secretsmanager.ISecret,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        task_def = ecs.FargateTaskDefinition(self, "GatewayTaskDef", cpu=512, memory_limit_mib=1024)

        # Deny bedrock:InvokeModel on this role explicitly — spot-checked in
        # Phase 8 verify step. The Gateway talks to the mocks and Postgres
        # only; it has no business calling Bedrock.
        task_def.task_role.add_to_principal_policy(
            iam.PolicyStatement(
                effect=iam.Effect.DENY,
                actions=["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
                resources=["*"],
            )
        )

        task_def.add_container(
            "GatewayContainer",
            image=ecs.ContainerImage.from_asset("../../services/gateway-mcp"),
            logging=ecs.LogDrivers.aws_logs(stream_prefix="gateway-mcp", log_retention=logs.RetentionDays.ONE_WEEK),
            port_mappings=[ecs.PortMapping(container_port=8090)],
            environment={
                "POSTGRES_HOST": db_cluster.cluster_endpoint.hostname,
                "POSTGRES_PORT": str(db_cluster.cluster_endpoint.port),
                "POSTGRES_DB": "vz_poc",
                "BLUEMARBLE_BASE_URL": "http://mock-bluemarble.vz-poc.local:8081",
                "SALESFORCE_BASE_URL": "http://mock-salesforce.vz-poc.local:8082",
                "GATEWAY_RATE_LIMIT_PER_MIN": "60",
            },
            secrets={
                "POSTGRES_USER": ecs.Secret.from_secrets_manager(db_cluster.secret, field="username"),
                "POSTGRES_PASSWORD": ecs.Secret.from_secrets_manager(db_cluster.secret, field="password"),
                "GATEWAY_API_KEY": ecs.Secret.from_secrets_manager(gateway_api_key_secret),
            },
        )

        self.service = ecs_patterns.ApplicationLoadBalancedFargateService(
            self, "GatewayFargateService",
            cluster=cluster,
            task_definition=task_def,
            desired_count=1,
            public_load_balancer=False,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS),
            health_check_grace_period=Duration.seconds(30),
        )
        self.service.target_group.configure_health_check(path="/health")

        db_security_group.add_ingress_rule(
            self.service.service.connections.security_groups[0], ec2.Port.tcp(5432), "Gateway -> Aurora",
        )
