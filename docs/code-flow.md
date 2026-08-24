# Code Flow: A Knowledge Agent Request

Walks one request end-to-end — "how much data have I used this month?" — through every file and network hop it touches, then explains the two pieces of plumbing that are easy to misread on a first pass: the ASGI layer inside `gateway-mcp`, and the client/server split across the two services. Closes with how to extend the setup with another MCP server, and how the mocked backends here map to real ones later. See [`mapping.md`](mapping.md) for the full POC-component → RFP-box table and [`architecture-decisions.md`](architecture-decisions.md) for the ADRs behind these choices.

## 1. The request, step by step

```
Browser (chat.js)
   │  POST /chat  {customer_id, thread_id, message}
   ▼
Orchestrator — FastAPI (api.py)
   │  graph.ainvoke(input_state, config)
   ▼
LangGraph StateGraph (graph.py)
   │  router_node  → Bedrock Claude classifies intent
   │  route_after_router("knowledge") → knowledge_agent node
   ▼
knowledge_agent.run() (agents/knowledge_agent.py)
   │  create_react_agent(llm, tools) — Claude decides to call a tool
   ▼
mcp_client.knowledge_agent_tools() (mcp_client.py)
   │  MultiServerMCPClient — MCP tool call over streamable HTTP
   ▼
   ══════════════ network hop: orchestrator container → gateway-mcp container ══════════════
   ▼
Gateway ASGI app (asgi.py)
   │  RateLimitMiddleware → APIKeyAuthMiddleware → Mount("/mcp") → mcp_app
   ▼
MCP protocol server (mcp_server.py)
   │  @mcp.tool() get_customer_usage(...) — thin wrapper
   ▼
snowflake_tools.get_customer_usage() (tools/snowflake_tools.py)
   │  SELECT * FROM analytics.vw_customer_usage_spend WHERE customer_id = $1
   │  record_audit(...) → audit.audit_trail
   ▼
Postgres (db/init/004_governed_views.sql)
   │  result flows back up through every layer above
   ▼
Claude drafts the reply → knowledge_agent.run() returns → graph END
   │  checkpointer (MemorySaver) persists updated thread state
   ▼
api.py returns ChatResponse → chat.js renders the bubble
```

### 1.1 Browser → Orchestrator

[`services/ui/chat.js`](../services/ui/chat.js) POSTs `{customer_id, thread_id, message}` to `POST /chat` on the orchestrator.

### 1.2 FastAPI entry point

[`services/orchestrator/app/api.py`](../services/orchestrator/app/api.py) `chat()`:
- Gets the compiled LangGraph (`get_graph()`, built once and cached — see [`graph.py`](../services/orchestrator/app/graph.py)).
- Loads existing checkpoint state for `thread_id` (`MemorySaver`, in-process — becomes `AsyncPostgresSaver` on AWS).
- If it's a new thread, seeds `phase="advise"`, `pending_proposal=None`, etc.
- Calls `graph.ainvoke(input_state, config)`.

### 1.3 Router node

[`graph.py`](../services/orchestrator/app/graph.py) `router_node`:
- Calls Bedrock Claude (`get_llm().with_structured_output(RouterDecision)`) with a system prompt classifying the message into `knowledge` / `transactional` / `out_of_scope`.
- `route_after_router` sends `knowledge` intent to the `knowledge_agent` node via a LangGraph conditional edge.

### 1.4 Knowledge agent node

[`agents/knowledge_agent.py`](../services/orchestrator/app/agents/knowledge_agent.py) `run()`:
- Lazily builds a `create_react_agent` (LangGraph's prebuilt ReAct loop) bound to Claude plus whatever tools `knowledge_agent_tools()` returns.
- Prepends a system prompt via `session_prefix()` ([`agents/common.py`](../services/orchestrator/app/agents/common.py)) that forces the LLM to pass `customer_id`/`thread_id` on every tool call.
- Invokes the ReAct agent; Claude decides whether to call `get_customer_usage`, `get_customer_profile`, both, or neither.

### 1.5 Tool binding — the MCP client

[`mcp_client.py`](../services/orchestrator/app/mcp_client.py) `knowledge_agent_tools()` calls `get_tools_for({"get_customer_usage", "get_customer_profile"})`:
- Uses `MultiServerMCPClient` (from `langchain-mcp-adapters`) to connect over **streamable HTTP** to the Gateway at `http://gateway-mcp:8090/mcp`, with an `x-api-key` header.
- Filters the full advertised tool list down to just these two names.

This filter is the actual enforcement mechanism for "the Knowledge Agent is read-only": it is never handed `submit_order`, `propose_order`, or any write tool — not because a prompt tells it not to, but because those tool objects never enter its tool list.

### 1.6 Gateway MCP server (a separate container)

The request lands on [`asgi.py`](../services/gateway-mcp/app/asgi.py) and passes through middleware in order — see §2 for why this shape exists:

1. `RateLimitMiddleware` — in-memory fixed-window counter per API key.
2. `APIKeyAuthMiddleware` — checks `x-api-key` against `GATEWAY_API_KEY`.
3. `Mount("/mcp")` hands off to `mcp_app`, the actual MCP protocol server, which dispatches the `tools/call` JSON-RPC to the registered handler.

### 1.7 MCP tool registration

[`mcp_server.py`](../services/gateway-mcp/app/mcp_server.py) `get_customer_usage` is a thin `@mcp.tool()` wrapper that owns nothing but registration — it immediately delegates to `snowflake_tools.get_customer_usage`. This split (registration here, logic in `app/tools/*.py`) is what lets the tool logic stay testable without an MCP client in the loop — see ADR-1.

### 1.8 Actual data access

[`tools/snowflake_tools.py`](../services/gateway-mcp/app/tools/snowflake_tools.py):
- Runs a fixed, named query (`SELECT * FROM analytics.vw_customer_usage_spend WHERE customer_id = $1`) via the shared connection pool — there is no raw/dynamic SQL surface exposed to an agent anywhere in this module, by design.
- The view is defined in [`db/init/004_governed_views.sql`](../db/init/004_governed_views.sql), joining `customer_360` and `product_offering` in Postgres (standing in for Snowflake).
- Calls `record_audit()` ([`middleware/audit_logging.py`](../services/gateway-mcp/app/middleware/audit_logging.py)) to insert a row into `audit.audit_trail` — every tool call does this, no exceptions.
- Returns a JSON-serializable dict back up through the MCP protocol.

### 1.9 Result flows back up

- The MCP client receives the tool result as a `ToolMessage` and feeds it back into the ReAct loop.
- Claude (via [`bedrock.py`](../services/orchestrator/app/bedrock.py), optionally wrapped by Bedrock Guardrails) drafts a natural-language reply citing the real numbers.
- `knowledge_agent.run()` returns `{"messages": new_messages, "phase": "advise"}`.
- The graph edge `knowledge_agent → END` ends this invocation; the checkpointer persists the updated state under `thread_id`.
- `api.py` pulls the latest `AIMessage` text (`_latest_ai_text`) and returns a `ChatResponse`, which `chat.js` renders as a chat bubble.

**Key design point:** the read-only guarantee on the Knowledge Agent is structural, not a trusted LLM instruction — the tool list handed to its ReAct loop physically excludes every write tool (`mcp_client.py`'s `KNOWLEDGE_TOOLS` set).

## 2. What ASGI is, and why `gateway-mcp` has its own layer of it

ASGI (Asynchronous Server Gateway Interface) is Python's standard contract between a web server and a web application — the async successor to WSGI. It is not MCP-specific; it's the plumbing that lets a server process (Uvicorn here) speak HTTP to a Python app in a standard, `async`/`await`-friendly way. FastAPI and Starlette are both ASGI apps; `app = FastAPI(...)` in `asgi.py` is the literal object Uvicorn runs (`uvicorn app.asgi:app`).

Rough equivalent for anyone coming from Java: Uvicorn plays the role Tomcat plays for servlets — it binds the socket, speaks HTTP, and dispatches each request into your app via a standard interface. The differences are that Uvicorn is deliberately thin (single async event loop, no bundled sessions/JSP/multi-app hosting — one ASGI app per process, usually run under several Uvicorn/Gunicorn worker processes) where Tomcat is a heavier container with more built in.

The MCP Python SDK's `FastMCP` object already produces its own ASGI app via `mcp.streamable_http_app()` — that alone could run standalone. This project instead wraps it inside a second, ordinary FastAPI app and mounts it as a sub-app:

```python
# asgi.py
mcp_app = mcp.streamable_http_app()
...
app = FastAPI(title="VZ MCP Gateway", lifespan=lifespan)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(APIKeyAuthMiddleware)
app.router.routes.append(Mount("/mcp", app=mcp_app))
```

Why (ADR-1): the MCP SDK's own middleware ergonomics are thin, so rather than fighting the protocol server object to add auth/rate-limiting/health-checks, the outer FastAPI app owns those cross-cutting concerns as ordinary Starlette middleware, and `Mount` nests the real MCP server underneath it at `/mcp` — the same way you'd nest one router inside another, because both are just ASGI apps underneath.

Request path through the one `gateway-mcp` process:

```
HTTP request
  → outer FastAPI app (asgi.py)
      → RateLimitMiddleware
      → APIKeyAuthMiddleware
      → Mount("/mcp") → mcp_app (mcp_server.py)
          → MCP protocol handling: tools/list, tools/call
          → dispatches to the matching @mcp.tool() function
```

## 3. Client vs. server: two different services, not one talking to itself

This is easy to misread because both roles live in this one repo, but they are two separate containers with two separate responsibilities:

| | Role | File |
|---|---|---|
| `orchestrator` | MCP **client** | [`mcp_client.py`](../services/orchestrator/app/mcp_client.py) — uses `MultiServerMCPClient` to *call* tools |
| `gateway-mcp` | MCP **server** | [`mcp_server.py`](../services/gateway-mcp/app/mcp_server.py) — *hosts* and exposes tools |

They run as separate Docker Compose services and talk over the network via streamable HTTP (`orchestrator` → `http://gateway-mcp:8090/mcp`). The orchestrator is never "the MCP server to itself" — it's a client of a different process. The repo happens to own both ends of this particular integration (unlike calling a genuinely external vendor's MCP server), which is what makes it feel self-referential, but architecturally it's an ordinary client ↔ network ↔ server pair.

## 4. Connecting another MCP server (e.g. a future Ziggo-side one)

`MultiServerMCPClient` is already built to hold more than one named connection — adding a server is a config change in `mcp_client.py`, not a new abstraction:

```python
GATEWAY_URL = os.environ.get("GATEWAY_MCP_URL", "http://gateway-mcp:8090/mcp")
GATEWAY_API_KEY = os.environ["GATEWAY_API_KEY"]

ZIGGO_MCP_URL = os.environ["ZIGGO_MCP_URL"]
ZIGGO_MCP_API_KEY = os.environ["ZIGGO_MCP_API_KEY"]

def _client_config() -> dict:
    return {
        "gateway": {
            "url": GATEWAY_URL,
            "transport": "streamable_http",
            "headers": {"x-api-key": GATEWAY_API_KEY},
        },
        "ziggo": {
            "url": ZIGGO_MCP_URL,
            "transport": "streamable_http",  # or "sse" / "stdio" depending on what they expose
            "headers": {"Authorization": f"Bearer {ZIGGO_MCP_API_KEY}"},
        },
    }
```

`client.get_tools()` returns the **union** of tools from every configured server as one flat list, which is exactly what `get_tools_for()` already filters by name — no other code needs to change.

Steps:

1. **Add the connection** to `_client_config()` as above.
2. **Decide which agent gets the new tools** — extend an existing set (`KNOWLEDGE_TOOLS`, `TRANSACTIONAL_TOOLS`, `GOVERNANCE_TOOLS`) with the new tool names, or, if it's a genuinely new capability, add a fourth tool set plus a fourth LangGraph node in `graph.py` and teach the router prompt about the new intent.
3. **Watch for tool-name collisions.** Since `get_tools()` flattens across servers, two servers exposing a tool with the same name would silently collide in the name-based filter. Check names up front, or namespace them (`ziggo_get_x`) if you control the naming.
4. **Wire env vars** into `docker-compose.yml` under the `orchestrator` service (`ZIGGO_MCP_URL`, `ZIGGO_MCP_API_KEY`) and add them to `.env.example`.

This only applies when Ziggo's server is an *external* MCP endpoint you're pointing at. If instead the plan is to build a wrapper/mock for a new backend the way `gateway-mcp` already wraps Bluemarble/Salesforce/Snowflake, there is no second `MultiServerMCPClient` entry at all — you'd add a tool module under `services/gateway-mcp/app/tools/` and register `@mcp.tool()` wrappers in `mcp_server.py`, and it would simply show up as more tools on the existing `gateway` connection.

## 5. Mocked tools today vs. real backends later

Per [`mapping.md`](mapping.md), `gateway-mcp` is deliberately split into two layers with very different lifespans:

- **The MCP protocol layer** — `mcp_server.py`'s `@mcp.tool()` registrations, tool schemas, `tools/list` advertisement, and the outer ASGI middleware (auth, rate limiting) — is real and does not change when a mock is replaced.
- **The tool implementation bodies** — `tools/snowflake_tools.py`, `tools/bluemarble_tools.py`, `tools/salesforce_tools.py` — are mocked today (Postgres standing in for Snowflake; small FastAPI mock services standing in for Bluemarble/Salesforce).

Concretely:

```python
@mcp.tool()
async def get_customer_usage(customer_id: str, thread_id: str) -> dict:
    return await snowflake_tools.get_customer_usage(customer_id, thread_id)
```

The wrapper and its schema never change. What changes in production is only what's inside `snowflake_tools.get_customer_usage()` — today it queries a local Postgres view; in production it queries real Snowflake. Same story for Bluemarble and Salesforce: point `BLUEMARBLE_BASE_URL` / `SALESFORCE_BASE_URL` at the real APIs and swap the credential, and the tool schema and every agent above it are untouched.

This means the default real-world assumption in this codebase is **connecting to ordinary REST/SQL APIs**, not to a vendor's own MCP server — because none of Bluemarble, Salesforce, or Snowflake natively speak MCP. `gateway-mcp` exists specifically to be the one place that translates plain backend APIs into MCP tools, with a single shared point for auth/rate-limiting/audit in front of all of them, rather than every agent talking raw REST directly.

The exception is §4 above: if a backend (Ziggo-side or third-party) *already* exposes a real MCP server, you don't rebuild a wrapper for it — you either point the orchestrator's `MultiServerMCPClient` directly at it, or still proxy it through `gateway-mcp` if you want the centralized auth/rate-limit/audit story to keep covering it.
