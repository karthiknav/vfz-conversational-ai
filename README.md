# VodafoneZiggo Conversational AI — POC

A thin vertical slice proving the full RFP reference architecture (see [`vz-rfp-poc-plan.md`](vz-rfp-poc-plan.md)) end-to-end through one golden-path use case: a mobile data-bundle upgrade journey through Advise → Configure → Action. Real orchestration, real MCP gateway, real governance enforcement, real observability — mocked Bluemarble/Salesforce/Snowflake. See [`docs/mapping.md`](docs/mapping.md) for exactly what's real vs. mocked and how each mock swaps to its production system.

## Architecture

```
UI (static chat)  ──▶  Orchestrator (LangGraph, FastAPI)  ──▶  MCP Gateway (real MCP protocol)
                                                                     │
                                            ┌────────────────────────┼────────────────────────┐
                                            ▼                        ▼                          ▼
                                    mock-bluemarble          mock-salesforce            Postgres (analytics.*
                                    (TMF622-shaped)           (Case mgmt)                Snowflake-mock views,
                                                                                          audit.audit_trail)
```

Three agents (Knowledge / Transactional / Governance), each bound to a different least-privilege MCP tool subset — see [`docs/architecture-decisions.md`](docs/architecture-decisions.md) for why, and the plan file's "Is This an Agentic Flow?" section for the full design rationale.

## Quick start (local, Docker Compose)

```
cp .env.example .env          # fill in AWS credentials + Langfuse keys (both optional to start containers)
docker compose up --build
python -m pip install -r scripts/requirements.txt
python scripts/seed_db.py --check         # confirm seed data landed
python scripts/mcp_smoke_test.py          # confirm the Gateway's MCP server works
```

Open http://localhost:8080 for the chat UI, or drive the API directly (requires AWS Bedrock credentials in `.env` — every turn calls Claude):

```
python scripts/golden_path_test.py --branch auto_approve
python scripts/golden_path_test.py --branch escalate
python scripts/golden_path_test.py --branch partial_failure
```

Full click-through walkthrough with expected outputs: [`docs/demo-script.md`](docs/demo-script.md).

## Services

| Service | Port | Purpose |
|---|---|---|
| `ui` | 8080 | Static chat UI |
| `orchestrator` | 8000 | LangGraph agents, `/chat` and `/approve/{id}` |
| `gateway-mcp` | 8090 | Real MCP server + AuthN/rate-limit/idempotency/audit |
| `mock-bluemarble` | 8081 | TMF622-shaped catalog + order management mock |
| `mock-salesforce` | 8082 | Case management mock |
| `db` | 5432 | Shared Postgres — schema-per-mocked-system + audit trail |

## Docs

- [`vz-rfp-poc-plan.md`](vz-rfp-poc-plan.md) — the build plan this POC implements (sample data, turn-by-turn golden path, agentic design)
- [`docs/getting-started.md`](docs/getting-started.md) — running the full stack or any single component locally, plus troubleshooting
- [`docs/code-flow.md`](docs/code-flow.md) — a request traced end-to-end through every file, plus the ASGI/MCP client-server mechanics
- [`docs/mapping.md`](docs/mapping.md) — POC component → RFP diagram box → real system swap-in
- [`docs/architecture-decisions.md`](docs/architecture-decisions.md) — ADR log for the notable implementation calls
- [`docs/demo-script.md`](docs/demo-script.md) — click-through walkthrough of all three golden-path branches
- [`docs/eval-cases.md`](docs/eval-cases.md) — phase-gate eval checklist

## AWS deployment

CDK stacks under `infra/cdk/` deploy the same services to ECS Fargate + Aurora Serverless v2; see that directory's own notes for the docker-compose → AWS resource mapping.
