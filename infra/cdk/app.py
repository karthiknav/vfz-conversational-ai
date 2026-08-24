#!/usr/bin/env python3
"""CDK app — deploys the same services as docker-compose.yml to AWS. See
docs/mapping.md for the compose-service -> AWS-resource table this follows.

    cd infra/cdk
    python -m venv .venv && .venv/Scripts/activate  (or source .venv/bin/activate)
    pip install -r requirements.txt
    cdk bootstrap   # first time only, per account/region
    cdk deploy --all

Requires BEDROCK_MODEL_ID env var (or defaults to the same model as local),
and the AWS CLI configured with credentials that have deploy permissions.
After deploy, populate the LangfuseSecret in Secrets Manager manually with
your Langfuse Cloud public_key/secret_key, and set
services/ui/index.html's ORCHESTRATOR_BASE_URL to the printed orchestrator
ALB URL before (re-)deploying the UiStack.
"""

import os

import aws_cdk as cdk

from stacks.data_stack import DataStack
from stacks.gateway_stack import GatewayStack
from stacks.mocks_stack import MocksStack
from stacks.network_stack import NetworkStack
from stacks.observability_stack import ObservabilityStack
from stacks.orchestrator_stack import OrchestratorStack
from stacks.ui_stack import UiStack

app = cdk.App()

env = cdk.Environment(
    account=os.environ.get("CDK_DEFAULT_ACCOUNT"),
    region=os.environ.get("CDK_DEFAULT_REGION", "eu-west-1"),
)

bedrock_model_id = os.environ.get("BEDROCK_MODEL_ID", "anthropic.claude-3-5-sonnet-20241022-v2:0")

network = NetworkStack(app, "VzPoc-Network", env=env)
observability = ObservabilityStack(app, "VzPoc-Observability", env=env)
data = DataStack(app, "VzPoc-Data", vpc=network.vpc, env=env)

mocks = MocksStack(
    app, "VzPoc-Mocks",
    cluster=network.cluster,
    namespace=network.namespace,
    db_cluster=data.cluster,
    db_security_group=data.db_security_group,
    env=env,
)
mocks.add_dependency(data)

gateway = GatewayStack(
    app, "VzPoc-Gateway",
    cluster=network.cluster,
    db_cluster=data.cluster,
    db_security_group=data.db_security_group,
    gateway_api_key_secret=observability.gateway_api_key_secret,
    env=env,
)
gateway.add_dependency(mocks)

gateway_url = f"http://{gateway.service.load_balancer.load_balancer_dns_name}/mcp"

orchestrator = OrchestratorStack(
    app, "VzPoc-Orchestrator",
    cluster=network.cluster,
    gateway_url=gateway_url,
    gateway_api_key_secret=observability.gateway_api_key_secret,
    langfuse_secret=observability.langfuse_secret,
    bedrock_model_id=bedrock_model_id,
    bedrock_guardrail_id=observability.guardrail.attr_guardrail_id,
    env=env,
)
orchestrator.add_dependency(gateway)

ui = UiStack(app, "VzPoc-Ui", env=env)

app.synth()
