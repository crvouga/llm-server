# LLM Proxy

Transparent HTTP proxy that forwards all requests to a configurable backend while logging raw request/response data to PostgreSQL. Runs as a Bun server in Docker at `llm-proxy.chrisvouga.dev`.

## Architecture

```
Client → llm-proxy.chrisvouga.dev → Docker/Bun on infra origin → backend (from config table)
                                              ↓
                                         PostgreSQL (config + raw JSONB logs)
```

The upstream backend URL and optional auth headers are stored in `llm_proxy.config` — not in environment variables or app code. Until that row exists, proxied requests return **503 Proxy not configured**.

## Prerequisites

Vault secrets at `secret/personal/dev` (used by CI on push to `main`):

| Secret | Purpose |
|--------|---------|
| `DATABASE_URL` | PostgreSQL connection string (Neon HTTP API format) |

Production runtime env is synced from Vault via infra deploy-pipeline.

## Setup

1. **Create the database tables**:
   ```bash
   # Ensure DATABASE_URL is set in your environment
   ./proxy/database/setup.sh
   ```

2. **Configure the backend** (required before the proxy will forward traffic):
   ```sql
   INSERT INTO llm_proxy.config (backend_url, backend_headers)
   VALUES (
     'https://your-llm-api.example',
     '{"Authorization":"Bearer sk-..."}'::jsonb
   );
   ```

   Or use the **Backend** card in the UI at `/ui` to set the URL and upstream headers.

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

Push to `main` runs **Publish image** (migrations + `ghcr.io/crvouga/chrisvouga-llm-proxy`) and dispatches infra **Deploy Pipeline**.

```bash
docker run -e DATABASE_URL='...' -p 8080:8080 ghcr.io/crvouga/chrisvouga-llm-proxy:latest
```

## Proxy config

| Column | Type | Description |
|--------|------|-------------|
| `id` | SMALLINT | Always `1` (singleton row) |
| `backend_url` | TEXT | Upstream origin, e.g. `https://api.openai.com` or `https://lm-studio.example.com` |
| `backend_headers` | JSONB | Upstream request headers (API keys, bearer tokens, etc.) |
| `updated_at` | TIMESTAMPTZ | Last time the backend config was changed |

## Development

```bash
vault login
vault setup --project personal --config dev
bun run dev
bun run check
```

### Docker

```bash
docker build -t llm-proxy proxy/
docker run -e DATABASE_URL='...' -p 8080:8080 llm-proxy
```

## Testing

```bash
make proxy-test
# Or from proxy/
bun run test:vault
```

## Dashboard

Open `/ui` on the proxy (e.g. `https://llm-proxy.chrisvouga.dev/ui`).

Implementation lives in [`src/dashboard/`](src/dashboard/).
