CREATE SCHEMA IF NOT EXISTS llm_server;

CREATE TABLE IF NOT EXISTS llm_server.usage_logs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  endpoint TEXT NOT NULL,
  api_key_hash TEXT,
  req JSONB NOT NULL,
  res JSONB NOT NULL
);

CREATE INDEX IF NOT EXISTS usage_logs_created_at_idx
  ON llm_server.usage_logs (created_at DESC);

CREATE INDEX IF NOT EXISTS usage_logs_req_model_idx
  ON llm_server.usage_logs ((req->>'model'));
