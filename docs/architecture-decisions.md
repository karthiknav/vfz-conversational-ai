# Architecture Decisions

Short ADR-style log. The point of this file is to turn "things the POC simplified" into documented, deliberate choices — for an RFP response, that distinction is the actual credibility play.

## ADR-1: Real MCP protocol server, not a REST facade

**Decision:** `services/gateway-mcp/` is a genuine MCP server (official `mcp` Python SDK, `FastMCP`, real `tools/list`/`tools/call` JSON-RPC over streamable HTTP), mounted as a sub-app inside an outer FastAPI app that owns AuthN, rate limiting, and health checks as ordinary ASGI middleware.

**Why:** the RFP's reference architecture names "MCP/Tool Registry" explicitly. Implementing genuine MCP protocol — not just an MCP-flavored REST API — is the literal fulfillment of that box, and lets the demo show real tool-discovery/capability-advertisement behavior, not a facsimile.

**Caveat:** the MCP SDK's own middleware ergonomics are thin, so cross-cutting concerns (auth, rate limiting) live in the outer app, not the MCP server object. Idempotency and audit logging are implemented as helper functions called from inside each tool (`app/middleware/idempotency.py`, `app/middleware/audit_logging.py`), not generic ASGI middleware — MCP tool calls arrive as JSON-RPC bodies (and can be SSE-streamed), so semantically-aware dedup/logging is more reliable done inside the tool function, which has full context, than by sniffing the transport layer generically.

**Fallback (not taken, but available):** because tool logic lives as plain Python functions regardless of transport, degrading to a REST facade with an OpenAPI-described tool catalog is a same-day pivot, not a rewrite.

## ADR-2: Governance enforcement lives in the Gateway tool, not just the LLM agent

**Decision:** `submit_order` (`services/gateway-mcp/app/tools/bluemarble_tools.py`) independently re-derives the price delta and re-checks eligibility server-side before writing anything, rather than trusting a `governance_decision` argument the calling LLM agent claims.

**Why:** the RFP's stated principle is "AI can *request* actions; platform services *decide* execution." If the Governance Agent's LLM node were the only enforcement point, a prompt-injected or simply mistaken agent could call `submit_order` for an out-of-policy upgrade and the platform would have no independent check. Enforcing the threshold in the tool itself makes this a structural guarantee, not a prompt-engineering hope.

## ADR-3: Single shared Postgres instance, schema-per-mocked-system

**Decision:** Bluemarble-mock, Salesforce-mock, and the Snowflake-mock analytics tables all live in one Postgres instance under `bluemarble.*`, `salesforce.*`, and `analytics.*` schemas (plus `audit.*` for the audit trail), instead of three separate database containers.

**Why:** this still proves per-system schema isolation and the "governed view, no raw SQL" pattern, while keeping local iteration to one DB container and mapping 1:1 to a single Aurora Serverless v2 cluster in the CDK phase. Splitting into physically separate databases later is additive, not a redesign — nothing above the DB layer knows or cares that it's one physical instance today.

## ADR-4: Deliberate anti-corruption-layer quirks in the mocks

**Decision:** each mock's JSON shape includes one intentionally realistic quirk — Bluemarble-mock nests price under `productOfferingPrice[0].price.taxIncludedAmount.value` the way real TMF622 does; Salesforce-mock uses a `Case_Status__c`-style picklist field instead of a clean enum. The Gateway's tool-adapter code (`_normalize_offering`, `_normalize_case`) normalizes both into the canonical shape the agents see.

**Why:** the source plan (`vz-rfp-poc-plan.md` §4) flags "no anti-corruption layer pattern shown shielding agents from legacy system quirks" as a gap in the RFP's own diagram. This is the cheapest possible proof that the gap was understood, not missed.

## ADR-5: Approval hand-off implemented via checkpointed state + `aupdate_state`, not LangGraph `interrupt()`

**Decision:** the Configure→Action boundary does not use LangGraph's `interrupt()`/`Command(resume=...)` primitive. Each HTTP request (a `/chat` turn or an `/approve` call) is already a separate graph invocation against the same persisted thread, which gives "pause across turns" for free via the checkpointer. The `/approve/{proposal_id}` endpoint calls `governance_agent.run()` directly as a plain function against the thread's current checkpointed state, then folds the result back in with `graph.aupdate_state(config, update, as_node="governance_agent")`.

**Why:** `interrupt()` is designed for pausing *within* a single `.invoke()` call to get external input before that same call continues. Our approval gate is a separate HTTP request that can arrive after other, unrelated chat turns on the same thread (the "what's my usage" example in the golden path) — using `interrupt()`/`Command(resume=...)` here would tie resumption to a specific paused run that later chat turns could invalidate. Driving the update through `aupdate_state` sidesteps that edge case entirely while still using the checkpointer for genuine cross-turn persistence, which is the part of LangGraph actually being demonstrated.

## ADR-6: Langfuse Cloud (EU region), not self-hosted

**Decision:** observability uses Langfuse Cloud's EU-hosted option rather than self-hosting on ECS.

**Why:** self-hosting Langfuse v3 needs ClickHouse + Redis + object storage + Postgres — disproportionate infrastructure for a thin vertical slice whose point is to prove the tracing *pattern*, not host an analytics platform. The EU region choice also gives a direct, concrete answer to source-plan gap #5 ("no data residency/sovereignty statement") for the one third-party data path in the system. Self-hosting on AWS remains a documented stretch upgrade if VZ requires no third-party SaaS for trace data at all.
