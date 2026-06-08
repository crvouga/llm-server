-- Persist dashboard cost rate configuration (singleton row)

CREATE TABLE IF NOT EXISTS llm_proxy.cost_rates (
  id SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
  input_per_million NUMERIC NOT NULL DEFAULT 1,
  output_per_million NUMERIC NOT NULL DEFAULT 2,
  model_overrides JSONB NOT NULL DEFAULT '{}',
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
