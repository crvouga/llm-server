-- Request timing for tokens-per-second dashboard metrics

ALTER TABLE llm_proxy.http_log ADD COLUMN IF NOT EXISTS duration_ms INTEGER;
ALTER TABLE llm_proxy.http_log ADD COLUMN IF NOT EXISTS ttft_ms INTEGER;
