#!/usr/bin/env bash
# Local dev: inject DATABASE_URL from vault (personal/dev) and run the Bun server.
set -euo pipefail

cd "$(dirname "$0")/.."

export VAULT_ADDR="${VAULT_ADDR:-https://vault.chrisvouga.dev}"

mkdir -p public

exec vault run --project personal --config dev -- sh -c '
  set -euo pipefail
  if [ -z "${DATABASE_URL:-}" ]; then
    echo "Error: DATABASE_URL not set by vault (secret/personal/dev)" >&2
    echo "Run: vault login && vault setup --project personal --config dev" >&2
    exit 1
  fi
  export PORT="${PORT:-8080}"
  exec bun run src/server.ts "$@"
' sh "$@"
