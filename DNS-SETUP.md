# DNS Setup for litellm.chrisvouga.dev

## Overview

LiteLLM runs on Fly.io (`litellm-chrisvouga.fly.dev`). Cloudflare DNS routes `litellm.chrisvouga.dev` to the Fly app.

## Automated setup (recommended)

The deploy script creates/updates the DNS record and requests a Fly.io certificate:

```bash
doppler run --project personal --config dev -- make deploy-litellm
```

Required Doppler secrets:

- `FLY_API_TOKEN`
- `LITELLM_MASTER_KEY`
- `OPENAI_API_KEY`
- `CLOUDFLARE_API_TOKEN`
- `CLOUDFLARE_ACCOUNT_ID`

## Manual setup

1. Go to [Cloudflare Dashboard](https://dash.cloudflare.com)
2. Select **chrisvouga.dev** zone
3. Go to **DNS** → **Add record**
4. Configure:

| Field | Value |
|-------|-------|
| Type | CNAME |
| Name | litellm |
| Content | `litellm-chrisvouga.fly.dev` |
| TTL | Auto |
| Proxy status | DNS only (grey cloud) |

> Must be **DNS only**. If proxied (orange cloud), Cloudflare can't complete the SSL handshake to the Fly origin (Fly never issues a cert for a proxied hostname) and you get **Error 525**. DNS-only also avoids Cloudflare's request timeout truncating long LLM streaming responses.

5. Request a Fly.io certificate:

```bash
fly certs add litellm.chrisvouga.dev -a litellm-chrisvouga
```

## Verification

```bash
dig litellm.chrisvouga.dev
curl -fsS https://litellm.chrisvouga.dev/health/liveliness
```

## Legacy domain

The old Worker endpoint `llm.chrisvouga.dev` is retired. Remove its DNS record and Workers custom domain from Cloudflare if still present.
