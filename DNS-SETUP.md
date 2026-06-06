# DNS Setup for llm.chrisvouga.dev

## Issue
The `llm.chrisvouga.dev` domain is not resolving because there's no DNS record pointing it to your Cloudflare Worker.

## Solution

### Option 1: Manual Setup (Quick)
1. Go to [Cloudflare Dashboard](https://dash.cloudflare.com)
2. Select **chrisvouga.dev** zone
3. Go to **DNS** tab → **Add record**
4. Configure:

| Field | Value |
|-------|-------|
| Type | CNAME |
| Name | llm |
| Content | `llm-usage-tracker.<your-subdomain>.workers.dev` |
| TTL | Auto |
| Proxy status | Proxied |

### Option 2: Automated (via CI/CD)
The deployment script now attempts to create the DNS record automatically. You need:
1. `CLOUDFLARE_ACCOUNT_ID` in your Doppler secrets
2. Proper API token permissions for DNS editing

Run the deploy script manually to test:
```bash
doppler run -- ./scripts/deploy-worker.sh
```

## Verification
After setting up DNS, verify with:
```bash
dig llm.chrisvouga.dev
# or
curl -I https://llm.chrisvouga.dev
```
