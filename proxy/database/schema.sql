-- LLM Proxy HTTP Logging Schema
-- Stores raw request/response data as JSONB for flexible analysis

-- Neon: UUID extension is pre-installed, but this ensures compatibility
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Create the schema if it doesn't exist
CREATE SCHEMA IF NOT EXISTS llm_proxy;

CREATE TABLE IF NOT EXISTS llm_proxy.http_log (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  request_method VARCHAR(16) NOT NULL,
  request_path TEXT NOT NULL,
  request_query_params JSONB,
  request_headers JSONB,
  request_body JSONB,
  response_status_code SMALLINT NOT NULL,
  response_headers JSONB,
  response_body JSONB,
  response_error_message TEXT,
  duration_ms INTEGER,
  ttft_ms INTEGER
);

ALTER TABLE llm_proxy.http_log ADD COLUMN IF NOT EXISTS duration_ms INTEGER;
ALTER TABLE llm_proxy.http_log ADD COLUMN IF NOT EXISTS ttft_ms INTEGER;

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_http_log_created_at ON llm_proxy.http_log(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_http_log_request_method ON llm_proxy.http_log(request_method);
CREATE INDEX IF NOT EXISTS idx_http_log_request_path ON llm_proxy.http_log(request_path);

-- Singleton proxy configuration (backend URL, etc.)
DO $$
BEGIN
  IF EXISTS (
    SELECT 1
    FROM information_schema.tables
    WHERE table_schema = 'llm_proxy'
      AND table_name = 'proxy_state'
  ) AND NOT EXISTS (
    SELECT 1
    FROM information_schema.tables
    WHERE table_schema = 'llm_proxy'
      AND table_name = 'config'
  ) THEN
    ALTER TABLE llm_proxy.proxy_state RENAME TO config;
  END IF;
END $$;

CREATE TABLE IF NOT EXISTS llm_proxy.config (
  id SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
  backend_url TEXT NOT NULL,
  investment_usd NUMERIC,
  projected_daily_spend_usd NUMERIC,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE llm_proxy.config ADD COLUMN IF NOT EXISTS investment_usd NUMERIC;
ALTER TABLE llm_proxy.config ADD COLUMN IF NOT EXISTS projected_daily_spend_usd NUMERIC;

-- Singleton dashboard cost rate configuration
CREATE TABLE IF NOT EXISTS llm_proxy.cost_rates (
  id SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
  input_per_million NUMERIC NOT NULL DEFAULT 1,
  output_per_million NUMERIC NOT NULL DEFAULT 2,
  model_overrides JSONB NOT NULL DEFAULT '{}',
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
