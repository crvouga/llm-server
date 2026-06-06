#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

APP_NAME="litellm-chrisvouga"
HOSTNAME="litellm.chrisvouga.dev"
FLY_HOSTNAME="${APP_NAME}.fly.dev"
ZONE_NAME="chrisvouga.dev"
DNS_RECORD_NAME="litellm"

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1"
    exit 1
  fi
}

cf_api() {
  local method="$1"
  local path="$2"
  local data="${3:-}"

  if [ -n "$data" ]; then
    curl -fsS -X "$method" "https://api.cloudflare.com/client/v4${path}" \
      -H "Authorization: Bearer ${CLOUDFLARE_API_TOKEN}" \
      -H "Content-Type: application/json" \
      --data "$data"
  else
    curl -fsS -X "$method" "https://api.cloudflare.com/client/v4${path}" \
      -H "Authorization: Bearer ${CLOUDFLARE_API_TOKEN}" \
      -H "Content-Type: application/json"
  fi
}

resolve_zone_id() {
  if [ -n "${CLOUDFLARE_ZONE_ID:-}" ]; then
    echo "${CLOUDFLARE_ZONE_ID}"
    return
  fi

  cf_api GET "/zones?name=${ZONE_NAME}&account.id=${CLOUDFLARE_ACCOUNT_ID}" | jq -r '.result[0].id // empty'
}

ensure_dns_record() {
  local zone_id="$1"

  local existing
  existing="$(cf_api GET "/zones/${zone_id}/dns_records?name=${HOSTNAME}" | jq -c '.result[0] // empty')"

  if [ -n "$existing" ] && [ "$existing" != "null" ]; then
    local current_target
    current_target="$(echo "$existing" | jq -r '.content')"
    local record_id
    record_id="$(echo "$existing" | jq -r '.id')"

    if [ "$current_target" = "$FLY_HOSTNAME" ]; then
      echo "DNS record for ${HOSTNAME} already points to ${FLY_HOSTNAME}."
      return
    fi

    echo "Updating DNS record for ${HOSTNAME}: ${current_target} -> ${FLY_HOSTNAME}..."
    local response
    response="$(cf_api PATCH "/zones/${zone_id}/dns_records/${record_id}" "$(jq -nc \
      --arg type "CNAME" \
      --arg name "$DNS_RECORD_NAME" \
      --arg content "$FLY_HOSTNAME" \
      '{type: $type, name: $name, content: $content, ttl: 1, proxied: true}')")"

    if ! echo "$response" | jq -e '.success == true' >/dev/null; then
      echo "Failed to update DNS record:"
      echo "$response" | jq .
      exit 1
    fi

    echo "DNS record updated."
    return
  fi

  echo "Creating DNS CNAME record for ${HOSTNAME} -> ${FLY_HOSTNAME}..."
  local response
  response="$(cf_api POST "/zones/${zone_id}/dns_records" "$(jq -nc \
    --arg type "CNAME" \
    --arg name "$DNS_RECORD_NAME" \
    --arg content "$FLY_HOSTNAME" \
    '{type: $type, name: $name, content: $content, ttl: 1, proxied: true}')")"

  if ! echo "$response" | jq -e '.success == true' >/dev/null; then
    echo "Failed to create DNS record:"
    echo "$response" | jq .
    exit 1
  fi

  echo "DNS record created."
}

ensure_fly_certificate() {
  echo "Ensuring Fly.io certificate for ${HOSTNAME}..."
  if fly certs list -a "$APP_NAME" 2>/dev/null | grep -Fq "$HOSTNAME"; then
    echo "Certificate already configured for ${HOSTNAME}."
    # Don't return here - we need to verify it's fully provisioned
  else
    fly certs add "$HOSTNAME" -a "$APP_NAME"
    echo "Certificate request submitted for ${HOSTNAME}."
  fi
  
  # Always run verification to ensure the certificate is ready
  verify_certificate || true
}

verify_certificate() {
  local attempts=24
  local delay=5

  echo "Verifying SSL certificate for ${HOSTNAME}..."
  for ((i = 1; i <= attempts; i++)); do
    if fly certs verify "$HOSTNAME" -a "$APP_NAME" 2>&1 | grep -q "Certificate verified"; then
      echo "SSL certificate verified for ${HOSTNAME}."
      return 0
    fi

    # Also check if cert is 'verified' in the list output
    if fly certs list -a "$APP_NAME" 2>/dev/null | grep -Fq "$HOSTNAME.*verified"; then
      echo "SSL certificate verified for ${HOSTNAME}."
      return 0
    fi

    echo "Attempt ${i}/${attempts}: certificate not ready yet, retrying in ${delay}s..."
    sleep "$delay"
  done

  echo "Warning: SSL certificate not verified after waiting."
  echo "Proceeding anyway - certificate may still be provisioning..."
  return 1
}

verify_endpoint() {
  local attempts=36
  local delay=5

  echo "Verifying https://${HOSTNAME}/health/liveliness ..."
  for ((i = 1; i <= attempts; i++)); do
    if curl -fsS "https://${HOSTNAME}/health/liveliness" >/dev/null 2>&1; then
      echo "https://${HOSTNAME} is healthy."
      return 0
    fi

    echo "Attempt ${i}/${attempts}: endpoint not ready yet, retrying in ${delay}s..."
    sleep "$delay"
  done

  echo "Error: https://${HOSTNAME} did not become healthy after deploy."
  exit 1
}

require_cmd jq
require_cmd curl
require_cmd fly

if [ -z "${FLY_API_TOKEN:-}" ]; then
  echo "FLY_API_TOKEN is required (set via Doppler or env)."
  exit 1
fi

if [ -z "${LITELLM_MASTER_KEY:-}" ]; then
  echo "LITELLM_MASTER_KEY is required (set via Doppler or env)."
  echo "Generate one: openssl rand -hex 32 | xargs -I{} doppler secrets set LITELLM_MASTER_KEY sk-{} --project personal --config dev"
  exit 1
fi

if [ -z "${DATABASE_URL:-}" ]; then
  echo "DATABASE_URL is required (set via Doppler or env)."
  exit 1
fi

ensure_litellm_schema_url() {
  local url="$1"

  if [[ "$url" == *"schema="* ]]; then
    echo "$url"
    return
  fi

  if [[ "$url" == *"?"* ]]; then
    echo "${url}&schema=litellm"
  else
    echo "${url}?schema=litellm"
  fi
}

DATABASE_URL="$(ensure_litellm_schema_url "$DATABASE_URL")"

if [ -z "${OPENAI_API_KEY:-}" ]; then
  echo "OPENAI_API_KEY is required (set via Doppler or env)."
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

export FLY_API_TOKEN

LM_STUDIO_API_KEY="${LM_STUDIO_API_KEY:-local}"

if ! fly apps list 2>/dev/null | awk '{print $1}' | grep -Fxq "$APP_NAME"; then
  echo "Creating Fly.io app ${APP_NAME}..."
  fly apps create "$APP_NAME"
fi

echo "Syncing Fly.io secrets..."
fly secrets set \
  LITELLM_MASTER_KEY="$LITELLM_MASTER_KEY" \
  OPENAI_API_KEY="$OPENAI_API_KEY" \
  LM_STUDIO_API_KEY="$LM_STUDIO_API_KEY" \
  DATABASE_URL="$DATABASE_URL" \
  -a "$APP_NAME"

echo "Deploying LiteLLM to Fly.io..."
cd litellm
fly deploy --remote-only -a "$APP_NAME"
cd ..

ZONE_ID="$(resolve_zone_id)"
if [ -z "$ZONE_ID" ]; then
  echo "Could not resolve Cloudflare zone ID for ${ZONE_NAME}."
  echo "Set CLOUDFLARE_ZONE_ID in Doppler or ensure the API token can read zones."
  exit 1
fi

echo "Using Cloudflare zone ${ZONE_NAME} (${ZONE_ID})."
ensure_dns_record "$ZONE_ID"
ensure_fly_certificate
verify_endpoint

echo "Deployment complete: https://${HOSTNAME}"
