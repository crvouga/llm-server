# LLM Proxy

Transparent Cloudflare Worker that forwards all requests to a configurable backend while logging raw request/response data to PostgreSQL.

## Architecture

```
Client → llm-proxy.chrisvouga.dev → Cloudflare Worker → backend (from config table)
                                              ↓
                                         PostgreSQL (config + raw JSONB logs)
```

The upstream backend URL is stored in `llm_proxy.config` — not in environment variables or worker code. Until that row exists, proxied requests return **503 Proxy not configured**.

## Prerequisites

- Cloudflare account with Workers access
- Secret store at `https://secret-store.chrisvouga.dev` with secrets at `secret/personal/<config>`:
  - `DATABASE_URL` - PostgreSQL connection string in HTTP API format (Supabase/PlanetScale)
  - `CLOUDFLARE_API_TOKEN` - API token for deployment
  - `CLOUDFLARE_ACCOUNT_ID` - Your Cloudflare account ID

## Setup

1. **Create the database tables**:
   ```bash
   # Ensure DATABASE_URL is set in your environment
   ./proxy/database/setup.sh
   ```

2. **Configure the backend URL** (required before the proxy will forward traffic):
   ```sql
   INSERT INTO llm_proxy.config (backend_url)
   VALUES ('https://lm-studio.chrisvouga.dev');
   ```

   To change the backend later:
   ```sql
   UPDATE llm_proxy.config
   SET backend_url = 'https://new-backend.example.com', updated_at = NOW()
   WHERE id = 1;
   ```

   Or manually run the schema from [`database/schema.sql`](database/schema.sql), then insert the row above.

   Legacy manual schema (http_log only):
   ```sql
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

   CREATE INDEX IF NOT EXISTS idx_http_log_created_at ON llm_proxy.http_log(created_at DESC);
   CREATE INDEX IF NOT EXISTS idx_http_log_request_method ON llm_proxy.http_log(request_method);
   CREATE INDEX IF NOT EXISTS idx_http_log_request_path ON llm_proxy.http_log(request_path);

   CREATE TABLE IF NOT EXISTS llm_proxy.config (
     id SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
     backend_url TEXT NOT NULL,
     updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
   );
   ```

3. **Install dependencies**:
   ```bash
   bun install
   ```

4. **Deploy to Cloudflare Workers**:
   ```bash
   # Ensure the secret store is configured and secrets are loaded
   vault setup --project personal --config prd

   # Deploy the worker
   vault run --config prd -- wrangler deploy
   ```

## Proxy config

| Column | Type | Description |
|--------|------|-------------|
| `id` | SMALLINT | Always `1` (singleton row) |
| `backend_url` | TEXT | Upstream origin, e.g. `https://lm-studio.example.com` |
| `updated_at` | TIMESTAMPTZ | Last time the backend URL was changed |

The worker reads `backend_url` from this table on each request (cached for 30 seconds per isolate). If the row is missing or the URL is invalid, proxied requests return:

```json
{ "error": "Proxy not configured", "details": "Set llm_proxy.config.backend_url" }
```

## Logging Format

The proxy stores complete raw data in JSONB format:

| Column | Type | Description |
|--------|------|-------------|
| `id` | UUID | Unique ID for each log entry |
| `created_at` | TIMESTAMPTZ | When the request was received |
| `request_method` | VARCHAR(16) | HTTP method (GET, POST, etc.) |
| `request_path` | TEXT | Request path (e.g., `/v1/chat/completions`) |
| `request_query_params` | JSONB | Query string parameters as object |
| `request_headers` | JSONB | Request headers as object |
| `request_body` | JSONB | Request body (parsed as JSON or null) |
| `response_status_code` | SMALLINT | Response HTTP status |
| `response_headers` | JSONB | Response headers as object |
| `response_body` | JSONB | Response body (parsed as JSON or null) |
| `response_error_message` | TEXT | Error message if request failed |

## Usage Examples

### View recent API usage
```sql
SELECT 
  id,
  created_at,
  request_method,
  request_path,
  response_status_code
FROM llm_proxy.http_log
ORDER BY created_at DESC
LIMIT 10;
```

### Find all requests to a specific endpoint
```sql
SELECT id, created_at, request_query_params, request_body, response_body
FROM llm_proxy.http_log
WHERE request_path = '/v1/chat/completions'
  AND created_at > NOW() - INTERVAL '24 hours'
ORDER BY created_at DESC;
```

### Analyze error responses
```sql
SELECT 
  request_method,
  request_path,
  response_status_code,
  COUNT(*) as count,
  JSONB_AGG(id) as request_ids
FROM llm_proxy.http_log
WHERE response_status_code >= 400
GROUP BY request_method, request_path, response_status_code
ORDER BY count DESC;
```

### Extract token usage from OpenAI-style responses
```sql
SELECT 
  created_at,
  request_body->>'model' as model,
  (response_body->'usage'->>'prompt_tokens')::int as prompt_tokens,
  (response_body->'usage'->>'completion_tokens')::int as completion_tokens,
  response_body->'choices' as choices
FROM llm_proxy.http_log
WHERE request_path = '/v1/chat/completions'
  AND response_body ? 'usage'
ORDER BY created_at DESC
LIMIT 20;
```

### Find requests with high latency (by count)
```sql
SELECT 
  id,
  response_status_code,
  length(CAST(response_body AS TEXT)) as response_size_bytes
FROM llm_proxy.http_log
WHERE request_path = '/v1/chat/completions'
ORDER BY response_size_bytes DESC
LIMIT 10;
```

## Development

```bash
# Run locally with wrangler dev
bun run dev

# Type-check without deploying
bun run check
```

## Usage Dashboard

Open `/usage-dashboard` on the Worker (e.g. `https://llm-proxy.chrisvouga.dev/usage-dashboard`).

- **Pure HTML forms** — no client-side JavaScript
- **Date range** — filter usage for any period (defaults to today)
- **Per-model cloud rates** — defaults to $1 / 1M input tokens and $2 / 1M output tokens; override globally or per model
- **Money saved** — `(prompt_tokens × input_rate) + (completion_tokens × output_rate)` assuming local inference is free

Implementation lives in [`src/usage-dashboard.tsx`](src/usage-dashboard.tsx).
