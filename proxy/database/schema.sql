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
  response_error_message TEXT
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_http_log_created_at ON llm_proxy.http_log(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_http_log_request_method ON llm_proxy.http_log(request_method);
CREATE INDEX IF NOT EXISTS idx_http_log_request_path ON llm_proxy.http_log(request_path);

-- Singleton proxy configuration (backend URL, etc.)
CREATE TABLE IF NOT EXISTS llm_proxy.proxy_state (
  id SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
  backend_url TEXT NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
