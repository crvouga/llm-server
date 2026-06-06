# LiteLLM Proxy (Fly.io)

Self-hosted [LiteLLM](https://docs.litellm.ai/) proxy deployed to Fly.io at `https://litellm.chrisvouga.dev`.

## Architecture

- **Public API**: `https://litellm.chrisvouga.dev`
- **Compute**: Fly.io app `litellm-chrisvouga`
- **DNS**: Cloudflare CNAME `litellm` → `litellm-chrisvouga.fly.dev`
- **Secrets**: Doppler (`personal` / `dev`)

## Required Doppler secrets

| Secret | Purpose |
|--------|---------|
| `FLY_API_TOKEN` | Fly.io deploy auth |
| `LITELLM_MASTER_KEY` | Bearer token for proxy clients (`Authorization: Bearer …`) |
| `OPENAI_API_KEY` | OpenAI provider routing |
| `CLOUDFLARE_API_TOKEN` | DNS record management during deploy |
| `CLOUDFLARE_ACCOUNT_ID` | Cloudflare account for DNS API |

Optional:

| Secret | Purpose |
|--------|---------|
| `LM_STUDIO_API_KEY` | Auth for tunneled LM Studio upstream (defaults to `local` if unset) |
| `CLOUDFLARE_ZONE_ID` | Skip zone lookup during deploy |

Generate a master key:

```bash
openssl rand -hex 32 | xargs -I{} doppler secrets set LITELLM_MASTER_KEY "sk-{}" --project personal --config dev
```

## Deploy

From repo root:

```bash
doppler run --project personal --config dev -- make deploy-litellm
```

Or directly:

```bash
doppler run --project personal --config dev -- ./scripts/deploy-litellm.sh
```

## Usage

```bash
curl https://litellm.chrisvouga.dev/v1/chat/completions \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-4o-mini",
    "messages": [{"role": "user", "content": "Hello"}]
  }'
```

Route to local LM Studio models via the `local-lm-studio` alias:

```bash
curl https://litellm.chrisvouga.dev/v1/chat/completions \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "local-lm-studio",
    "messages": [{"role": "user", "content": "Hello"}]
  }'
```

## Operations

```bash
make litellm-status   # Fly app status
fly logs -a litellm-chrisvouga
fly ssh console -a litellm-chrisvouga
```

## Adding providers

Edit `litellm_config.yaml` with new `model_list` entries using `os.environ/YOUR_KEY`, add the secret to Doppler, and redeploy.
