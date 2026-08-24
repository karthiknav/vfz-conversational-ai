# Demo Script

Run `docker compose up --build` first (see root `README.md`), then open http://localhost:8080. All three branches use the same seeded customer, Anna de Groot (`CUST-1001`), currently on Ziggo Mobile S — 20GB at €34.99/mo, 18.4GB used.

## Branch 1 — Auto-approve (the default happy path)

1. Type: **"What's my current data usage this month?"**
   Expect an Advise-tier answer citing 18.4GB/20GB and €34.99 — no proposal card, phase badge stays `advise`.
2. Type: **"I'm close to my limit, can I upgrade to 50GB?"**
   Expect a proposal card: Ziggo Mobile M — 50GB, €44.99/mo, +€10.00. Phase badge switches to `configure`.
3. Leave "Simulate CRM sync failure" unchecked, click **Approve**.
   Expect a success reply, phase badge switches to `action`. Order `ORD-3001` (or next in sequence) now exists — confirm with:
   ```
   curl http://localhost:8081/productOrderingManagement/v4/productOrder/ORD-3001
   ```

## Branch 2 — Escalation (over the auto-approve threshold)

Fresh conversation (reload the page for a new thread_id), repeat step 1, then:
2. Type: **"Actually, can I go unlimited instead?"**
   Expect a proposal card: Ziggo Mobile L — Unlimited, €54.99/mo, +€20.00.
3. Click **Approve** (checkbox unchecked).
   Expect a reply explaining the upgrade needs review — **no order is created**. Confirm via the audit trail:
   ```sql
   SELECT governance_decision, outcome_status FROM audit.audit_trail
   WHERE action_type = 'submit_order' ORDER BY occurred_at DESC LIMIT 1;
   -- governance_decision = 'escalated'
   ```

## Branch 3 — Induced partial failure (compensation demo)

Fresh conversation, repeat steps 1–2 from Branch 1 (50GB upgrade), then:
3. Check **"Simulate CRM sync failure"**, click **Approve**.
   Expect a reply confirming the order went through *and* that a follow-up case was opened. Confirm both effects landed:
   ```
   curl http://localhost:8081/productOrderingManagement/v4/productOrder/<order-id>   # order exists
   curl http://localhost:8082/Case/<case-id>                                          # escalation case exists
   ```
   ```sql
   SELECT outcome_status, correlation_order_id, correlation_case_id FROM audit.audit_trail
   WHERE outcome_status = 'partial_failure' ORDER BY occurred_at DESC LIMIT 1;
   ```

## Talking points while demoing

- **DevTools Network tab**: the UI only ever calls the orchestrator (`localhost:8000`) — never the Gateway or the mocks directly. That's "AI requests, platform decides execution" made visible.
- **Langfuse dashboard**: pull up the trace for whichever turn you just ran — nested spans show router → agent node → MCP tool call → Bedrock call under one trace_id.
- **`audit.audit_trail` table**: every branch above leaves a row (or two) — this is the audit trail the RFP asks for, queryable after the fact, not just log lines.
- **`docs/mapping.md`**: the answer to "what happens when we point this at the real Bluemarble" is a table, not a promise.
