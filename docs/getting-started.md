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

Once containers report healthy, verify the seed data and MCP surface from the host. These `scripts/` helpers get their own venv at the repo root, kept separate from any service's venv and from system Python:

```bash
python -m venv .venv && . .venv/Scripts/activate   # macOS/Linux: source .venv/bin/activate
pip install -r scripts/requirements.txt
python scripts/seed_db.py --check         # confirms seed data landed in Postgres
python scripts/mcp_smoke_test.py          # confirms the Gateway's MCP server answers tools/list + tools/call
```

Then either:
- Open **http://localhost:8080** for the chat UI, or
- Drive the API directly (same `.venv`, activate it again if you're in a new shell):
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
| `db` (Postgres) | 5433 (host) → 5432 (container) | `pg_isready` | — |
| `mock-bluemarble` | 8081 | `GET /health` | `db` |
| `mock-salesforce` | 8082 | `GET /health` | `db` |
| `gateway-mcp` | 8090 | `GET /health` | `db`, `mock-bluemarble`, `mock-salesforce` |
| `orchestrator` | 8000 | `GET /health` | `gateway-mcp` |
| `ui` | 8080 | `GET /` | `orchestrator` |

Every Python service is `FROM python:3.12-slim`, installs its own `requirements.txt`, and is run with Uvicorn (see each `Dockerfile`). `ui` is plain static files served by nginx — no build step.

## 3. Running the services one by one (active development, no shortcuts)

This is the full manual walkthrough — bring each service up standalone, in dependency order, verifying each with a health check before starting the next. Useful when you're actively developing one service and want `--reload` on it, or just want to understand the stack piece by piece. If you just want everything running, use §1 instead.

Every step assumes you're at the repo root unless a step says `cd`. Commands below are written for bash (Git Bash on Windows, or a regular shell on macOS/Linux) — each venv activation line calls out the macOS/Linux path inline. If you're on Windows PowerShell instead, replace `export VAR=value` with `$env:VAR = "value"` and `. .venv/Scripts/activate` with `.venv\Scripts\Activate.ps1`.

Each service that has its own `requirements.txt` (`mock-bluemarble`, `mock-salesforce`, `gateway-mcp`, `orchestrator`) gets its **own** `.venv` inside that service's directory — their dependency sets diverge (e.g. `orchestrator` pulls in `langgraph`/`boto3`, the mocks don't), so a shared venv isn't safe to reuse across them. `ui` has no `requirements.txt` and needs no venv at all — it's served with the plain system `python -m http.server`.

### 1. `db` — Postgres

Everything else depends on this, and it's the one piece not worth running outside Docker (schema-per-mocked-system init scripts under `db/init/` run automatically on first boot).

```bash
cp .env.example .env   # if you haven't already — this is where POSTGRES_* come from
docker compose up -d db
```

Verify:
```bash
docker compose ps db          # should show "healthy"
```

**Test locally** — connect with `psql` and confirm the seed data actually landed (not just that the process is up):
```bash
docker compose exec db psql -U vz_poc -d vz_poc -c "\dn"                                          # schemas: bluemarble, salesforce, analytics, audit
docker compose exec db psql -U vz_poc -d vz_poc -c "SELECT id, monthly_price FROM bluemarble.product_offering;"  # OFFER-20GB / OFFER-50GB / OFFER-UNLIMITED
docker compose exec db psql -U vz_poc -d vz_poc -c "SELECT customer_id, name FROM analytics.customer_360;"       # CUST-1001 | Anna de Groot
```
Same check, scripted: `python scripts/seed_db.py --check`. If any of this comes back empty, the init scripts under `db/init/` didn't run — see [Troubleshooting](#4-troubleshooting).

### 2. `mock-bluemarble` — catalog + order management mock (port 8081)

Depends on: `db`.

```bash
cd services/mock-bluemarble
python -m venv .venv && . .venv/Scripts/activate   # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt

export POSTGRES_USER=vz_poc POSTGRES_PASSWORD=change-me-locally POSTGRES_DB=vz_poc
export POSTGRES_HOST=localhost POSTGRES_PORT=5433   # host, not "db" — you're outside the compose network here (5433, not Postgres's default 5432 — see docker-compose.yml)

uvicorn app.main:app --reload --port 8081
```

Verify: `curl http://localhost:8081/health` → `{"status": "ok"}`.

**Test locally** — exercise the actual TM Forum-shaped endpoints, not just health:
```bash
curl http://localhost:8081/catalog                                              # returns the 3 seeded product offerings
curl -X POST http://localhost:8081/productOrderingManagement/v4/productOrder \
  -H "Content-Type: application/json" \
  -d '{"customer_id": "CUST-1001", "product_offering_id": "OFFER-50GB"}'        # 201, returns the new order incl. its id
curl http://localhost:8081/productOrderingManagement/v4/productOrder/<id-from-above>   # should echo the same order back
```

(Or skip the venv and just run it in Docker: `docker compose up -d mock-bluemarble`.)

### 3. `mock-salesforce` — case management mock (port 8082)

Depends on: `db`. Same shape as step 2:

```bash
cd services/mock-salesforce
python -m venv .venv && . .venv/Scripts/activate   # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt

export POSTGRES_USER=vz_poc POSTGRES_PASSWORD=change-me-locally POSTGRES_DB=vz_poc
export POSTGRES_HOST=localhost POSTGRES_PORT=5433

uvicorn app.main:app --reload --port 8082
```

Verify: `curl http://localhost:8082/health` → `{"status": "ok"}`.

**Test locally** — create a case and read it back:
```bash
curl -X POST http://localhost:8082/Case \
  -H "Content-Type: application/json" \
  -d '{"customer_id": "CUST-1001", "subject": "Local smoke test", "reason": "testing"}'   # 201, returns CASE-<n>
curl http://localhost:8082/Case/<id-from-above>                                          # should echo the same case back
```
Set `"force_fail": true` in the POST body to exercise the induced-failure path the orchestrator's compensation logic handles (see [`demo-script.md`](demo-script.md)) — it returns a `500` instead of creating the case.

(Or: `docker compose up -d mock-salesforce`.)

### 4. `gateway-mcp` — MCP server + AuthN/rate-limit/idempotency/audit (port 8090)

Depends on: `db`, `mock-bluemarble`, `mock-salesforce` (steps 1–3 must be reachable first).

```bash
cd services/gateway-mcp
python -m venv .venv && . .venv/Scripts/activate   # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt

export POSTGRES_USER=vz_poc POSTGRES_PASSWORD=change-me-locally POSTGRES_DB=vz_poc
export POSTGRES_HOST=localhost POSTGRES_PORT=5433
export GATEWAY_API_KEY=dev-gateway-key-change-me   # must match what you'll export for orchestrator in step 5
export GATEWAY_RATE_LIMIT_PER_MIN=60
export BLUEMARBLE_BASE_URL=http://localhost:8081
export SALESFORCE_BASE_URL=http://localhost:8082

uvicorn app.asgi:app --reload --port 8090
```

Verify: `curl http://localhost:8090/health` → `{"status": "ok"}`.

**Test locally:**
```bash
curl -X POST http://localhost:8090/mcp                                          # no api key → 401 (auth middleware is doing its job)
curl -X POST http://localhost:8090/mcp -H "x-api-key: dev-gateway-key-change-me"  # authenticated, but not a real MCP request → still tells you auth passed
```
For a real check of the MCP protocol surface (`tools/list`/`tools/call` over streamable HTTP — not something plain `curl` can drive), run:
```bash
python scripts/mcp_smoke_test.py
```
once this and step 1's seed data are both up. It confirms all 7 tools are discoverable, unauthenticated calls are rejected, and one authenticated `get_catalog` round-trip works end to end.

### 5. `orchestrator` — LangGraph agents, `/chat` and `/approve/{id}` (port 8000)

Depends on: `gateway-mcp` (step 4). This is where the router and the three agent nodes (`app/agents/*.py`) live — the one you'll touch most.

```bash
cd services/orchestrator
python -m venv .venv && . .venv/Scripts/activate   # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt

export GATEWAY_MCP_URL=http://localhost:8090/mcp
export GATEWAY_API_KEY=dev-gateway-key-change-me   # same value as step 4
export AWS_REGION=eu-west-1
export BEDROCK_MODEL_ID=anthropic.claude-3-5-sonnet-20241022-v2:0
# AWS credentials: exported env vars (AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY / AWS_SESSION_TOKEN),
# or your default ~/.aws profile — boto3's normal credential chain. Required for any actual chat reply.

uvicorn app.api:app --reload --port 8000
```

Verify: `curl http://localhost:8000/health` → `{"status": "ok"}`.

**Test locally** — send an actual chat turn (requires working AWS Bedrock creds; use the seeded `CUST-1001`):
```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"customer_id": "CUST-1001", "thread_id": "local-test-1", "message": "How much data have I used this month?"}'
```
A working reply means the full chain — orchestrator → gateway-mcp (auth'd) → mock-bluemarble → Postgres → Bedrock — is wired correctly. To confirm the branching logic too (auto-approve / escalation / partial-failure + compensation), run one of the `scripts/golden_path_test.py --branch ...` commands from §1.

### 6. `ui` — static chat UI (port 8080)

Depends on: `orchestrator` (step 5). No build step — plain HTML/CSS/JS.

```bash
cd services/ui
python -m http.server 8080
```

`chat.js` defaults `ORCHESTRATOR_BASE_URL` to `http://localhost:8000`, so this works as-is once step 5 is up. To point it at a non-default orchestrator URL, set `window.ORCHESTRATOR_BASE_URL` before `chat.js` loads (e.g. a small inline `<script>` in `index.html`).

Open **http://localhost:8080** and verify the chat responds.

**Test locally** — no separate API test needed here since it's a static frontend; the real test is exercising it in a browser: open dev tools' Network tab, send a message, and confirm a `POST /chat` fires against `http://localhost:8000` and renders the reply. A blank/erroring UI with a healthy `orchestrator` from step 5 is almost always the CORS issue noted below, not a UI bug.

## 4. Troubleshooting

- **Postgres port 5432 already in use / auth fails against the Docker `db` even with the right password** — usually a native Postgres install on the host (common on Windows/Mac dev machines) already bound to 5432, silently answering instead of the container. `docker-compose.yml` maps the `db` service to **host port 5433** (container-internal port stays the standard 5432) specifically to avoid this collision. Any *host*-side connection — `psql -h localhost`, pgAdmin, or a service run standalone outside Docker (§3) — must use port **5433**, not 5432. Containers talking to each other over the Compose network (`POSTGRES_HOST=db`) are unaffected; they always use 5432 internally.
- **`KeyError: 'GATEWAY_API_KEY'` on startup** — both `gateway-mcp` and `orchestrator` read this with `os.environ[...]` (no default, since it's a credential). Make sure it's exported in whichever shell/`.env` is feeding that process, and that both services use the *same* value.
- **Chat replies are empty/error out, everything else works** — almost always missing or invalid AWS Bedrock credentials/region, or no model access granted for `BEDROCK_MODEL_ID` in that account/region. Health checks and DB-backed routes don't need AWS at all, so they'll look fine even when this is broken.
- **UI shows a network error calling `/chat` when `ui` and `orchestrator` run in separate containers on different ports** — there's no CORS middleware on the orchestrator today, so a browser can block the cross-origin POST from `localhost:8080` to `localhost:8000` depending on browser/version. If you hit this, either serve the UI as a plain local file (`file://` origin issues aside, `python -m http.server` from `services/ui` works around it in practice) or add `fastapi.middleware.cors.CORSMiddleware` to `api.py` for local dev.
- **`gateway-mcp` can't reach Postgres when run outside Docker** — set `POSTGRES_HOST=localhost` (the container network hostname `db` only resolves inside the Compose network).
- **Seed data missing** — rerun `python scripts/seed_db.py --check`; the SQL under `db/init/` only runs automatically on a *fresh* Postgres volume (`docker compose down -v` to force re-seeding).
