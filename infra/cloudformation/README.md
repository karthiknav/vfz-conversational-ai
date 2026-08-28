# CloudFormation deployment — EKS orchestrator + ECS Fargate gateway-mcp + CloudFront/S3 UI

Ten independent stacks, wired together via `Fn::ImportValue`. Each stack's
`EnvironmentName` parameter defaults to `vfz-poc` — keep it consistent across
all stacks in one environment, since several templates default their
cross-stack `*StackName` parameters assuming CloudFormation stack names of
the form `vfz-<concern>` (e.g. `vfz-network`, `vfz-data`). Region: pick one
with Bedrock model access (the app defaults to `eu-west-1`).

## Deploy order

Note: this corrects one ordering issue implied by treating "app-secrets"
as a single upfront step — `GATEWAY_MCP_URL` can only be known once
gateway-mcp's ALB exists, so that specific value is published as an SSM
parameter **by** `gateway-services.yaml` itself, not by `app-secrets.yaml`.

```
1. network.yaml
2. eks-cluster.yaml            (parallel with 3)
3. gateway-ecs-cluster.yaml    (parallel with 2)
4. eks-nodegroup.yaml, data.yaml, ecr.yaml, app-secrets.yaml   (parallel, all depend only on 1-3)
   -- build & push all 4 images to the ECR repos from step 4 --
5. gateway-services.yaml       (creates the GATEWAY_MCP_URL SSM parameter as an output)
6. irsa-roles.yaml             (needs LoadBalancerControllerPolicyArn — see below)
   -- cluster bootstrap (Helm, not CloudFormation) --
7. apply infra/k8s/orchestrator/ manifests
   -- note the Ingress's ALB hostname --
8. ui.yaml
   -- build UI with ORCHESTRATOR_BASE_URL injected, sync dist/ to the S3 bucket --
```

Example, per stack:

```bash
aws cloudformation deploy \
  --stack-name vfz-network \
  --template-file network.yaml \
  --parameter-overrides EnvironmentName=vfz-poc
```

Repeat for each template, passing the same `EnvironmentName` and any
stack-name parameters that differ from the defaults.

Before step 6, create the AWS Load Balancer Controller's IAM policy once
(it's AWS-maintained, not hand-copied into this repo):

```bash
curl -o iam_policy.json https://raw.githubusercontent.com/kubernetes-sigs/aws-load-balancer-controller/main/docs/install/iam_policy.json
aws iam create-policy --policy-name AWSLoadBalancerControllerIAMPolicy --policy-document file://iam_policy.json
# pass the resulting ARN as irsa-roles.yaml's LoadBalancerControllerPolicyArn parameter
```

Before step 4's image push, authenticate and push:

```bash
aws ecr get-login-password --region <region> | docker login --username AWS --password-stdin <account>.dkr.ecr.<region>.amazonaws.com
docker build -t <orchestrator-repo-uri>:latest services/orchestrator && docker push <orchestrator-repo-uri>:latest
# repeat for gateway-mcp, mock-bluemarble, mock-salesforce
```

## Cluster bootstrap (Helm, between steps 6 and 7)

```bash
aws eks update-kubeconfig --name vfz-poc-orchestrator --region <region>

helm repo add eks https://aws.github.io/eks-charts && helm repo update
helm install aws-load-balancer-controller eks/aws-load-balancer-controller \
  -n kube-system \
  --set clusterName=vfz-poc-orchestrator \
  --set serviceAccount.create=true \
  --set serviceAccount.name=aws-load-balancer-controller \
  --set serviceAccount.annotations."eks\.amazonaws\.com/role-arn"=<irsa-roles LoadBalancerControllerRoleArn output>

helm repo add secrets-store-csi-driver https://kubernetes-sigs.github.io/secrets-store-csi-driver/charts
helm install csi-secrets-store secrets-store-csi-driver/secrets-store-csi-driver -n kube-system
kubectl apply -f https://raw.githubusercontent.com/aws/secrets-store-csi-driver-provider-aws/main/deployment/aws-provider-installer.yaml

helm repo add metrics-server https://kubernetes-sigs.github.io/metrics-server/
helm install metrics-server metrics-server/metrics-server -n kube-system
```

## Applying the orchestrator manifests (step 7)

`infra/k8s/orchestrator/*.yaml` contain `__PLACEHOLDER__` tokens filled in
from CloudFormation outputs. Simplest approach — `envsubst`:

```bash
export ORCHESTRATOR_IRSA_ROLE_ARN=<irsa-roles OrchestratorRoleArn output>
export AWS_REGION=<region>
export ECR_ORCHESTRATOR_IMAGE_URI=<ecr OrchestratorRepoUri output>:latest
export BEDROCK_GUARDRAIL_ID=<observability guardrail id, or blank>
export DB_ENDPOINT=<data DbEndpoint output>
export DB_PORT=<data DbPort output>
export UI_CLOUDFRONT_URL=<ui UiUrl output>   # only known after step 8 — see note below

for f in infra/k8s/orchestrator/*.yaml; do
  envsubst < "$f" | sed \
    -e "s#__ORCHESTRATOR_IRSA_ROLE_ARN__#$ORCHESTRATOR_IRSA_ROLE_ARN#" \
    -e "s#__AWS_REGION__#$AWS_REGION#" \
    -e "s#__ECR_ORCHESTRATOR_IMAGE_URI__#$ECR_ORCHESTRATOR_IMAGE_URI#" \
    -e "s#__BEDROCK_GUARDRAIL_ID__#$BEDROCK_GUARDRAIL_ID#" \
    -e "s#__DB_ENDPOINT__#$DB_ENDPOINT#" \
    -e "s#__DB_PORT__#$DB_PORT#" \
    -e "s#__UI_CLOUDFRONT_URL__#$UI_CLOUDFRONT_URL#" \
    | kubectl apply -f -
done
```

`UI_CLOUDFRONT_URL` isn't known until after `ui.yaml` deploys (step 8), and
`ui.yaml`'s build in turn needs the orchestrator's Ingress ALB hostname
(known only after this step) — so in practice: apply the manifests once
with `ALLOWED_ORIGINS` blank, deploy `ui.yaml`, then re-run this loop with
`UI_CLOUDFRONT_URL` set and `kubectl apply` again (idempotent, only patches
the Deployment's env).

## Verification

See the "Verification" section of the approved plan
(`i-want-to-use-crispy-cookie.md`) for the full checklist: pod health, ALB
health checks, checkpointer persistence across a pod restart, the
`scripts/mcp_smoke_test.py` run against the deployed orchestrator, mock
unreachability from outside the gateway ECS cluster, and an end-to-end
chat + approve flow through the CloudFront URL.
