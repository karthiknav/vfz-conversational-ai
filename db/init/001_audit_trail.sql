CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE SCHEMA IF NOT EXISTS audit;

CREATE TABLE audit.audit_trail (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    trace_id            TEXT,
    occurred_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    thread_id           TEXT,
    phase               TEXT NOT NULL CHECK (phase IN ('advise', 'configure', 'action')),
    actor_agent         TEXT NOT NULL,
    requested_by        TEXT NOT NULL,
    action_type         TEXT NOT NULL,
    target_system       TEXT NOT NULL CHECK (target_system IN ('bluemarble', 'salesforce', 'snowflake', 'none')),
    idempotency_key     TEXT,
    request_payload     JSONB,
    governance_decision TEXT NOT NULL DEFAULT 'not_required'
                        CHECK (governance_decision IN ('not_required', 'approved', 'blocked', 'escalated')),
    governance_reason   TEXT,
    outcome_status      TEXT NOT NULL CHECK (outcome_status IN ('success', 'failure', 'partial_failure')),
    outcome_detail      JSONB,
    correlation_order_id TEXT,
    correlation_case_id  TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Only successful writes are deduplicated on idempotency_key; a failed
-- attempt leaves the key free to retry (matches real idempotency semantics —
-- dedupe confirmed side effects, not attempts).
CREATE UNIQUE INDEX audit_trail_idempotency_key_uq
    ON audit.audit_trail (idempotency_key)
    WHERE idempotency_key IS NOT NULL AND outcome_status = 'success';

CREATE INDEX audit_trail_thread_id_idx ON audit.audit_trail (thread_id);
CREATE INDEX audit_trail_occurred_at_idx ON audit.audit_trail (occurred_at);
