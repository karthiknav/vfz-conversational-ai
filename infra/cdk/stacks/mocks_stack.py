"""ECS Fargate services for mock-bluemarble and mock-salesforce — no ALB,
reached only via Cloud Map private DNS from the Gateway, exactly as the
docker-compose services are reached only by service name on the compose
network. 0.25 vCPU / 512MB each, matching the plan's "pattern-proven, not
scale-tested" framing.
"""

from aws_cdk import Duration, Stack
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_ecs as ecs
from aws_cdk import aws_logs as logs
from aws_cdk import aws_rds as rds
from aws_cdk import aws_secretsmanager as secretsmanager
from aws_cdk import aws_servicediscovery as servicediscovery
from constructs import Construct


def _mock_service(
    scope: Construct,
    id_prefix: str,
    *,
    cluster: ecs.Cluster,
    namespace: servicediscovery.PrivateDnsNamespace,
    db_host: str,
    db_port: str,
    db_secret: secretsmanager.ISecret,
    db_security_group: ec2.SecurityGroup,
    build_context: str,
    container_port: int,
    cloud_map_name: str,
) -> ecs.FargateService:
    task_def = ecs.FargateTaskDefinition(scope, f"{id_prefix}TaskDef", cpu=256, memory_limit_mib=512)

    container = task_def.add_container(
        f"{id_prefix}Container",
        image=ecs.ContainerImage.from_asset(build_context),
        logging=ecs.LogDrivers.aws_logs(stream_prefix=id_prefix, log_retention=logs.RetentionDays.ONE_WEEK),
        environment={
            "POSTGRES_HOST": db_host,
            "POSTGRES_PORT": db_port,
            "POSTGRES_DB": "vz_poc",
        },
        secrets={
            "POSTGRES_USER": ecs.Secret.from_secrets_manager(db_secret, field="username"),
            "POSTGRES_PASSWORD": ecs.Secret.from_secrets_manager(db_secret, field="password"),
        },
    )
    container.add_port_mappings(ecs.PortMapping(container_port=container_port))

    service_sg = ec2.SecurityGroup(scope, f"{id_prefix}Sg", vpc=cluster.vpc, allow_all_outbound=True)
    db_security_group.add_ingress_rule(service_sg, ec2.Port.tcp(5432), f"{id_prefix} -> Aurora")

    return ecs.FargateService(
        scope, f"{id_prefix}Service",
        cluster=cluster,
        task_definition=task_def,
        desired_count=1,
        security_groups=[service_sg],
        vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS),
        cloud_map_options=ecs.CloudMapOptions(
            cloud_map_namespace=namespace, name=cloud_map_name, dns_ttl=Duration.seconds(10),
        ),
    )


class MocksStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        cluster: ecs.Cluster,
        namespace: servicediscovery.PrivateDnsNamespace,
        db_cluster: rds.DatabaseCluster,
        db_security_group: ec2.SecurityGroup,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        common = dict(
            cluster=cluster, namespace=namespace,
            db_host=db_cluster.cluster_endpoint.hostname,
            db_port=str(db_cluster.cluster_endpoint.port),
            db_secret=db_cluster.secret, db_security_group=db_security_group,
        )

        self.bluemarble_service = _mock_service(
            self, "MockBluemarble", build_context="../../services/mock-bluemarble",
            container_port=8081, cloud_map_name="mock-bluemarble", **common,
        )
        self.salesforce_service = _mock_service(
            self, "MockSalesforce", build_context="../../services/mock-salesforce",
            container_port=8082, cloud_map_name="mock-salesforce", **common,
        )
