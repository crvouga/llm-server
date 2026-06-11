# LLM Proxy

Transparent HTTP proxy that forwards all requests to a configurable backend while logging raw request/response data to PostgreSQL. Runs as a Bun server in Docker, deployed on Fly.io at `llm-proxy.chrisvouga.dev`.

## Architecture

```
Client → llm-proxy.chrisvouga.dev → Fly.io (Docker/Bun) → backend (from config table)
                                              ↓
                                         PostgreSQL (config + raw JSONB logs)
```

The upstream backend URL is stored in `llm_proxy.config` — not in environment variables or app code. Until that row exists, proxied requests return **503 Proxy not configured**.

## Prerequisites

Vault secrets at `secret/personal/dev` (used by CI on push to `main`):

| Secret | Purpose |
|--------|---------|
| `DATABASE_URL` | PostgreSQL connection string (Neon HTTP API format) |
| `FLY_API_TOKEN` | Fly.io deploy token |
| `CLOUDFLARE_API_TOKEN` | DNS updates + Worker cleanup |
| `CLOUDFLARE_ACCOUNT_ID` | Cloudflare account for API calls |

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

3. **Install dependencies**:
   ```bash
   bun install
   ```

4. **Run locally**:
   ```bash
   vault login
   vault setup --project personal --config dev
   bun run dev
   ```

   Server listens on `http://localhost:8080` by default (`PORT` env overrides).

## Deployment

The app is packaged as a **provider-neutral OCI container**. CI builds and pushes the image; Fly.io (or any runtime) only pulls and runs that image.

Push to `main` runs the full pipeline automatically:

1. Type-check and test
2. Run database migrations
3. Build and push container image to `ghcr.io/crvouga/llm-proxy`
4. Verify the image exists in the registry
5. Deploy the **pre-built image** to Fly (`flyctl deploy --image … --remote-only`; no Fly build step)
6. Remove legacy Cloudflare Worker + custom domain
7. Point `llm-proxy.chrisvouga.dev` DNS (Cloudflare CNAME → `chrisvouga-llm-proxy.fly.dev`)
8. Ensure Fly TLS certificate and wait for HTTPS
9. Run API smoke tests

The same image can be run elsewhere without changes:

```bash
docker run -e DATABASE_URL='...' -p 8080:8080 ghcr.io/crvouga/llm-proxy:latest
```

Implementation: [`scripts/deploy.sh`](scripts/deploy.sh) (accepts `CONTAINER_IMAGE`), invoked from [`.github/workflows/deployment-pipeline.yml`](../.github/workflows/deployment-pipeline.yml).

Images:

```
ghcr.io/crvouga/llm-proxy:<git-sha>
ghcr.io/crvouga/llm-proxy:latest
```

Local deploy (same script as CI, requires vault `prd` config with all secrets above):

```bash
CONTAINER_IMAGE=ghcr.io/crvouga/llm-proxy:latest bash scripts/deploy.sh
```

Or from repo root: `make proxy-deploy`

## Proxy config

| Column | Type | Description |
|--------|------|-------------|
| `id` | SMALLINT | Always `1` (singleton row) |
| `backend_url` | TEXT | Upstream origin, e.g. `https://lm-studio.example.com` |
| `updated_at` | TIMESTAMPTZ | Last time the backend URL was changed |

The proxy reads `backend_url` from this table on each request (cached for 30 seconds per process). If the row is missing or the URL is invalid, proxied requests return:

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
# Run locally (loads DATABASE_URL from vault secret/personal/dev)
vault login
vault setup --project personal --config dev
bun run dev

# Run without vault (DATABASE_URL must be set)
DATABASE_URL='...' bun run start

# Type-check without deploying
bun run check
```

### Docker

```bash
docker build -t llm-proxy proxy/
docker run -e DATABASE_URL='...' -p 8080:8080 llm-proxy
```

## Testing

Usage tracking tests hit the real dev database (`vault personal/dev` `DATABASE_URL`) and a local mock OpenAI-compatible backend. Test rows use sentinel model names (`__test__<runId>-*`) and are deleted after each suite.

```bash
# From repo root
make proxy-test

# Or from proxy/
bun run test:vault
```

Pure summarization tests run without a database. Query and e2e suites seed rows in isolated date windows (or assert on sentinel models only) so real usage data does not affect assertions.

## Dashboard

Open `/ui` on the proxy (e.g. `https://llm-proxy.chrisvouga.dev/ui`). Legacy `/dashboard` and `/usage-dashboard` paths redirect here.

- **All-time default** — loads full usage history on first visit; filter by date range as needed
- **Per-model analytics** — requests, prompt/completion/total tokens, avg per request, share of total
- **Charts** — tokens per model, stacked prompt vs completion, share doughnut, daily trend, estimated cost
- **Sortable table** — click column headers to reorder per-model results
- **Cost estimation** — parameterized as USD per 1M tokens (defaults: $1 input, $2 output); override globally or per model
- **Est. cloud cost** — `(prompt_tokens × input $/1M + completion_tokens × output $/1M) ÷ 1,000,000`, assuming local inference is free

Only responses with a `usage` field are included in dashboard totals. For streaming chat completions (`text/event-stream`), the proxy tees the stream, parses SSE chunks after the response completes, and logs usage from the final chunk. The proxy also injects `stream_options.include_usage: true` on outbound streaming requests when the client omits it, so compatible backends emit token counts in the stream.

Implementation lives in [`src/dashboard/`](src/dashboard/).
