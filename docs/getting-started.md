# Getting Started — Running Every Component Locally

This walks through bringing the whole stack up via Docker Compose (the fast path), then how to run each service standalone on the host for active development, plus a troubleshooting section for the things that trip people up first time.

## Prerequisites

- Docker Desktop (Compose v2)
- Python 3.12+ (only needed if you'll run a service outside Docker, or use the `scripts/` helpers)
- AWS credentials with Bedrock access in `eu-west-1` (or whichever `AWS_REGION` you set) — **every chat turn calls Claude**, so the orchestrator won't produce useful replies without this. Health/routing/DB plumbing all work without it; the LLM calls will not.
- Langfuse Cloud keys — optional, tracing just no-ops without them

## 1. Fast path: the whole stack via Docker Compose

```bash
cp .env.example .env                 # fill in AWS creds + Langfuse keys (both optional to boot containers)
docker compose up --build
```

This starts, in dependency order (`depends_on` + healthchecks in `docker-compose.yml`):

```
db  →  mock-bluemarble, mock-salesforce  →  gateway-mcp  →  orchestrator  →  ui
```

Once containers report healthy, verify the seed data and MCP surface from the host:

```bash
python -m pip install -r scripts/requirements.txt
python scripts/seed_db.py --check         # confirms seed data landed in Postgres
python scripts/mcp_smoke_test.py          # confirms the Gateway's MCP server answers tools/list + tools/call
```

Then either:
- Open **http://localhost:8080** for the chat UI, or
- Drive the API directly:
  ```bash
  python scripts/golden_path_test.py --branch auto_approve
  python scripts/golden_path_test.py --branch escalate
  python scripts/golden_path_test.py --branch partial_failure
  ```

Full expected-output walkthrough: [`demo-script.md`](demo-script.md).

To stop everything: `docker compose down` (add `-v` to also drop the Postgres volume and re-seed from scratch next time).

## 2. Per-component reference

| Service | Port | Health check | Depends on |
|---|---|---|---|
| `db` (Postgres) | 5432 | `pg_isready` | — |
| `mock-bluemarble` | 8081 | `GET /health` | `db` |
| `mock-salesforce` | 8082 | `GET /health` | `db` |
| `gateway-mcp` | 8090 | `GET /health` | `db`, `mock-bluemarble`, `mock-salesforce` |
| `orchestrator` | 8000 | `GET /health` | `gateway-mcp` |
| `ui` | 8080 | `GET /` | `orchestrator` |

Every Python service is `FROM python:3.12-slim`, installs its own `requirements.txt`, and is run with Uvicorn (see each `Dockerfile`). `ui` is plain static files served by nginx — no build step.

## 3. Running one service standalone (active development)

The usual pattern: keep everything *except* the service you're actively changing running in Docker, run that one service on the host with `--reload` so edits take effect instantly, and repoint it at the Dockerized dependencies via `localhost`.

### Orchestrator (most common — this is where the agent/graph logic lives)

```bash
docker compose up -d db mock-bluemarble mock-salesforce gateway-mcp

cd services/orchestrator
python -m venv .venv && . .venv/Scripts/activate   # or source .venv/bin/activate on macOS/Linux
pip install -r requirements.txt

# Env vars — gateway-mcp's container port is published to the host at 8090
export GATEWAY_MCP_URL=http://localhost:8090/mcp
export GATEWAY_API_KEY=dev-gateway-key-change-me   # must match .env's GATEWAY_API_KEY
export AWS_REGION=eu-west-1
export BEDROCK_MODEL_ID=anthropic.claude-3-5-sonnet-20241022-v2:0
# AWS credentials: exported env vars, or your default ~/.aws profile — boto3's normal chain

uvicorn app.api:app --reload --port 8000
```

(PowerShell: use `$env:GATEWAY_MCP_URL = "http://localhost:8090/mcp"` etc. instead of `export`.)

### Gateway (MCP server + middleware)

```bash
docker compose up -d db mock-bluemarble mock-salesforce

cd services/gateway-mcp
python -m venv .venv && . .venv/Scripts/activate
pip install -r requirements.txt

export POSTGRES_USER=vz_poc POSTGRES_PASSWORD=change-me-locally POSTGRES_DB=vz_poc
export POSTGRES_HOST=localhost POSTGRES_PORT=5432   # host, not "db" — you're outside the compose network now
export GATEWAY_API_KEY=dev-gateway-key-change-me
export GATEWAY_RATE_LIMIT_PER_MIN=60
export BLUEMARBLE_BASE_URL=http://localhost:8081
export SALESFORCE_BASE_URL=http://localhost:8082

uvicorn app.asgi:app --reload --port 8090
```

Then point the orchestrator (wherever it's running) at `GATEWAY_MCP_URL=http://localhost:8090/mcp`.

### A mock (Bluemarble or Salesforce)

Same shape — only Postgres is a dependency:

```bash
docker compose up -d db

cd services/mock-bluemarble   # or mock-salesforce
python -m venv .venv && . .venv/Scripts/activate
pip install -r requirements.txt

export POSTGRES_USER=vz_poc POSTGRES_PASSWORD=change-me-locally POSTGRES_DB=vz_poc
export POSTGRES_HOST=localhost POSTGRES_PORT=5432

uvicorn app.main:app --reload --port 8081   # 8082 for mock-salesforce
```

### UI

The UI is static files with no build step — `chat.js` defaults `ORCHESTRATOR_BASE_URL` to `http://localhost:8000`, so as long as the orchestrator is reachable there, you can just open [`services/ui/index.html`](../services/ui/index.html) directly in a browser, or serve the folder with anything static:

```bash
cd services/ui
python -m http.server 8080
```

To point it at a non-default orchestrator URL, set `window.ORCHESTRATOR_BASE_URL` before `chat.js` loads (e.g. add a small inline `<script>` in `index.html`).

## 4. Troubleshooting

- **`KeyError: 'GATEWAY_API_KEY'` on startup** — both `gateway-mcp` and `orchestrator` read this with `os.environ[...]` (no default, since it's a credential). Make sure it's exported in whichever shell/`.env` is feeding that process, and that both services use the *same* value.
- **Chat replies are empty/error out, everything else works** — almost always missing or invalid AWS Bedrock credentials/region, or no model access granted for `BEDROCK_MODEL_ID` in that account/region. Health checks and DB-backed routes don't need AWS at all, so they'll look fine even when this is broken.
- **UI shows a network error calling `/chat` when `ui` and `orchestrator` run in separate containers on different ports** — there's no CORS middleware on the orchestrator today, so a browser can block the cross-origin POST from `localhost:8080` to `localhost:8000` depending on browser/version. If you hit this, either serve the UI as a plain local file (`file://` origin issues aside, `python -m http.server` from `services/ui` works around it in practice) or add `fastapi.middleware.cors.CORSMiddleware` to `api.py` for local dev.
- **`gateway-mcp` can't reach Postgres when run outside Docker** — set `POSTGRES_HOST=localhost` (the container network hostname `db` only resolves inside the Compose network).
- **Seed data missing** — rerun `python scripts/seed_db.py --check`; the SQL under `db/init/` only runs automatically on a *fresh* Postgres volume (`docker compose down -v` to force re-seeding).
