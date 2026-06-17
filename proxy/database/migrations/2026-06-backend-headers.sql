-- Upstream auth headers for the configured OpenAI-compatible backend.
ALTER TABLE llm_proxy.config ADD COLUMN IF NOT EXISTS backend_headers JSONB NOT NULL DEFAULT '{}';
