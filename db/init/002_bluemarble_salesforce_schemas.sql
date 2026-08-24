-- Bluemarble-mock: TM Forum-shaped product catalogue + order management
CREATE SCHEMA IF NOT EXISTS bluemarble;

CREATE TABLE bluemarble.product_offering (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    monthly_price   NUMERIC(10, 2) NOT NULL,
    data_allowance_gb INTEGER,
    -- Deliberate real-world quirk: price is nested the way real TMF622
    -- productOfferingPrice payloads nest it, so the Gateway's tool adapter
    -- has something realistic to normalize (RFP gap #8 stand-in).
    raw_json        JSONB NOT NULL
);

CREATE SEQUENCE bluemarble.order_id_seq START WITH 3001;

CREATE TABLE bluemarble.product_order (
    id                  TEXT PRIMARY KEY,
    customer_id         TEXT NOT NULL,
    product_offering_id TEXT NOT NULL REFERENCES bluemarble.product_offering(id),
    state               TEXT NOT NULL DEFAULT 'acknowledged'
                        CHECK (state IN ('acknowledged', 'inProgress', 'completed', 'failed')),
    raw_json            JSONB NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Salesforce-mock: Case management for CRM/advisor-desk hand-off
CREATE SCHEMA IF NOT EXISTS salesforce;

CREATE SEQUENCE salesforce.case_id_seq START WITH 5001;

CREATE TABLE salesforce.case (
    id           TEXT PRIMARY KEY,
    customer_id  TEXT NOT NULL,
    subject      TEXT NOT NULL,
    -- Deliberate real-world quirk: Salesforce picklist-style status field
    -- naming, rather than a clean enum, for the same anti-corruption-layer
    -- demonstration as the Bluemarble price nesting above.
    "Case_Status__c" TEXT NOT NULL DEFAULT 'New',
    reason       TEXT,
    raw_json     JSONB NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
