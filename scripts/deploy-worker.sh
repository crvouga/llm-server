#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

echo "Installing dependencies..."
cd llm-usage-tracker
npm ci

# Check if required environment variables are set
if [ -z "${DATABASE_URL:-}" ]; then
  echo "DATABASE_URL is required (set via Doppler or env)."
  exit 1
fi

if [ -z "${CLOUDFLARE_API_TOKEN:-}" ]; then
  echo "CLOUDFLARE_API_TOKEN is required (set via Doppler or env)."
  exit 1
fi

if [ -z "${CLOUDFLARE_ACCOUNT_ID:-}" ]; then
  echo "CLOUDFLARE_ACCOUNT_ID is required (set via Doppler or env)."
  exit 1
fi

# Upload secrets to Cloudflare
printf '%s' "$DATABASE_URL" | npx wrangler secret put DATABASE_URL

# Run database migrations and deploy
npm run db:migrate
npm run deploy

# Create DNS record for the worker (idempotent - checks if record exists first)
DNS_RECORD_EXISTS=$(curl -s -X GET "https://api.cloudflare.com/client/v4/accounts/${CLOUDFLARE_ACCOUNT_ID}/dns_records?name=llm.chrisvouga.dev" \
  -H "Authorization: Bearer ${CLOUDFLARE_API_TOKEN}" \
  -H "Content-Type: application/json" | grep -c '"success":true')

if [ "$DNS_RECORD_EXISTS" -eq 0 ]; then
  echo "Creating DNS record for llm.chrisvouga.dev..."
  
  # Get the deployed worker hostname
  WORKER_HOSTNAME=$(npx wrangler whoami 2>/dev/null | grep 'WorkerHostname' | sed 's/.*: //' || echo "")
  
  if [ -z "$WORKER_HOSTNAME" ]; then
    echo "Warning: Could not determine worker hostname automatically"
    echo "Please create a CNAME record manually pointing llm.chrisvouga.dev to your Worker hostname"
  else
    # Create the DNS record
    curl -s -X POST "https://api.cloudflare.com/client/v4/accounts/${CLOUDFLARE_ACCOUNT_ID}/dns_records" \
      -H "Authorization: Bearer ${CLOUDFLARE_API_TOKEN}" \
      -H "Content-Type: application/json" \
      --data '{
        "type": "CNAME",
        "name": "llm.chrisvouga.dev",
        "content": "'"${WORKER_HOSTNAME}"'",
        "ttl": 1,
        "priority": null,
        "proxied": true
      }' | grep -q '"success":true' && \
      echo "DNS record created successfully" || \
      echo "Warning: DNS record creation failed (may require manual setup)"
  fi
fi
