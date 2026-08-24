"""S3 + CloudFront for the static chat UI — the one docker-compose service
with no 1:1 AWS resource (the `ui` container is dropped entirely; see
docs/mapping.md). Deploys services/ui as-is; before running `cdk deploy`,
set ORCHESTRATOR_BASE_URL in services/ui/index.html's inline script to the
orchestrator ALB's DNS name (printed as a CfnOutput by orchestrator_stack).
"""

from aws_cdk import CfnOutput, RemovalPolicy, Stack
from aws_cdk import aws_cloudfront as cloudfront
from aws_cdk import aws_cloudfront_origins as origins
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_s3_deployment as s3_deployment
from constructs import Construct


class UiStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        bucket = s3.Bucket(
            self, "UiBucket",
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
        )

        distribution = cloudfront.Distribution(
            self, "UiDistribution",
            default_root_object="index.html",
            default_behavior=cloudfront.BehaviorOptions(
                origin=origins.S3BucketOrigin.with_origin_access_control(bucket),
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
            ),
        )

        s3_deployment.BucketDeployment(
            self, "UiDeployment",
            sources=[s3_deployment.Source.asset("../../services/ui")],
            destination_bucket=bucket,
            distribution=distribution,
            distribution_paths=["/*"],
        )

        CfnOutput(self, "UiUrl", value=f"https://{distribution.distribution_domain_name}")
