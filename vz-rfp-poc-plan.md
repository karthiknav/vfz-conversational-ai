# VodafoneZiggo Conversational AI Agent — RFP Context & POC Build Plan

> Working reference document. Intended to be used as project context in Claude Code while building the AWS POC.

---

## 1. Background: What This RFP Is

VodafoneZiggo (VZ) has issued an RFP (competing/incumbent vendor appears to be Cognizant, based on filename) for a **conversational AI agent platform** spanning their multiple brands (Vodafone, Ziggo).

**Business ambition:** Become a leading conversational telecom brand by 2028. Move customer experience from a static chat window to an adaptive interface combining natural conversation with visual components (forms, progress states, diagnostics, product cards, baskets, handover summaries, reward tiles).

**Phased capability model (this is the core structuring idea of the whole RFP):**

| Phase | Description | Risk level |
|---|---|---|
| **Advise** | AI understands customer needs, gives guidance/info: usage, spend, order summaries, troubleshooting, personalized recommendations | Low — read-only |
| **Configure** | AI helps customers complete tasks: invoice analysis, diagnostics, order summaries, selecting bundles/options/prices | Medium — proposes, doesn't commit |
| **Action-based** | AI handles actions customers explicitly approve: submitting an order, triggering service actions, while enforcing access rights and maintaining an audit trail | High — writes to backend systems |

**Target date:** H2 2027 for a market-facing branded AI interface. Acquisition sales use cases are the key differentiator; other use cases phased by feasibility, value, risk, and dependency readiness.

**Problem statement (VZ's own framing):** AI-enabled customer journeys introduce architectural risk beyond simple chat deployment. Advice-only use cases are becoming more feasible, but journeys that configure products or trigger actions depend on deep integration with existing (legacy) systems. **This integration risk — not the conversational AI itself — is the RFP's central challenge.**

---

## 2. The Reference Architecture (as shown in the RFP deck)

### Five vertical (functional) layers

1. **UI Layer** — Website, MyZiggo/Mobile App, Voice Bot/IVR, WhatsApp/Chat, Advisor Desktop, Contact Centre
2. **Omnichannel & Agent Orchestration Layer** — Intent Understanding, Agent Discovery, Task Decomposition, Journey State Manager, Orchestration & Planning, Context & Memory Manager, Evals/Guardrails/Governance — all coordinated by a **Central Orchestration Engine**
3. **Model & AI Services Layer** — LLMs (GPT/Claude/Gemini — multi-model, not vendor-locked), Embeddings, Classification, Speech-to-Text, Text-to-Speech, Content Moderation, Fine-tuned/Domain Models
4. **Business Capability Agent Layer** — Experience Agents (concierge, personalisation, voice, handover), Knowledge Agents (retrieval, content gen, brand voice, summarisation), Transactional Agents (commerce, CRM, billing, order mgmt, provisioning, appointments), Governance Agents (consent, risk assessment, human approval, policy enforcement, audit), Operations Agents (monitoring, evaluation, cost optimisation, incident diagnosis)
5. **Data & Knowledge Foundation** — Commerce, CRM, Billing, Product Catalogue, Customer 360, CMS/Knowledge Base, Interaction History, Orders & Fulfilment, Network/Service Inventory, Identity & Consent Store, Analytics & Telemetry, Legacy BSS

### Three horizontal (cross-cutting) layers

- **Secure MCP/API Tooling & Integration Gateway** — governed access to enterprise capabilities. **Key principle: AI can *request* actions; platform services *decide* execution.** Includes MCP/Tool Registry, API Catalogue + SLA Lifecycle, AuthN/AuthZ, Rate Limiting + Throttling, Idempotency + Reconciliation, Fallback + Recovery, Event/Queue Integration.
- **Semantic Layer (Knowledge and Meaning Bridge)** — Semantic Modeling, Vector embeddings/indexing, Customer Context Graph, Journey Knowledge Graph, Knowledge Graph & Relationships, Synonyms & Taxonomies, Contextual Mapping & Reasoning, Query Translation (Natural→Structured), Prompt + Persona Library.
- **Enterprise Governance, Security, Risk & Observability Control Plane** — Security & Compliance, Data Privacy, CIAM/IAM/RBAC, Consent Management, Brand & Policy Guardrails, Human Approval Gates, Audit & Traceability, Monitoring + LLMOps, KPIs & Analytics, Cost Controls.

### Known backend systems named in the RFP

- **Bluemarble** (Comviva) — TM Forum Open API-compliant BSS suite: CRM, Billing, Commerce, Order Management, CPQ, Ticket Management, Catalog.
- **Salesforce** — likely CRM / case management; possibly Agentforce-enabled (agent-to-agent capable, not just REST).
- **Snowflake** — analytical data layer: Customer 360, Interaction History, Analytics/Telemetry.
- **Content Guru** — likely contact centre/CCaaS platform.

---

## 3. What VZ Has Live Today (Current State, Real World)

- **TOBi** — original rules-based/NLP chatbot, launched 2017 on My Vodafone app, later extended to Ziggo/Vodafone websites. Originally **not connected to customer systems** — general info only, with handoff to a human who could read chat history. This is pure "Advise" tier, years before the RFP.
- **Deepdesk Agent Assist** — internal-only AI copilot for human contact centre advisors (not customer-facing). Suggests responses/links to advisors in real time to reduce average handling time. Built because even after chatbot deployment, ~80% of conversations still needed a human.
- **RAG-based GenAI chatbot (via Xomnia)** — the direct predecessor to this RFP. Customer-facing, live on the website, built with RAG over public website/forum content. A separate Agent Assist workstream added real-time call insights and auto call summaries for live agents.

**Where to see it:** ziggo.nl / vodafone.nl chat bubble, or the MyZiggo app. (Agent Assist tooling is internal-only, not visible externally.)

**The gap the RFP is asking to close:** today's bot can *answer* (RAG over public content, no account visibility, no write access). The RFP wants Configure + Action-based tiers layered on top — authenticated, transactional, auditable.

---

## 4. Gaps / Things to Flag in a Response

1. No defined handover SLA or context-transfer spec for agent→human escalation.
2. No agent-to-agent trust/authorization model (can a Transactional Agent call a Governance Agent directly, or only via orchestration?).
3. No error/rollback/compensation logic for partial action failures (e.g., billing updates but provisioning fails).
4. No latency/cost budget per layer — multi-model LLM + STT/TTS + semantic lookups stack latency fast, especially for voice/IVR.
5. No explicit data residency/sovereignty statement for using external hyperscaler models against EU telecom customer data (GDPR).
6. No agent/prompt/model versioning or rollback strategy for production behavior changes.
7. "Evals, Guardrails & Governance" is a single box — no detailed eval gate per phase transition (e.g., accuracy/safety bar required before an agent moves from Advise to Action for a given use case).
8. Legacy BSS integration risk is named in the RFP text but not architected — no explicit anti-corruption layer pattern shown shielding agents from legacy system quirks.
9. No mention of **TM Forum ODA** (Open Digital Architecture) as an explicit reference framework, despite Bluemarble being TM Forum API-compliant — worth mapping to for credibility if VZ's enterprise architects are TM Forum-aligned.

---

## 5. POC Objective

Build a **deployable, pattern-proven POC on AWS** that reproduces every layer of the reference architecture with **real orchestration/gateway/governance logic**, but **mocked backend systems** (no real Bluemarble/Salesforce/Snowflake access yet).

"Production ready" here means: **pattern-proven, not scale-tested.** Anyone reviewing it should see exactly how a real Bluemarble/Salesforce/Snowflake connection would slot in later without redesigning anything — i.e., mock→real should be a config/credential swap, not a rewrite.

### What's REAL in the POC
- Central Orchestration Engine (routing, journey state, context/memory)
- MCP/API Gateway (AuthN/AuthZ, rate limiting, idempotency, audit logging)
- Governance Agent logic (approval gates, policy checks)
- Semantic layer (intent → structured query translation, via fixed parameterized views — not open text-to-SQL)
- Full observability via Langfuse, wired through every hop from day one
- The phased capability model, implemented explicitly: Advise (read-only) → Configure (propose, don't execute) → Action (execute via Gateway with governance sign-off)

### What's MOCKED
- **Bluemarble** → small service implementing 2–3 TM Forum-shaped REST endpoints (e.g. `productOrderingManagement/v4/productOrder/{id}`) with structurally realistic fake JSON
- **Salesforce** → mock REST service mimicking a Case/Customer object with realistic field naming
- **Snowflake** → local Postgres/Aurora with a fake `customer_360` table, exposed only via 2–3 fixed governed views (never raw SQL from an agent)

---

## 6. Suggested AWS Architecture Mapping

| RFP Layer | AWS POC Implementation |
|---|---|
| UI Layer | Simple web chat UI (S3 + CloudFront, or a basic Next.js app on Amplify/ECS) — one channel is enough for POC |
| Central Orchestration Engine | ECS Fargate service (or Lambda if event-driven works better) running LangGraph or a hand-rolled state machine |
| Model & AI Services | Amazon Bedrock (Claude models) for LLM calls; Bedrock Guardrails for content moderation; Titan or Bedrock embeddings for RAG |
| MCP/API Gateway | Dedicated ECS Fargate service exposing MCP tools; fronted by Amazon API Gateway for external auth, throttling, and request logging |
| Business Capability Agents | Separate logical services/modules within the orchestration app (Knowledge, Transactional, Governance, Operations agents) — can start as modules in one service, split later |
| Data & Knowledge Foundation (mocked) | Aurora PostgreSQL (or RDS Postgres) for Bluemarble/Salesforce mocks; S3 + OpenSearch Serverless (vector) for the Knowledge Agent's RAG corpus |
| Semantic Layer | Thin service layer with named parameterized queries against the mock DB; no dynamic SQL generation exposed to the LLM |
| Governance/Security Control Plane | IAM roles per service (least privilege), Secrets Manager for mock credentials, CloudWatch + X-Ray for infra tracing, **Langfuse** for LLM-specific tracing/evals |
| Audit & Traceability | DynamoDB table (or Postgres table) logging every action: who/what agent requested it, governance decision, outcome, timestamp |
| IaC | AWS CDK (TypeScript or Python) — keeps the whole POC reproducible and reviewable, and doubles as documentation of the architecture for the RFP response |

**Langfuse hosting:** for a POC, self-host Langfuse on a small ECS Fargate task + RDS Postgres, or use Langfuse Cloud free tier to save time — self-hosting is more "AWS-native" for a demo but not essential to prove the pattern.

---

## 7. Build Sequence (3–4 week solo sprint)

### Week 1 — Gateway + Mocks
- Stand up 3 mock services (Bluemarble/Salesforce/Snowflake stand-ins) as separate containers (ECS Fargate or local Docker first, deploy to AWS after)
- Build the MCP Gateway as its own service: wraps each mock as an MCP tool; handles auth (dummy API key check is fine), idempotency keys, basic rate limiting
- Wire Langfuse tracing into every Gateway call from day one

### Week 2 — Orchestration + Agents
- Pick orchestration framework (LangGraph is a reasonable default) or hand-roll a state machine
- Build 2–3 Business Capability Agents:
  - **Knowledge Agent** — RAG over a small fake product-docs corpus (OpenSearch or even a simple in-memory vector store to start)
  - **Transactional Agent** — calls mock Order/Billing tools via the Gateway
  - **Governance Agent** — simple rules check (e.g., "block any order action above €X without explicit human approval")
- Implement the phased model explicitly: Advise (read-only) → Configure (propose, don't execute) → Action (execute via Gateway with governance sign-off)

### Week 3 — Semantic Layer + Guardrails
- Add named, parameterized "views" (not open text-to-SQL) the agent selects from based on intent
- Add basic guardrails: PII redaction on input/output, content moderation pass (Bedrock Guardrails), explicit refusal path for out-of-scope requests
- Add the audit trail: every action, its approver (human or governance-agent), and outcome — queryable after the fact

### Week 4 — Harden and Package
- Add a simple eval harness in Langfuse (or a spreadsheet of test conversations with expected outcomes) covering all three phases
- Write a short mapping doc: POC component → RFP diagram box → real system it will eventually connect to
- Package as CDK stack (or docker-compose for fast local iteration, CDK for the AWS deployment) so it's a one-command deploy
- Confirm every "money or state" action goes through the same governance gate, no exceptions baked in for the demo

---

## 8. Prep Checklist (Domain Knowledge, Do This in Parallel)

- [ ] TM Forum ODA basics — Party, Product, Engagement Management building blocks; TMF622 (Order), TMF637 (Product Inventory), TMF678 (Billing), TMF629 (Customer Management)
- [ ] MCP protocol spec — tool discovery, resources vs. tools vs. prompts, capability advertisement
- [ ] Salesforce Agentforce basics — is it exposed as a dumb API or as an agent with its own callable actions?
- [ ] Snowflake Cortex Analyst / semantic views — governed natural-language-to-query pattern
- [ ] A2A protocol (Google's Agent2Agent) — relevant if multi-vendor agent ecosystems (VZ agents ↔ Salesforce Agentforce agents) come up

---

## 9. Open Questions to Carry Into Team Discussions

- Is Salesforce expected to be integrated as a traditional REST/Bulk API target, or via Agentforce as a peer agent?
- What's VZ's actual data residency posture for using Google/OpenAI/Anthropic-hosted models against EU customer data?
- Is there an existing TM Forum ODA governance body at VZ this proposal needs to align with?
- What does "human approval gate" concretely mean operationally — who is the human, and what's the SLA/timeout behavior if they don't respond?
- What's the rollback/compensation strategy expected for partially-failed multi-system actions (e.g., order committed in Bluemarble but Salesforce case update fails)?
