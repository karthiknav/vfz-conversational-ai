# CloudFormation deployment — EKS orchestrator + ECS Fargate gateway-mcp + CloudFront/S3 UI

Ten independent stacks, wired together via `Fn::ImportValue`. Each stack's
`EnvironmentName` parameter defaults to `vfz-poc` — keep it consistent across
all stacks in one environment, since several templates default their
cross-stack `*StackName` parameters assuming CloudFormation stack names of
the form `vfz-<concern>` (e.g. `vfz-network`, `vfz-data`). Region: pick one
with Bedrock model access (the app defaults to `us-east-1`). The commands
below all assume that region and the default stack names — adjust both
consistently if you deploy elsewhere.

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

All commands below are run from `infra/cloudformation/`. Stacks that create
IAM roles need `--capabilities CAPABILITY_NAMED_IAM` (every role in these
templates sets an explicit `RoleName`); stacks that don't create IAM
resources omit it.

## Deploy instructions

### 1. network

No dependencies.

```bash
aws cloudformation deploy \
  --stack-name vfz-network \
  --template-file network.yaml \
  --parameter-overrides EnvironmentName=vfz-poc \
  --region us-east-1
```

### 2. eks-cluster (parallel with gateway-ecs-cluster)

Depends on network (VPC + EKS private subnets). Creates an IAM role, so
needs `CAPABILITY_NAMED_IAM`.

```bash
aws cloudformation deploy \
  --stack-name vfz-eks-cluster \
  --template-file eks-cluster.yaml \
  --parameter-overrides EnvironmentName=vfz-poc NetworkStackName=vfz-network \
  --capabilities CAPABILITY_NAMED_IAM \
  --region us-east-1
```

### 3. gateway-ecs-cluster (parallel with eks-cluster)

No dependencies — it's an empty ECS cluster until gateway-services.yaml
populates it.

```bash
aws cloudformation deploy \
  --stack-name vfz-gateway-ecs-cluster \
  --template-file gateway-ecs-cluster.yaml \
  --parameter-overrides EnvironmentName=vfz-poc \
  --region us-east-1
```

### 4. eks-nodegroup, data, ecr, app-secrets (parallel)

All four depend only on stacks 1–3 (or nothing) and can be deployed
concurrently.

```bash
# eks-nodegroup — depends on network + eks-cluster; creates an IAM role
aws cloudformation deploy \
  --stack-name vfz-eks-nodegroup \
  --template-file eks-nodegroup.yaml \
  --parameter-overrides EnvironmentName=vfz-poc NetworkStackName=vfz-network EksClusterStackName=vfz-eks-cluster \
  --capabilities CAPABILITY_NAMED_IAM \
  --region us-east-1

# data — depends on network + eks-cluster (for the EKS-side DB ingress rule)
aws cloudformation deploy \
  --stack-name vfz-data \
  --template-file data.yaml \
  --parameter-overrides EnvironmentName=vfz-poc NetworkStackName=vfz-network EksClusterStackName=vfz-eks-cluster \
  --region us-east-1

# ecr — no dependencies
aws cloudformation deploy \
  --stack-name vfz-ecr \
  --template-file ecr.yaml \
  --parameter-overrides EnvironmentName=vfz-poc \
  --region us-east-1

# app-secrets — no dependencies
aws cloudformation deploy \
  --stack-name vfz-app-secrets \
  --template-file app-secrets.yaml \
  --parameter-overrides EnvironmentName=vfz-poc \
  --region us-east-1
```

Once `ecr` exists, build and push all four images before continuing:

```bash
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin <account>.dkr.ecr.us-east-1.amazonaws.com

docker build -t <orchestrator-repo-uri>:latest services/orchestrator && docker push <orchestrator-repo-uri>:latest
docker build -t <gateway-mcp-repo-uri>:latest services/gateway-mcp && docker push <gateway-mcp-repo-uri>:latest
docker build -t <mock-bluemarble-repo-uri>:latest services/mock-bluemarble && docker push <mock-bluemarble-repo-uri>:latest
docker build -t <mock-salesforce-repo-uri>:latest services/mock-salesforce && docker push <mock-salesforce-repo-uri>:latest
```

Repo URIs come from the `ecr` stack's `*RepoUri` outputs
(`aws cloudformation describe-stacks --stack-name vfz-ecr`).

### 5. gateway-services

Depends on network, gateway-ecs-cluster, ecr, and data — and needs images
already pushed. Creates IAM roles.

```bash
aws cloudformation deploy \
  --stack-name vfz-gateway-services \
  --template-file gateway-services.yaml \
  --parameter-overrides EnvironmentName=vfz-poc \
    NetworkStackName=vfz-network \
    GatewayEcsClusterStackName=vfz-gateway-ecs-cluster \
    EcrStackName=vfz-ecr \
    DataStackName=vfz-data \
    AppSecretsStackName=vfz-app-secrets \
  --capabilities CAPABILITY_NAMED_IAM \
  --region us-east-1
```

This publishes `GATEWAY_MCP_URL` as an SSM parameter (`GatewayMcpUrl` /
`GatewayMcpUrlParameterName` outputs) once the ALB's DNS name resolves.

### 6. irsa-roles

Depends on eks-cluster (OIDC provider), app-secrets, and data. Requires the
AWS Load Balancer Controller's IAM policy ARN, which is AWS-maintained and
not checked into this repo — create it once first:

```bash
curl -o iam_policy.json https://raw.githubusercontent.com/kubernetes-sigs/aws-load-balancer-controller/main/docs/install/iam_policy.json
aws iam create-policy --policy-name AWSLoadBalancerControllerIAMPolicy --policy-document file://iam_policy.json
```

Then deploy, passing the resulting ARN:

```bash
aws cloudformation deploy \
  --stack-name vfz-irsa-roles \
  --template-file irsa-roles.yaml \
  --parameter-overrides EnvironmentName=vfz-poc \
    EksClusterStackName=vfz-eks-cluster \
    AppSecretsStackName=vfz-app-secrets \
    DataStackName=vfz-data \
    LoadBalancerControllerPolicyArn=<arn from above> \
    BedrockModelId=anthropic.claude-3-5-sonnet-20241022-v2:0 \
    BedrockGuardrailId=<guardrail-id-or-leave-blank> \
  --capabilities CAPABILITY_NAMED_IAM \
  --region us-east-1
```

### Cluster bootstrap (Helm, between steps 6 and 7)

Not CloudFormation — installs cluster add-ons the orchestrator's manifests
depend on (ALB creation, Secrets Store CSI mounts, HPA metrics):

```bash
aws eks update-kubeconfig --name vfz-poc-orchestrator --region us-east-1

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

**How secrets actually get to the orchestrator pod:** the two `secrets-store-csi-driver`
commands above install two separate DaemonSets, not one — the generic CSI driver
(`helm install csi-secrets-store ...`) implements the Kubernetes CSI mount interface but
doesn't know AWS exists; the `kubectl apply .../aws-provider-installer.yaml` line installs
the AWS Secrets and Configuration Provider (ASCP), the piece that actually calls
Secrets Manager/SSM.

At pod start, the orchestrator's `secrets-store` CSI volume
(`infra/k8s/orchestrator/deployment.yaml`) triggers the generic driver to delegate to
ASCP on that node, which assumes the pod's IRSA role (`OrchestratorRole`, from
irsa-roles.yaml) and fetches the objects listed in
`infra/k8s/orchestrator/secret-provider-class.yaml` **live** — nothing is cached in the
image or fetched at Helm-install time. Because that `SecretProviderClass` also declares
`secretObjects`, the same mount step syncs those values into a real Kubernetes `Secret`
(`orchestrator-secrets`), remapped to the key names (`POSTGRES_PASSWORD`,
`GATEWAY_API_KEY`, etc.) the Deployment expects. The Deployment then loads that k8s
`Secret` as env vars via `envFrom`, once, at container start — the app itself never calls
Secrets Manager and never reads the mounted files directly.

Caveat: env vars are fixed at container start. If a secret rotates in Secrets Manager
afterward, the CSI driver can refresh the *mounted files* on its poll interval, but the
derived k8s `Secret` and the pod's env vars will not update — a rotated secret only takes
effect after the pod is restarted.

### 7. Apply the orchestrator manifests

`infra/k8s/orchestrator/*.yaml` contain `__PLACEHOLDER__` tokens filled in
from CloudFormation outputs. Simplest approach — `envsubst`:

```bash
export ORCHESTRATOR_IRSA_ROLE_ARN=<irsa-roles OrchestratorRoleArn output>
export AWS_REGION=us-east-1
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

### 8. ui

No CloudFormation dependencies, but must be deployed last: the S3 sync
needs `services/ui/dist` built with `window.ORCHESTRATOR_BASE_URL` already
pointed at the Ingress ALB hostname noted in step 7.

```bash
aws cloudformation deploy \
  --stack-name vfz-ui \
  --template-file ui.yaml \
  --parameter-overrides EnvironmentName=vfz-poc \
  --region us-east-1

# then, with services/ui/dist built against the orchestrator's ALB hostname:
aws s3 sync services/ui/dist s3://<ui UiBucketName output> --delete
aws cloudfront create-invalidation --distribution-id <ui DistributionId output> --paths "/*"
```

## Stack components

### network.yaml

One VPC (`10.0.0.0/16` by default) with two independently-routed subnet
groups that share nothing but the VPC, IGW, and one NAT Gateway:

- **eks-\*** subnets (public `10.0.0.0/24`, `10.0.1.0/24`; private
  `10.0.10.0/24`, `10.0.11.0/24`) — for the orchestrator's EKS cluster and
  node group. Public subnets are tagged `kubernetes.io/role/elb` and
  private ones `kubernetes.io/role/internal-elb` so the AWS Load Balancer
  Controller can auto-discover them.
- **gateway-\*** subnets (public `10.0.20.0/24`, `10.0.21.0/24`; private
  `10.0.30.0/24`, `10.0.31.0/24`) — for the gateway-mcp/mocks ECS Fargate
  platform.
- One **NAT Gateway** (in `EksPublicSubnet1`) shared by both private route
  tables — there is deliberately no private routing shortcut between the
  eks-private and gateway-private route tables, so the orchestrator can
  only reach gateway-mcp via its public ALB, the same path it would use for
  any third-party MCP provider.
- **Route tables**: one public table (default route → IGW) shared by all
  four public subnets, and two separate private tables (default route →
  the shared NAT Gateway) — one per platform, kept apart so a future
  routing change on one side can't accidentally affect the other.

#### VPC endpoints

Two **Interface** VPC endpoints keep specific AWS-service traffic off the
NAT path entirely (traffic goes over AWS's private network instead of
through the NAT Gateway to the public internet):

- `BedrockRuntimeEndpoint` (`com.amazonaws.<region>.bedrock-runtime`) —
  placed only in the **eks-private** subnets, because only the
  orchestrator calls Bedrock. gateway-mcp's task role carries an explicit
  `Deny` on `bedrock:InvokeModel*` (see gateway-services.yaml), so it has
  no need for this endpoint and doesn't get one — defense in depth mirrored
  by network placement, not just IAM.
- `SecretsManagerEndpoint` (`com.amazonaws.<region>.secretsmanager`) —
  placed in the **eks-private** subnets, one ENI per AZ (an interface
  endpoint can only have one ENI per AZ, and EksPrivateSubnet1/2 and
  GatewayPrivateSubnet1/2 pair up by AZ). Both platforms read secrets from
  it — the orchestrator reads DB credentials, the gateway API key, and
  Langfuse keys; gateway-mcp and the mocks read DB credentials and the
  gateway API key — gateway-private traffic reaches these ENIs over the
  VPC's implicit local route, no ENI of its own needed.

Both endpoints have `PrivateDnsEnabled: true`, so in-VPC callers resolve
the normal `secretsmanager.<region>.amazonaws.com` / `bedrock-runtime.<region>.amazonaws.com`
hostnames straight to the endpoint's ENIs with no code-level change needed.
They share one security group (`VpcEndpointSg`) that allows port 443
inbound only from the VPC's own CIDR — nothing outside the VPC can reach
them, and they don't need an egress rule since interface endpoints don't
initiate connections.

Everything else still goes over NAT: reaching gateway-mcp's public ALB,
ECR image pulls, and Langfuse Cloud. There are no ECR or S3 gateway
endpoints — at POC scale, each service only pulls its image once per
deploy, so the NAT cost is negligible and the extra endpoints wouldn't pay
for themselves.

**Outputs**: VPC ID/CIDR, and subnet ID lists/singles for each of the four
subnet groups — every other stack imports from here.

### eks-cluster.yaml

The orchestrator's EKS control plane, in the eks-private subnets.

- `ClusterSecurityGroup` — attached to the control plane's ENIs.
- `ClusterRole` — the EKS service role (`AmazonEKSClusterPolicy`).
- `Cluster` — an `AWS::EKS::Cluster` with `AuthenticationMode:
  API_AND_CONFIG_MAP`, both public and private API endpoint access enabled
  (so `kubectl` works from outside the VPC while nodes/pods stay private).
- `OidcProvider` — the cluster's IAM OIDC identity provider, which is what
  makes IRSA (IAM Roles for Service Accounts) possible; the thumbprint is
  Amazon Root CA1's well-known fingerprint, the same one eksctl/CDK use.

**Outputs** include `ClusterSharedSecurityGroupId` (the SG EKS
auto-attaches to the control plane *and* every managed-node-group
instance) — this, not `ControlPlaneSecurityGroupId`, is the SG that
data.yaml grants DB ingress from.

### eks-nodegroup.yaml

A managed node group for the cluster above, confined to the eks-private
subnets.

- `NodeRole` — worker node IAM role (`AmazonEKSWorkerNodePolicy`,
  `AmazonEC2ContainerRegistryReadOnly`, `AmazonEKS_CNI_Policy`).
- `NodeGroup` — `t3.medium` by default, 2/2/4 (min/desired/max), AL2023
  x86_64 AMI, `MaxUnavailable: 1` on rolling updates.

### gateway-ecs-cluster.yaml

A second, independent ECS cluster (Container Insights enabled) for
gateway-mcp and its two mocks — deliberately not the EKS cluster, so
gateway-mcp is only reachable as an external service the orchestrator
calls over HTTPS/HTTP, never a workload that happens to share a control
plane with it.

### gateway-services.yaml

Three ECS Fargate services in the gateway-private subnets, plus the
plumbing between them:

- **Cloud Map namespace** (`gateway.internal`) with A-record services for
  `mock-bluemarble` and `mock-salesforce` — private DNS discovery used only
  by gateway-mcp, never exposed to EKS.
- **TaskExecutionRole** (shared) — pulls images and reads the DB secret and
  gateway API key secret for injection as container secrets.
- **gateway-mcp**: task role carries an explicit `Deny` on
  `bedrock:InvokeModel*` (defense in depth — nothing grants it Bedrock
  access either, but this makes the boundary explicit and durable against
  future policy drift). Fronted by its own internet-facing ALB
  (`GatewayAlb`, port 80 → target port 8090, health check `/health`) — this
  is the "remote MCP server" endpoint the orchestrator calls. Its task
  security group only accepts 8090 from the ALB's security group.
- **mock-bluemarble** / **mock-salesforce**: no public ingress at all —
  each task security group accepts its port only from gateway-mcp's task
  security group, and each registers with Cloud Map instead of an ALB.
- **DB ingress rules**: this stack adds three more ingress rules to
  data.yaml's `DbSecurityGroup` (from gateway-mcp's, bluemarble's, and
  salesforce's task security groups) on top of the EKS-side rule data.yaml
  creates for itself.
- **GatewayMcpUrlParameter** — an SSM `String` parameter
  (`/${EnvironmentName}/gateway-mcp-url`) holding
  `http://<GatewayAlb DNS name>/mcp`, consumed by the orchestrator's k8s
  Deployment as `GATEWAY_MCP_URL`. HTTP only for this POC — no custom
  domain or ACM cert; add both before treating this as production.

### data.yaml

A single RDS PostgreSQL instance (`db.t4g.micro`/20GB gp3 by default,
`postgres` 16.9, single-AZ, encrypted, 1-day backup retention) shared by
the orchestrator's LangGraph checkpointer and gateway-mcp/mocks'
bluemarble/salesforce/audit schemas — mirroring the repo's
schema-per-system design (ADR-3). Isolation between the two compute
platforms is enforced entirely by security group, not separate databases:

- `DbSecret` — Secrets Manager, auto-generated username/password.
- `DbSubnetGroup` — spans all four private subnets (eks-private and
  gateway-private) so either platform can reach it.
- `DbSecurityGroup` — no default allow; ingress is granted per-consumer.
  This stack grants only the EKS shared node SG; gateway-services.yaml
  layers on its own ingress rules afterward.

### ecr.yaml

Four ECR repositories (`orchestrator`, `gateway-mcp`, `mock-bluemarble`,
`mock-salesforce`), each with scan-on-push enabled and a lifecycle policy
that expires untagged images after 14 days.

### app-secrets.yaml

Secrets shared across both compute platforms:

- `GatewayApiKeySecret` — auto-generated; read by both gateway-mcp's ECS
  task and the orchestrator's EKS pods, since this repo owns and issues
  both sides of that credential.
- `LangfuseSecret` — placeholder (`public_key`/`secret_key` blank); the
  orchestrator only reads this, and no-ops tracing if the values are
  empty. Populate manually post-deploy.

### irsa-roles.yaml

Two IAM roles trusted via the EKS cluster's OIDC provider, each scoped to
one specific `namespace:serviceaccount` subject (via `StringEquals` on
`<oidc-host>:sub`) so no other pod in the cluster can assume them:

- `OrchestratorRole` — trusts `system:serviceaccount:<namespace>:orchestrator`.
  Grants `bedrock:InvokeModel`/`InvokeModelWithResponseStream` scoped to one
  foundation-model ARN, `bedrock:ApplyGuardrail` scoped to a guardrail ARN
  (only if `BedrockGuardrailId` is set), and `secretsmanager:GetSecretValue`
  on the gateway API key, Langfuse, and DB secrets.
- `LoadBalancerControllerRole` — trusts
  `system:serviceaccount:kube-system:aws-load-balancer-controller`, and
  attaches the AWS-maintained `AWSLoadBalancerControllerIAMPolicy` (fetched
  from the upstream repo, not hand-copied here — see deploy instructions
  above).

Note the trust-policy JSON is built as a raw `!Sub` JSON string rather than
nested YAML: CloudFormation has no clean way to compute a *dynamic map key*
(`"<oidc-host>:sub"`) in native syntax, but `Json`-typed properties accept a
pre-rendered JSON string just as well.

### ui.yaml

Static hosting for the chat UI — deploy last, since the build it serves
needs the orchestrator's Ingress ALB hostname baked in.

- `UiBucket` — private S3 bucket (all public access blocked).
- `OriginAccessControl` + `Distribution` — CloudFront distribution reading
  from the bucket via OAC/SigV4 (no public bucket policy, no legacy OAI),
  `CachingOptimized` managed cache policy, and 403/404 responses rewritten
  to `/index.html` (200) so future client-side routing doesn't break deep
  links even though today's UI doesn't need SPA fallback.
- `UiBucketPolicy` — grants `cloudfront.amazonaws.com` `s3:GetObject`,
  conditioned on `AWS:SourceArn` matching this specific distribution.

## Verification

See the "Verification" section of the approved plan
(`i-want-to-use-crispy-cookie.md`) for the full checklist: pod health, ALB
health checks, checkpointer persistence across a pod restart, the
`scripts/mcp_smoke_test.py` run against the deployed orchestrator, mock
unreachability from outside the gateway ECS cluster, and an end-to-end
chat + approve flow through the CloudFront URL.
