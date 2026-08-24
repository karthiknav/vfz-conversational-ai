"""Aurora PostgreSQL Serverless v2 — the single shared instance behind
bluemarble.*/salesforce.*/analytics.*/audit.* schemas, mapping 1:1 to the
docker-compose `db` service (see docs/architecture-decisions.md ADR-3).
Also adds a langgraph_checkpoints schema hook point for swapping
MemorySaver -> AsyncPostgresSaver in the orchestrator (graph.py).
"""

from aws_cdk import RemovalPolicy, Stack
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_rds as rds
from constructs import Construct


class DataStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, *, vpc: ec2.Vpc, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.db_security_group = ec2.SecurityGroup(
            self, "DbSecurityGroup", vpc=vpc, description="Aurora Postgres — VZ POC", allow_all_outbound=False,
        )

        self.cluster = rds.DatabaseCluster(
            self, "VzPocDb",
            engine=rds.DatabaseClusterEngine.aurora_postgres(version=rds.AuroraPostgresEngineVersion.VER_16_4),
            writer=rds.ClusterInstance.serverless_v2("writer"),
            serverless_v2_min_capacity=0.5,
            serverless_v2_max_capacity=4,
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS),
            security_groups=[self.db_security_group],
            default_database_name="vz_poc",
            removal_policy=RemovalPolicy.DESTROY,  # POC only — never for a production cluster
        )

        # Populated by RDS-generated Secrets Manager secret automatically;
        # exposed here so service stacks can grant read access + wire env vars.
        self.secret = self.cluster.secret
