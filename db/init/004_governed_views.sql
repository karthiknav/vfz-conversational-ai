-- Governed, fixed-shape views — the only way agents read analytics data.
-- No raw SQL is ever exposed to an agent; each view is called through a
-- named, parameterized function in services/gateway-mcp/app/tools/snowflake_tools.py.

CREATE VIEW analytics.vw_customer_usage_spend AS
SELECT
    c.customer_id,
    o.name AS plan_name,
    c.data_used_gb,
    c.data_allowance_gb,
    c.minutes_used,
    c.spend_current_month,
    c.spend_avg_3mo
FROM analytics.customer_360 c
JOIN bluemarble.product_offering o ON o.id = c.current_offering_id;

CREATE VIEW analytics.vw_customer_profile_360 AS
SELECT
    customer_id,
    tenure_months,
    churn_risk_score,
    current_offering_id AS current_product_id,
    last_interaction_date,
    preferred_channel
FROM analytics.customer_360;

CREATE VIEW analytics.vw_order_eligibility AS
SELECT
    customer_id,
    contract_end_date,
    upgrade_eligible,
    outstanding_balance,
    credit_flag
FROM analytics.customer_360;
