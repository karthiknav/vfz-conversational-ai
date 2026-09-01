# CloudFormation deployment — EKS orchestrator + ECS Fargate gateway-mcp + CloudFront/S3 UI

Ten independent stacks, wired together via `Fn::ImportValue`, plus four more
optional stacks (see the CI/CD steps below) that wire up CodePipeline/CodeBuild
to build and deploy each service automatically on push. Each stack's
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

-- optional, any time after 1-8 exist: CI/CD (push-to-deploy pipelines) --
9. cicd-foundation.yaml
   -- complete the GitHub connection handshake by hand, in the console --
10. cicd-pipeline-eks.yaml, cicd-pipelines-ecs.yaml, cicd-pipeline-ui.yaml
    (parallel, all depend only on 9 + the stacks above)
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

Once `ecr` exists, build and push all four images before continuing. This is a
one-time bootstrap step, required even if you plan to set up CI/CD later:
`gateway-services.yaml` (step 5) and the orchestrator's k8s Deployment (step 7)
both hard-reference `<repo>:<tag>`, and the pipelines that could build these
images for you don't exist until steps 9-10 — which themselves depend on 5 and
8 already being deployed. Once the CI/CD pipelines are up, you no longer need
to repeat this by hand on every change (a push to each service's directory
triggers its pipeline instead) — but the very first build has to happen here.

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
  --set region=us-east-1 \
  --set vpcId=<network VpcId output> \
  --set serviceAccount.create=true \
  --set serviceAccount.name=aws-load-balancer-controller \
  --set serviceAccount.annotations."eks\.amazonaws\.com/role-arn"=<irsa-roles LoadBalancerControllerRoleArn output>

helm repo add secrets-store-csi-driver https://kubernetes-sigs.github.io/secrets-store-csi-driver/charts
helm install csi-secrets-store secrets-store-csi-driver/secrets-store-csi-driver \
  -n kube-system \
  --set tokenRequests[0].audience=sts.amazonaws.com \
  --set syncSecret.enabled=true
kubectl apply -f https://raw.githubusercontent.com/aws/secrets-store-csi-driver-provider-aws/main/deployment/aws-provider-installer.yaml

helm repo add metrics-server https://kubernetes-sigs.github.io/metrics-server/
helm install metrics-server metrics-server/metrics-server -n kube-system
```

`region`/`vpcId` are passed explicitly rather than left for the controller to
discover via EC2 instance metadata (IMDS) at startup — belt-and-suspenders
against `eks-nodegroup.yaml`'s launch template already fixing the underlying
cause: IMDSv2's default `HttpPutResponseHopLimit` (1) is one hop too few for
a call made from inside a pod rather than the host, so any in-pod IMDS call
times out unless the launch template raises it to 2 (which `NodeLaunchTemplate`
in that stack now does). Without either fix, the controller pods crash-loop
on `failed to get VPC ID: ... context deadline exceeded`, its webhook service
ends up with no endpoints, and *any* pod-creating `helm install`/`kubectl apply`
in the cluster fails admission — not just this controller's own resources.

`--set tokenRequests[0].audience=sts.amazonaws.com` on the `csi-secrets-store`
install is required, not cosmetic: the chart's `CSIDriver` template only
populates `spec.tokenRequests` when a value is explicitly passed — omit it
and kubelet mounts the volume with no service account token attached at
all, which surfaces later (only once a pod actually tries to mount a
`secrets-store` volume — the driver install itself succeeds either way) as
`FailedMount ... CSI token error: serviceAccount.tokens not provided -
ensure tokenRequests is configured in CSIDriver`. The audience must match
`eks-cluster.yaml`'s `OidcProvider` resource, which registers
`ClientIdList: ["sts.amazonaws.com"]` — that's what lets ASCP exchange the
token for STS credentials via `AssumeRoleWithWebIdentity`. `CSIDriver.spec`
fields are immutable after creation, so if the driver was already installed
without this flag, fixing it means `helm uninstall csi-secrets-store -n
kube-system && kubectl delete csidriver secrets-store.csi.k8s.io`, then
reinstalling with the flag above — a plain `helm upgrade` won't patch the
field in place.

`--set syncSecret.enabled=true` is also required, not cosmetic, but unlike
`tokenRequests` it's a normal (mutable) value — a plain `helm upgrade` with
the flag fixes it if it was missed, no reinstall needed. Without it the CSI
volume still mounts fine and ASCP still fetches the objects into
`/mnt/secrets-store` with no errors in its logs, but the driver never
creates the derived Kubernetes `Secret` described below — the orchestrator
Deployment's `envFrom.secretRef` then fails pod creation with `Error:
secret "orchestrator-secrets" not found`, which is easy to misread as an
ASCP/IRSA problem when the actual fetch worked. Confirm the secret exists
before chasing anything else:

```bash
kubectl get secret orchestrator-secrets -n orchestrator
# NotFound here + clean ASCP daemonset logs == missing syncSecret.enabled
```

If you have to add the flag after the fact, restart the orchestrator pods
afterward so they remount and trigger the sync — a Secret's absence isn't
watched, so existing pods won't self-heal:

```bash
helm upgrade csi-secrets-store secrets-store-csi-driver/secrets-store-csi-driver \
  -n kube-system \
  --set tokenRequests[0].audience=sts.amazonaws.com \
  --set syncSecret.enabled=true

kubectl rollout restart deployment/orchestrator -n orchestrator
kubectl rollout status deployment/orchestrator -n orchestrator
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

**End-to-end map, source secret to consuming code** — each row is one value's
full path from where it's stored to the line in `services/orchestrator` that
reads it:

| Secrets Manager / SSM source | `secret-provider-class.yaml` alias | `orchestrator-secrets` key | Read in app code |
| --- | --- | --- | --- |
| `vfz-poc/db-credentials` → `username` | `db-username` | `POSTGRES_USER` | `graph.py`: `os.environ["POSTGRES_USER"]` |
| `vfz-poc/db-credentials` → `password` | `db-password` | `POSTGRES_PASSWORD` | `graph.py`: `os.environ["POSTGRES_PASSWORD"]` |
| `vfz-poc/gateway-api-key` → `api_key` | `gateway-api-key-value` | `GATEWAY_API_KEY` | `mcp_client.py`: `os.environ["GATEWAY_API_KEY"]` |
| `vfz-poc/langfuse-keys` → `public_key` | `langfuse-public-key` | `LANGFUSE_PUBLIC_KEY` | `langfuse_setup.py`: `os.environ.get("LANGFUSE_PUBLIC_KEY")` |
| `vfz-poc/langfuse-keys` → `secret_key` | `langfuse-secret-key` | `LANGFUSE_SECRET_KEY` | `langfuse_setup.py`: `os.environ.get("LANGFUSE_SECRET_KEY")` |
| SSM `/vfz-poc/gateway-mcp-url` | `gateway-mcp-url` | `GATEWAY_MCP_URL` | `mcp_client.py`: `os.environ.get("GATEWAY_MCP_URL", ...)` |

`graph.py` and `mcp_client.py` use the required-key form (`os.environ["X"]`,
`KeyError` if unset) for the DB credentials and gateway API key — there's no
sane fallback for either, so a broken CSI sync fails loudly at import time
rather than limping along. `langfuse_setup.py` and the `GATEWAY_MCP_URL`
read use `.get()` with a fallback: missing Langfuse keys just disable
tracing (`get_callback_handler()` returns `None`), and a missing
`GATEWAY_MCP_URL` falls back to the docker-compose hostname so the same
image runs locally and in-cluster unchanged.

`POSTGRES_HOST`/`POSTGRES_PORT`/`POSTGRES_DB` follow a completely different
path — they're literal/placeholder values in `deployment.yaml`'s `env:`
list, substituted by the `envsubst`/`sed` step below from `data.yaml`'s
CloudFormation outputs, not synced through `orchestrator-secrets` at all
(see step 7).

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

**Checking rollout health / restarting the orchestrator.** After any
`kubectl apply` (or a Helm change upstream, like the `syncSecret` one
above), confirm the new pods actually came up rather than assuming the
apply succeeding means the rollout did:

```bash
kubectl rollout status deployment/orchestrator -n orchestrator   # blocks until Ready or errors out
kubectl get pods -n orchestrator -o wide                         # STATUS column: CrashLoopBackOff, CreateContainerConfigError, etc.
kubectl describe pod -n orchestrator -l app=orchestrator          # Events: at the bottom has the actual failure reason
kubectl logs -n orchestrator -l app=orchestrator --all-containers --tail=100
kubectl logs -n kube-system -l app=csi-secrets-store-provider-aws --tail=100  # ASCP-side fetch errors
```

To force pods to re-pull secrets/config without changing the manifest
(e.g. after a Secrets Manager rotation, or the `syncSecret` fix above —
neither is watched, so existing pods won't pick it up on their own):

```bash
kubectl rollout restart deployment/orchestrator -n orchestrator
kubectl rollout status deployment/orchestrator -n orchestrator
```

If a rollout is stuck or bad, `kubectl rollout undo deployment/orchestrator
-n orchestrator` returns to the previous ReplicaSet; `kubectl rollout
history deployment/orchestrator -n orchestrator` lists revisions.

### 8. ui

No CloudFormation dependencies, but must be deployed last: the S3 sync
needs `services/ui/dist` built with `window.ORCHESTRATOR_BASE_URL` already
pointed at the Ingress ALB hostname noted in step 7. `cicd-pipeline-ui.yaml`
does this injection automatically on every push (see `services/ui/buildspec.yml`);
deploying by hand means repeating the same two steps that buildspec runs —
patch `index.html`, then build — before the `s3 sync`:

```bash
aws cloudformation deploy \
  --stack-name vfz-ui \
  --template-file ui.yaml \
  --parameter-overrides EnvironmentName=vfz-poc \
  --region us-east-1

# The UI is a static bundle with no server-side templating, so the
# orchestrator's URL has to be baked into index.html at build time — there's
# nowhere else for the browser to learn it at runtime. That's the ALB
# hostname CloudFormation isn't aware of, since it's created by the
# `orchestrator` Ingress (Kubernetes), not by ui.yaml — hence reading it
# with kubectl instead of an `aws cloudformation describe-stacks` output.
ALB_HOSTNAME=$(kubectl get ingress orchestrator -n orchestrator \
  -o jsonpath='{.status.loadBalancer.ingress[0].hostname}')

# index.html ships with a placeholder comment (see the block right before
# `<script type="module" src="/src/main.js">`) documenting the injection
# this sed performs: it inserts a second inline
# `<script>window.ORCHESTRATOR_BASE_URL = "http://<ALB_HOSTNAME>";</script>`
# tag immediately before that module script tag, so widget/chat.js sees the
# global already set when it loads. This is exactly the sed buildspec.yml
# runs on every push (services/ui/buildspec.yml) — running it by hand here
# just reproduces CI's build step locally.
#
# HTTP, not HTTPS: this POC's ALB has no ACM cert / custom domain, so the
# orchestrator is only reachable over plain HTTP (see ingress.yaml's note).
#
# Because sed edits index.html in place, this leaves the real ALB hostname
# sitting in a tracked file — don't commit it. Either run this against a
# scratch copy of the repo, or (as below) run `git checkout --
# services/ui/index.html` right after the build to restore the placeholder.
sed -i "s#<script type=\"module\" src=\"/src/main.js\"></script>#<script>window.ORCHESTRATOR_BASE_URL = \"http://${ALB_HOSTNAME}\";</script>\n  <script type=\"module\" src=\"/src/main.js\"></script>#" \
  services/ui/index.html

# Builds the patched index.html (and the rest of services/ui/src) into
# services/ui/dist via Vite — see services/ui/buildspec.yml's `build` phase.
cd services/ui && npm ci && npm run build && cd ../..

aws s3 sync services/ui/dist s3://<ui UiBucketName output> --delete
aws cloudfront create-invalidation --distribution-id <ui DistributionId output> --paths "/*"

# restore the placeholder so the real hostname doesn't end up in a commit
git checkout -- services/ui/index.html
```

### 9. cicd-foundation

Optional — only needed if you want push-to-deploy pipelines instead of
re-running steps 4/8's manual `docker build`/`push`/`s3 sync` commands by
hand on every *subsequent* change. The first build/push in step 4 still has
to happen manually regardless — these pipelines can't exist until after
gateway-services (step 5) and ui (step 8) are already deployed, so they can't
bootstrap the images those steps need. No CloudFormation dependencies.

```bash
aws cloudformation deploy \
  --stack-name vfz-cicd-foundation \
  --template-file cicd-foundation.yaml \
  --parameter-overrides EnvironmentName=vfz-poc \
  --region us-east-1
```

This creates the GitHub connection in `PENDING` status — CloudFormation
can't finish the handshake for you. Complete it once, by hand: CodePipeline
console → Settings → Connections → `vfz-poc-github` → "Update pending
connection" → install/authorize the AWS Connector for GitHub app against
this repo. None of the pipelines in step 10 will run until this connection
shows `AVAILABLE`.

### 10. cicd-pipeline-eks, cicd-pipelines-ecs, cicd-pipeline-ui (parallel)

Each depends on cicd-foundation (step 9) plus whichever of the ten base
stacks it deploys to. All three need `RepoOwner` (the GitHub org/user that
owns this repo — no default, since it can't be guessed).

```bash
aws cloudformation deploy \
  --stack-name vfz-cicd-pipeline-eks \
  --template-file cicd-pipeline-eks.yaml \
  --parameter-overrides EnvironmentName=vfz-poc RepoOwner=<your-github-org-or-user> \
  --capabilities CAPABILITY_NAMED_IAM \
  --region us-east-1

aws cloudformation deploy \
  --stack-name vfz-cicd-pipelines-ecs \
  --template-file cicd-pipelines-ecs.yaml \
  --parameter-overrides EnvironmentName=vfz-poc RepoOwner=<your-github-org-or-user> \
  --capabilities CAPABILITY_NAMED_IAM \
  --region us-east-1

aws cloudformation deploy \
  --stack-name vfz-cicd-pipeline-ui \
  --template-file cicd-pipeline-ui.yaml \
  --parameter-overrides EnvironmentName=vfz-poc RepoOwner=<your-github-org-or-user> \
  --capabilities CAPABILITY_NAMED_IAM \
  --region us-east-1
```

All three assume the ten base stacks already exist under their default
names (`vfz-network`, `vfz-ecr`, `vfz-eks-cluster`, `vfz-gateway-ecs-cluster`,
`vfz-gateway-services`, `vfz-ui`, …) — override the `*StackName` parameters
if you deployed any of them under different names. `vfz-gateway-services`
specifically must already export `GatewayServiceName`/
`BluemarbleServiceName`/`SalesforceServiceName` for `cicd-pipelines-ecs.yaml`
to import — redeploy that stack first if it predates this addition.

Once all three are `AVAILABLE`, a push to `main` touching
`services/orchestrator/**` or `infra/k8s/orchestrator/**` triggers the EKS
pipeline; touching `services/gateway-mcp/**`, `services/mock-bluemarble/**`,
or `services/mock-salesforce/**` triggers the matching ECS pipeline;
touching `services/ui/**` triggers the UI pipeline — each is scoped to its
own directory (CodePipeline V2 push-trigger path filters), so one service's
change never redeploys another.

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

#### Cluster admin access (`ClusterAdminRole` / `ClusterAdminAccessEntry`)

By default, EKS silently grants full cluster-admin (`system:masters`
equivalent) to whichever IAM principal happened to call `CreateCluster` —
`AccessConfig.bootstrapClusterCreatorAdminPermissions` defaults to `true`,
and this template doesn't override it. For a CI/CD-driven deploy that
principal is whatever role ran the stack, not any human, and the grant
doesn't appear as an ordinary, auditable `AccessEntry`. `ClusterAdminRole`
+ `ClusterAdminAccessEntry` exist to make admin access explicit and
version-controlled instead: anyone who can `sts:AssumeRole` into
`${EnvironmentName}-eks-cluster-admin` (gated by the
`ClusterAdminTrustedPrincipal` parameter, default: the whole account root —
narrow this to specific ARNs for real use) gets `AmazonEKSClusterAdminPolicy`
via that one, reviewable `AccessEntry` resource.

**This is the only admin path this template manages.** Anyone can still be
granted access directly — bypassing `ClusterAdminRole` entirely — by
creating a separate `AccessEntry` for their own IAM user/role ARN via
`aws eks create-access-entry` / `associate-access-policy` (or the console:
cluster → **Access** tab → **IAM access entries**). That's a normal,
supported EKS mechanism, but any such entry is *out-of-band*: it won't
show up in this stack's resources (`aws cloudformation describe-stack-resources
--stack-name vfz-eks-cluster`), isn't tracked in this template, and will
silently persist even if `ClusterAdminTrustedPrincipal` is later tightened.
Run `aws eks list-access-entries --cluster-name <cluster>` periodically to
check for entries that don't trace back to `ClusterAdminRole` or one of the
CI/CD deploy roles (see `cicd-pipeline-eks.yaml`'s `DeployAccessEntry` and
`cicd-pipeline-ui.yaml`'s view-only entry below).

### eks-nodegroup.yaml

A managed node group for the cluster above, confined to the eks-private
subnets.

- `NodeLaunchTemplate` — sets `MetadataOptions.HttpPutResponseHopLimit: 2`
  (IMDSv2 stays required). A managed node group left without a custom
  launch template gets one auto-generated by EKS, which defaults the hop
  limit to 1 — one hop too few for a call made from inside a pod (as
  opposed to the host), so any in-pod IMDS call times out. That's what
  breaks the AWS Load Balancer Controller specifically: on first boot it
  falls back to IMDS to discover the VPC ID, times out, crash-loops, and
  its webhook ends up with no endpoints — which then fails *any*
  pod-creating `helm install`/`kubectl apply` in the cluster, not just its
  own resources, since the webhook intercepts all `Service` objects
  cluster-wide. (The Helm command in "Cluster bootstrap" below also passes
  `region`/`vpcId` explicitly as a second, independent guard against the
  same failure mode.)
- `NodeRole` — worker node IAM role (`AmazonEKSWorkerNodePolicy`,
  `AmazonEC2ContainerRegistryReadOnly`, `AmazonEKS_CNI_Policy`).
- `NodeGroup` — `t3.medium` by default, 2/2/4 (min/desired/max), AL2023
  x86_64 AMI, `MaxUnavailable: 1` on rolling updates, using
  `NodeLaunchTemplate` above.

### gateway-ecs-cluster.yaml

A second, independent ECS cluster (Container Insights enabled) for
gateway-mcp and its two mocks — deliberately not the EKS cluster, so
gateway-mcp is only reachable as an external service the orchestrator
calls over HTTPS/HTTP, never a workload that happens to share a control
plane with it.

### gateway-services.yaml

Three ECS Fargate services in the gateway-private subnets, plus the
plumbing between them:

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

#### Cloud Map service discovery

`Namespace` is an `AWS::ServiceDiscovery::PrivateDnsNamespace`
(`gateway.internal`), which Cloud Map backs with a Route 53 **private
hosted zone** associated with this VPC. `BluemarbleDiscovery` and
`SalesforceDiscovery` are `AWS::ServiceDiscovery::Service` resources with
`DnsRecords: [{Type: A}]` — each becomes one record set in that zone
(`mock-bluemarble.gateway.internal`, `mock-salesforce.gateway.internal`),
but empty until something registers an instance.

That "something" is the `ServiceRegistries` property on the
`BluemarbleService`/`SalesforceService` `AWS::ECS::Service` resources
below. As tasks start, stop, or get replaced, ECS calls Cloud Map's
`RegisterInstance`/`DeregisterInstance` API on your behalf, adding or
removing that task's private IP as an A-record value — no polling, no
sidecar. `TTL: 10` keeps resolver caching short, since those IPs churn on
every deploy or scaling event.

**The "load balancing" this gives you is DNS round-robin, not a real load
balancer.** `DnsConfig` here doesn't set `RoutingPolicy`, which defaults to
`MULTIVALUE`: Route 53 returns up to 8 healthy instance IPs per query, and
whichever resolver/SDK asked picks one — there's no connection draining,
no L7 routing, no sticky sessions, and no active traffic shifting beyond
Route 53 dropping an IP once ECS deregisters that instance. In practice
this doesn't matter today: both mocks run `DesiredCount: 1`, so there's
only ever one IP behind each name.

This is exactly why gateway-mcp itself is wired differently one section up
— it fronts a real `GatewayAlb`/`GatewayTargetGroup` with health checks,
because it's the public entry point and needs real L7 load balancing; the
two mocks get the cheaper Cloud Map option because they're private,
low-stakes, single-task callees with no such requirement.

Cloud Map itself isn't ECS-specific — EC2, Lambda, and even non-AWS apps
can register through its plain API, and App Mesh/ECS Service Connect are
both built on top of it. (A single EKS cluster like this one's doesn't
need it at all: Kubernetes has its own built-in DNS-based service
discovery via CoreDNS, which is why `infra/k8s/orchestrator/service.yaml`
doesn't touch Cloud Map.) If either mock ever needed multiple tasks in a
real production setting, **ECS Service Connect** — an Envoy proxy layered
on top of this same Cloud Map namespace — would be the first upgrade to
reach for: it adds real client-side load balancing and near-instant
unhealthy-task removal without standing up a whole new ALB per service.

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
  Grants `bedrock:InvokeModel`/`InvokeModelWithResponseStream` on all
  foundation models (`foundation-model/*`) rather than one pinned model ID,
  so switching `BEDROCK_MODEL_ID` in the orchestrator Deployment's env
  doesn't require redeploying this stack; `bedrock:ApplyGuardrail` likewise
  scoped to all guardrails (`guardrail/*`) rather than one pinned ID, and
  only granted at all if `BedrockGuardrailId` is set; and
  `secretsmanager:GetSecretValue` on the gateway API key, Langfuse, and DB
  secrets.
- `LoadBalancerControllerRole` — trusts
  `system:serviceaccount:kube-system:aws-load-balancer-controller`, and
  attaches the AWS-maintained `AWSLoadBalancerControllerIAMPolicy` (fetched
  from the upstream repo, not hand-copied here — see deploy instructions
  above).

Note the trust-policy JSON is built as a raw `!Sub` JSON string rather than
nested YAML: CloudFormation has no clean way to compute a *dynamic map key*
(`"<oidc-host>:sub"`) in native syntax, but `Json`-typed properties accept a
pre-rendered JSON string just as well.

#### How the IRSA trust actually works

Both roles' `AssumeRolePolicyDocument` grants `sts:AssumeRoleWithWebIdentity`
(not the more familiar cross-account `sts:AssumeRole`) to a `Federated`
principal — `eks-cluster.yaml`'s `OidcProvider` resource, i.e. the cluster's
own OIDC issuer registered as an IAM identity provider. Two `StringEquals`
conditions must both hold before STS will honor the request:

- `<oidc-host>:aud` = `sts.amazonaws.com` — the token was minted for calling
  STS, not for some other audience.
- `<oidc-host>:sub` = `system:serviceaccount:<namespace>:<name>` — the token
  belongs to exactly one Kubernetes `ServiceAccount`, e.g.
  `system:serviceaccount:orchestrator:orchestrator` for `OrchestratorRole`.
  This is the actual access boundary: any other pod in the cluster,
  including ones in the same namespace using the `default` service account,
  presents a token with a different `sub` claim and gets denied.

The token itself never touches CloudFormation — it's supplied at runtime by
the EKS Pod Identity webhook (a mutating admission controller installed with
every EKS cluster). When a pod's spec references a `ServiceAccount` carrying
the `eks.amazonaws.com/role-arn` annotation (`service-account.yaml`'s
`orchestrator` `ServiceAccount`, in the k8s-manifests section below), the
webhook injects `AWS_ROLE_ARN` and `AWS_WEB_IDENTITY_TOKEN_FILE` env vars
into that pod, plus a projected volume containing a short-lived JWT signed
by the cluster's OIDC issuer and auto-rotated by the kubelet (default
1-hour expiry). Any IRSA-aware AWS SDK (boto3 included) picks up those two
env vars automatically and exchanges the JWT for temporary STS credentials
on first use — no code in `services/orchestrator` requests this explicitly.

This is also why IRSA is preferred over `eks-nodegroup.yaml`'s `NodeRole`:
the node role is attached to the EC2 instance profile and would be
reachable by *any* pod scheduled on that node via the instance metadata
service, whereas IRSA credentials are scoped per-pod, only to whichever
`ServiceAccount` that pod actually mounts. `OrchestratorRole` is reachable
solely by pods using the `orchestrator` `ServiceAccount`; `NodeRole` grants
nothing Bedrock- or Secrets-Manager-related in the first place, so even a
compromised pod on the same node gains nothing extra from it.

### infra/k8s/orchestrator/ manifests

Not CloudFormation — plain Kubernetes manifests applied together (step 7)
once `irsa-roles.yaml` and the Helm-installed cluster add-ons (ALB
controller, Secrets Store CSI driver + ASCP, metrics-server — see "Cluster
bootstrap" above) are in place. Their `__PLACEHOLDER__` tokens are
substituted from CloudFormation outputs before `kubectl apply` — see the
`envsubst`/`sed` loop in step 7.

- **namespace.yaml** — creates the `orchestrator` namespace; every other
  manifest here is scoped to it.
- **service-account.yaml** — `ServiceAccount` `orchestrator`, annotated
  with `eks.amazonaws.com/role-arn` set to `irsa-roles.yaml`'s
  `OrchestratorRoleArn` output. This is the IRSA binding: any pod that
  mounts this service account (the Deployment does) can assume
  `OrchestratorRole` for Bedrock and Secrets Manager access with no static
  AWS credentials in the pod.
- **secret-provider-class.yaml** — `SecretProviderClass`
  `orchestrator-secrets` (`provider: aws`). Lists three Secrets Manager
  objects (`vfz-poc/gateway-api-key`, `vfz-poc/db-credentials`,
  `vfz-poc/langfuse-keys`) and one SSM parameter
  (`/vfz-poc/gateway-mcp-url`, published by `gateway-services.yaml`), each
  with a `jmesPath` that extracts and renames specific fields. Its
  `secretObjects` block re-syncs those extracted values into a real k8s
  `Secret` named `orchestrator-secrets`, remapped to the key names
  `deployment.yaml` expects (`POSTGRES_USER`, `POSTGRES_PASSWORD`,
  `GATEWAY_API_KEY`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`,
  `GATEWAY_MCP_URL`). The full mechanics — which CSI DaemonSet does what,
  and the caveat that pod env vars don't pick up a secret rotation until
  the pod restarts — are covered under "Cluster bootstrap" above.
- **deployment.yaml** — the orchestrator pod spec: 2 replicas,
  `serviceAccountName: orchestrator` (so pods inherit `OrchestratorRole`),
  image `__ECR_ORCHESTRATOR_IMAGE_URI__`, `envFrom` the
  `orchestrator-secrets` k8s `Secret` plus literal/placeholder env vars
  (Bedrock model + guardrail IDs, Langfuse host, Postgres host/port/db
  name, and `ALLOWED_ORIGINS` set to the UI's CloudFront URL), the
  `secrets-store` CSI volume mounted read-only at `/mnt/secrets-store`
  (the app itself never reads these files — mounting is only what
  triggers the CSI sync into the `envFrom` Secret above), and `/health`
  readiness/liveness probes. A comment on the file flags a prerequisite:
  running with `replicas > 1` requires the orchestrator's LangGraph
  checkpointer already switched from in-memory `MemorySaver` to
  `AsyncPostgresSaver` (`services/orchestrator/app/graph.py`), or state
  won't be shared across pods.
- **service.yaml** — `ClusterIP` `Service` `orchestrator`, port 8000,
  selecting `app: orchestrator`. Internal only — the Ingress below is the
  actual public entry point.
- **ingress.yaml** — an ALB `Ingress` provisioned by the AWS Load Balancer
  Controller, internet-facing, `target-type: ip`, health check on
  `/health`, HTTP-only on port 80 (no ACM cert wired up — POC, no custom
  domain). Its ALB's DNS name is the "Ingress ALB hostname" referenced
  throughout steps 7-8 and consumed by `ui.yaml`'s build and
  `cicd-pipeline-ui.yaml`.
- **hpa.yaml** — a `HorizontalPodAutoscaler` targeting the Deployment,
  2-6 replicas, scaling on 70% average CPU utilization; requires
  metrics-server (installed in "Cluster bootstrap") to supply the
  underlying metrics.

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

### cicd-foundation.yaml

Shared CI/CD plumbing: one CodeStar Connection to GitHub (a GitHub App
OAuth handshake, completed once by hand — no PAT stored anywhere) and one
S3 bucket for CodePipeline/CodeBuild artifacts, shared by all three
pipeline stacks below.

### cicd-pipeline-eks.yaml

The orchestrator's pipeline — the only one deploying to EKS instead of
ECS. Triggered only by pushes to `services/orchestrator/**` or
`infra/k8s/orchestrator/**`. Build stage builds + pushes the image to
ECR; Deploy stage is a CodeBuild project that runs `kubectl set image` +
`kubectl rollout status` against the existing Deployment — it does not
re-render `infra/k8s/orchestrator/*.yaml`'s `__PLACEHOLDER__` tokens,
since those only change when the surrounding CloudFormation stacks
change (a provisioning-time concern — see step 7 above — not a per-commit
one). The deploy role gets an `AWS::EKS::AccessEntry` scoped to the
`orchestrator` namespace only (`AmazonEKSEditPolicy`, namespace-scoped,
not cluster-admin) — IAM permissions alone aren't enough to call the k8s
API under `AuthenticationMode: API_AND_CONFIG_MAP`.

### cicd-pipelines-ecs.yaml

Three independent pipelines bundled in one stack (mirroring how
gateway-services.yaml bundles the three ECS services themselves):
gateway-mcp, mock-bluemarble, mock-salesforce — each triggered only by
pushes to its own `services/<name>/` directory. Each Build stage builds +
pushes to ECR and writes an `imagedefinitions.json`; each Deploy stage is
its own CodeBuild project that scripts the ECS update directly —
`describe-task-definition`, swap the one container's image with `jq`,
`register-task-definition`, `update-service`, then `wait
services-stable` — rather than using CodePipeline's native `ECS` deploy
action. Same rolling-update behavior either way; scripting it means the
stage can grow custom health gates or rollback logic later without
switching to CodeDeploy blue/green (the other alternative — a better fit
for gateway-mcp specifically, since it's the one service with an ALB in
front of it; the mocks have neither public traffic nor a load balancer to
shift, so blue/green would add infra for no benefit there).

### cicd-pipeline-ui.yaml

Triggered only by pushes to `services/ui/**`. Build stage reads the
orchestrator's Ingress ALB hostname live via `kubectl get ingress`
(read-only `AmazonEKSViewPolicy` access entry, scoped to the
`orchestrator` namespace — same reasoning as cicd-pipeline-eks.yaml's
access entry, just view instead of edit), injects it into
`services/ui/index.html` as `window.ORCHESTRATOR_BASE_URL`, then runs
`npm run build`. Deploy stage syncs `dist/` to the UI bucket and
invalidates CloudFront. Deliberately re-reads the ALB hostname on every
run instead of caching it, since recreating the Ingress would change it.

## Troubleshooting

### ALB controller crash-loops, or an Ingress never gets an ADDRESS

**Symptoms**: `kubectl get pods -n kube-system -l app.kubernetes.io/name=aws-load-balancer-controller`
shows `CrashLoopBackOff`, with logs ending in:

```
unable to initialize AWS cloud: failed to get VPC ID: failed to fetch VPC ID from
instance metadata: ... get mac metadata: ... context deadline exceeded
```

— or the controller pods themselves show `Running 1/1` (their readiness probe only
checks the local webhook HTTP server, not AWS connectivity) but an `Ingress` sits
with no `ADDRESS` indefinitely, and `kubectl describe ingress <name>` shows repeating
events like:

```
FailedBuildModel ... DescribeLoadBalancers, get identity: get credentials:
failed to refresh cached credentials, no EC2 IMDS role found, ...
context deadline exceeded
```

**Root cause**: both errors are the same underlying failure — the pod can't reach
the EC2 instance metadata service (IMDS, `169.254.169.254`). IMDSv2 has a
`HttpPutResponseHopLimit` setting that caps how many network hops a metadata
request can travel; traffic from *inside a pod's* network namespace takes one
more hop than traffic from the host itself (the bridge/veth adds a hop), so a
node with hop limit `1` serves IMDS fine to host-level processes but times out
every in-pod call. The controller uses IMDS at startup to auto-discover its VPC
ID, and (as a fallback credentials source) during reconciliation — both die the
same way. `eks-nodegroup.yaml`'s `NodeLaunchTemplate` sets the hop limit to `2`
precisely to prevent this, but **the fix only applies to nodes launched under
that launch template** — check whether the deployed stack actually has it:

```bash
aws cloudformation describe-stack-resources --stack-name vfz-eks-nodegroup \
  --query "StackResources[].LogicalResourceId"
# No "NodeLaunchTemplate" in the list == the deployed stack predates the fix
# (or was never updated since) and existing nodes were launched without it,
# regardless of what's in the template file in this repo.
```

**Fix**:

1. Redeploy the node group stack so its launch template (and thus the hop
   limit) actually reaches AWS — safe to run any time, confirm first with a
   change set if you want to see the plan before applying:
   ```bash
   aws cloudformation deploy --stack-name vfz-eks-nodegroup \
     --template-file eks-nodegroup.yaml \
     --parameter-overrides EnvironmentName=vfz-poc NetworkStackName=vfz-network EksClusterStackName=vfz-eks-cluster \
     --capabilities CAPABILITY_NAMED_IAM --region us-east-1
   ```
   Attaching a launch template to a node group that didn't have one is an
   in-place update (`Replacement: False`, `RequiresRecreation: Never`) — it
   rolls the existing nodes one at a time per `UpdateConfig.MaxUnavailable: 1`,
   not a full node group recreation.
2. To unblock immediately without waiting on a stack deploy/node roll (e.g.
   mid-incident), raise the hop limit on the live instances directly — takes
   effect with no reboot:
   ```bash
   aws ec2 modify-instance-metadata-options --instance-id <id> \
     --http-put-response-hop-limit 2 --http-tokens required
   ```
   This only patches already-running instances; it doesn't change the launch
   template, so any node replaced later (scale-up, AMI upgrade, spot
   interruption) reverts to hop limit `1` unless step 1 has also been applied.
3. After either fix, the crash-looping controller pod recovers on its own
   restart, and any pending Ingress gets an `ADDRESS` on its next reconcile
   (a few seconds) with no other action needed.

## Verification

See the "Verification" section of the approved plan
(`i-want-to-use-crispy-cookie.md`) for the full checklist: pod health, ALB
health checks, checkpointer persistence across a pod restart, the
`scripts/mcp_smoke_test.py` run against the deployed orchestrator, mock
unreachability from outside the gateway ECS cluster, and an end-to-end
chat + approve flow through the CloudFront URL.

## CI/CD notes and gaps to close before production

Auth to AWS never uses a stored access key across any of the four CI/CD
stacks (see steps 9-10 and their stack-component entries above): GitHub
access goes through a CodeStar Connection (a GitHub App OAuth handshake,
completed once by hand), and every pipeline/build/deploy role is a normal
IAM role assumed by the AWS service itself (CodePipeline/CodeBuild),
scoped to exactly what that stage does. What's still missing before this
would hold up as a production setup:

- **No rollback automation.** ECS deploys get standard rolling-update
  behavior from `UpdateService`, but nothing here watches for a bad
  rollout and reverts it. The orchestrator's `kubectl rollout status`
  will at least fail the pipeline (and leave the previous ReplicaSet
  running) if the new pods never become ready — that's a stop, not an
  automatic rollback.
- **No test/lint stage.** These pipelines go straight from build to
  deploy. Add a stage (or a step in the build buildspec) running each
  service's test suite before the image is pushed.
- **`latest` tag still gets overwritten on every push**, alongside the
  immutable short-SHA tag each pipeline actually deploys — keep it only if
  something still depends on it; drop it once nothing does.
- **Single environment.** There's no staging gate — every push to `main`
  that touches a service's directory deploys straight to `vfz-poc`. Adding
  a second environment means parameterizing `BranchName`/`EnvironmentName`
  per env and, for a real approval gate, adding a manual-approval stage
  before Deploy.
