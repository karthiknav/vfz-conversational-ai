"""VPC + ECS cluster + Cloud Map namespace shared by every service stack.
One NAT gateway — needed only for Langfuse Cloud egress and ECR pulls from
private subnets (see docs/architecture-decisions.md ADR-6 on why Langfuse
isn't self-hosted). Everything else (Bedrock, Secrets Manager) reaches AWS
services via VPC interface endpoints, not NAT.
"""

from aws_cdk import Stack
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_ecs as ecs
from aws_cdk import aws_servicediscovery as servicediscovery
from constructs import Construct


class NetworkStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.vpc = ec2.Vpc(
            self, "VzPocVpc",
            max_azs=2,
            nat_gateways=1,
            subnet_configuration=[
                ec2.SubnetConfiguration(name="public", subnet_type=ec2.SubnetType.PUBLIC, cidr_mask=24),
                ec2.SubnetConfiguration(name="private", subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS, cidr_mask=24),
            ],
        )

        # Bedrock reached over a VPC interface endpoint, not the NAT gateway —
        # keeps model-invoke latency and egress cost off the NAT path.
        self.vpc.add_interface_endpoint(
            "BedrockRuntimeEndpoint",
            service=ec2.InterfaceVpcEndpointAwsService.BEDROCK_RUNTIME,
        )
        self.vpc.add_interface_endpoint(
            "SecretsManagerEndpoint",
            service=ec2.InterfaceVpcEndpointAwsService.SECRETS_MANAGER,
        )

        self.cluster = ecs.Cluster(self, "VzPocCluster", vpc=self.vpc, container_insights=True)

        self.namespace = servicediscovery.PrivateDnsNamespace(
            self, "VzPocNamespace", name="vz-poc.local", vpc=self.vpc,
        )
