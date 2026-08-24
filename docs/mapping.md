# POC Component → RFP Architecture Mapping

One row per POC component. This is the document that makes the "mock→real should be a config/credential swap, not a rewrite" claim concrete and checkable.

| RFP diagram box | POC component | What's real vs. mocked | Real system it stands in for | Swap-in plan |
|---|---|---|---|---|
| UI Layer (Website/App) | `services/ui/` | Real (static chat UI, one channel) | VZ website / MyZiggo app chat surface | Replace with the production frontend; it only needs the same `/chat` and `/approve/{id}` contract |
| Central Orchestration Engine / Journey State Manager / Context & Memory Manager | `services/orchestrator/app/graph.py`, `state.py` | Real (LangGraph StateGraph + checkpointer) | — (this component doesn't exist yet at VZ) | Swap `MemorySaver` → `AsyncPostgresSaver` against Aurora (already the plan for the AWS phase) |
| Intent Understanding / Agent Discovery / Orchestration & Planning | `services/orchestrator/app/graph.py` (router_node) | Real (LLM-backed router + conditional edges) | — | No swap needed — this logic doesn't depend on backend system identity |
| Model & AI Services (LLMs) | `services/orchestrator/app/bedrock.py` | Real (Amazon Bedrock, Claude) | Same in production | No swap — this already targets Bedrock directly |
| Model & AI Services (Content Moderation) | `services/orchestrator/app/bedrock.py` (guardrail_config) | Real (Bedrock Guardrails) | Same in production | No swap |
| Secure MCP/API Tooling & Integration Gateway | `services/gateway-mcp/` | Real MCP protocol server + real AuthN/rate-limit/idempotency/audit middleware; **mocked backend tool implementations** | Enterprise API/MCP gateway | Backend systems change; gateway protocol layer, middleware, and tool schemas do not |
| MCP/Tool Registry | `services/gateway-mcp/app/mcp_server.py` | Real (`tools/list` capability advertisement) | — | No swap |
| AuthN/AuthZ | `services/gateway-mcp/app/middleware/auth.py` | Real pattern, dummy API key | CIAM / OAuth2 client-credentials | Swap the credential check; middleware interface unchanged |
| Idempotency + Reconciliation | `services/gateway-mcp/app/middleware/idempotency.py` | Real (audit-trail-backed dedup) | Same in production | No swap |
| Transactional Agents (Commerce/Order Mgmt) | `services/orchestrator/app/agents/transactional_agent.py` | Real agent logic, mocked backend | Bluemarble / CPQ | Point `BLUEMARBLE_BASE_URL` at the real Bluemarble API + swap Secrets Manager credential; tool schema and agent code unchanged |
| Transactional Agents (Billing) | `services/gateway-mcp/app/tools/snowflake_tools.py` (usage/spend) | Real read path, mocked source | Billing/Commerce | Point the governed view at the real Snowflake/billing warehouse table |
| Governance Agents (Policy Enforcement, Human Approval) | `services/orchestrator/app/agents/governance_agent.py`, `services/gateway-mcp/app/tools/bluemarble_tools.py` (submit_order's server-side re-check) | Real policy logic, mocked eligibility data | Real policy/eligibility service | Point `vw_order_eligibility` at the production eligibility source; policy threshold logic unchanged |
| Governance Agents (Audit & Traceability) | `db/init/001_audit_trail.sql`, `services/gateway-mcp/app/middleware/audit_logging.py` | Real | Same in production | No swap — this is the audit system, not a mock of one |
| Data & Knowledge Foundation — Commerce/Order Mgmt/Catalog | `services/mock-bluemarble/` | Mocked (TM Forum-shaped REST) | Bluemarble (Comviva) | Replace service with real Bluemarble endpoint + credentials |
| Data & Knowledge Foundation — CRM/Case Mgmt | `services/mock-salesforce/` | Mocked | Salesforce | Replace service with real Salesforce REST/Bulk API (or Agentforce, if VZ exposes it as a peer agent — open question, see source plan §9) |
| Data & Knowledge Foundation — Customer 360/Analytics | `db/init/003_customer360_seed.sql`, `004_governed_views.sql` | Mocked (Postgres standing in for Snowflake) | Snowflake | Point governed-view queries at Snowflake (or Cortex Analyst semantic views) instead of Postgres views; agent-facing tool contract unchanged |
| Semantic Layer (Query Translation, Governed Access) | `services/gateway-mcp/app/tools/snowflake_tools.py` | Real pattern (named parameterized functions, never raw SQL) | Same principle applies against real Snowflake | No swap in principle — the "no raw SQL from an agent" rule holds regardless of backend |
| Enterprise Governance/Security Control Plane — Secrets | `.env.example` locally, Secrets Manager (AWS phase) | Real pattern | Same | No swap — this already uses Secrets Manager in the CDK stacks |
| Enterprise Governance/Security Control Plane — Observability | `services/orchestrator/app/langfuse_setup.py` | Real (Langfuse Cloud, EU) | Same in production, or self-hosted | Optional: self-host on AWS if VZ requires no third-party SaaS for trace data — see `architecture-decisions.md` |
