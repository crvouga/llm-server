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
