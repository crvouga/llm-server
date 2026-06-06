# LLM Usage Tracker

Cloudflare Worker that transparently proxies OpenAI-compatible API requests to LM Studio while logging raw request/response payloads to Neon PostgreSQL.

## Architecture

- Public API: `https://llm.chrisvouga.dev`
- Upstream (tunneled LM Studio): `https://lm-studio.chrisvouga.dev`
- Database: Neon PostgreSQL, schema `llm_server`

## Setup

```bash
cd llm-usage-tracker
npm install
cp .dev.vars.example .dev.vars
# Fill DATABASE_URL in .dev.vars, or use Doppler:
doppler run --project personal --config dev -- npm run db:migrate
```

Set the production secret:

```bash
doppler secrets get DATABASE_URL --project personal --config dev --plain | \
  npx wrangler secret put DATABASE_URL
```

## Development

```bash
npm run dev
```

## Deploy

```bash
npm run deploy
```

## Database

Schema lives in `sql/schema.sql`. Apply with:

```bash
doppler run --project personal --config dev -- npm run db:migrate
```

If upgrading from the old normalized schema:

```sql
DROP TABLE IF EXISTS llm_server.usage_logs CASCADE;
DROP MATERIALIZED VIEW IF EXISTS llm_server.daily_usage;
```

Then re-run `npm run db:migrate`.

## Usage queries

```sql
-- Total tokens
SELECT SUM((res->'usage'->>'total_tokens')::int)
FROM llm_server.usage_logs
WHERE res ? 'usage';

-- Daily breakdown by model
SELECT
  DATE(created_at) AS date,
  req->>'model' AS model,
  SUM((res->'usage'->>'total_tokens')::int) AS total_tokens,
  COUNT(*) AS requests
FROM llm_server.usage_logs
WHERE res ? 'usage'
GROUP BY 1, 2;
```

Streaming responses are stored as `{ "stream": true, "chunks": [...] }`. Usage may appear on the final chunk:

```sql
SELECT
  created_at,
  req->>'model' AS model,
  chunk.value->'usage' AS usage
FROM llm_server.usage_logs,
LATERAL jsonb_array_elements(res->'chunks') AS chunk(value)
WHERE res->>'stream' = 'true'
  AND chunk.value ? 'usage';
```
