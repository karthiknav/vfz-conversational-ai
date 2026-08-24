-- Snowflake-mock: analytics / Customer 360 layer
CREATE SCHEMA IF NOT EXISTS analytics;

CREATE TABLE analytics.customer_360 (
    customer_id           TEXT PRIMARY KEY,
    name                  TEXT NOT NULL,
    current_offering_id   TEXT NOT NULL REFERENCES bluemarble.product_offering(id),
    data_allowance_gb     INTEGER NOT NULL,
    data_used_gb          NUMERIC(5, 1) NOT NULL,
    minutes_used          INTEGER NOT NULL,
    spend_current_month   NUMERIC(10, 2) NOT NULL,
    spend_avg_3mo         NUMERIC(10, 2) NOT NULL,
    tenure_months         INTEGER NOT NULL,
    churn_risk_score      NUMERIC(3, 2) NOT NULL,
    contract_end_date     DATE NOT NULL,
    outstanding_balance   NUMERIC(10, 2) NOT NULL DEFAULT 0,
    credit_flag           TEXT NOT NULL DEFAULT 'green' CHECK (credit_flag IN ('green', 'amber', 'red')),
    upgrade_eligible      BOOLEAN NOT NULL DEFAULT TRUE,
    last_interaction_date DATE,
    preferred_channel     TEXT
);

-- Seed catalogue offers (Bluemarble-mock)
INSERT INTO bluemarble.product_offering (id, name, monthly_price, data_allowance_gb, raw_json) VALUES
('OFFER-20GB', 'Ziggo Mobile S — 20GB', 34.99, 20, '{
    "id": "OFFER-20GB",
    "name": "Ziggo Mobile S — 20GB",
    "productOfferingPrice": [{"price": {"taxIncludedAmount": {"value": 34.99, "unit": "EUR"}}, "recurringChargePeriod": "month"}]
}'::jsonb),
('OFFER-50GB', 'Ziggo Mobile M — 50GB', 44.99, 50, '{
    "id": "OFFER-50GB",
    "name": "Ziggo Mobile M — 50GB",
    "productOfferingPrice": [{"price": {"taxIncludedAmount": {"value": 44.99, "unit": "EUR"}}, "recurringChargePeriod": "month"}]
}'::jsonb),
('OFFER-UNLIMITED', 'Ziggo Mobile L — Unlimited', 54.99, NULL, '{
    "id": "OFFER-UNLIMITED",
    "name": "Ziggo Mobile L — Unlimited",
    "productOfferingPrice": [{"price": {"taxIncludedAmount": {"value": 54.99, "unit": "EUR"}}, "recurringChargePeriod": "month"}]
}'::jsonb);

-- Seed customer (Snowflake-mock / analytics)
INSERT INTO analytics.customer_360 (
    customer_id, name, current_offering_id, data_allowance_gb, data_used_gb, minutes_used,
    spend_current_month, spend_avg_3mo, tenure_months, churn_risk_score, contract_end_date,
    outstanding_balance, credit_flag, upgrade_eligible, last_interaction_date, preferred_channel
) VALUES (
    'CUST-1001', 'Anna de Groot', 'OFFER-20GB', 20, 18.4, 210,
    34.99, 32.50, 27, 0.12, '2027-03-01',
    0.00, 'green', TRUE, '2026-07-15', 'app'
);
