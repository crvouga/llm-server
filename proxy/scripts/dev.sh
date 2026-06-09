#!/usr/bin/env bash
# Local dev: inject DATABASE_URL from vault (personal/dev) into .dev.vars for wrangler.
set -euo pipefail

cd "$(dirname "$0")/.."

export VAULT_ADDR="${VAULT_ADDR:-https://vault.chrisvouga.dev}"

mkdir -p public
if [ ! -f public/ui-client.js ]; then
  bun run build:client
fi

exec vault run --project personal --config dev -- sh -c '
  set -euo pipefail
  if [ -z "${DATABASE_URL:-}" ]; then
    echo "Error: DATABASE_URL not set by vault (secret/personal/dev)" >&2
    echo "Run: vault login && vault setup --project personal --config dev" >&2
    exit 1
  fi
  bun -e "await Bun.write(\".dev.vars\", \"DATABASE_URL=\" + JSON.stringify(process.env.DATABASE_URL) + \"\\n\")"
  exec wrangler dev "$@"
' sh "$@"
