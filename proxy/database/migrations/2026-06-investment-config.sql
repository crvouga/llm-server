-- Dashboard investment tracking (singleton config row)

ALTER TABLE llm_proxy.config ADD COLUMN IF NOT EXISTS investment_usd NUMERIC;
ALTER TABLE llm_proxy.config ADD COLUMN IF NOT EXISTS projected_daily_spend_usd NUMERIC;
