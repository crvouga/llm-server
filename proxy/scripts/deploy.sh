#!/usr/bin/env bash
# Idempotent deploy: GHCR visibility, Fly.io app/secrets/deploy/certs, Cloudflare DNS + Worker cleanup.
set -euo pipefail

cd "$(dirname "$0")/.."

FLY_APP="${FLY_APP:-chrisvouga-llm-proxy}"
FLY_HOSTNAME="${FLY_HOSTNAME:-${FLY_APP}.fly.dev}"
CUSTOM_DOMAIN="${CUSTOM_DOMAIN:-llm-proxy.chrisvouga.dev}"
WORKER_SCRIPT_NAME="${WORKER_SCRIPT_NAME:-llm-proxy}"
GHCR_PACKAGE="${GHCR_PACKAGE:-llm-proxy}"
IMAGE_TAG="${IMAGE_TAG:?IMAGE_TAG is required}"
GHCR_IMAGE="ghcr.io/crvouga/${GHCR_PACKAGE}:${IMAGE_TAG}"

require_env() {
  local name="$1"
  if [ -z "${!name:-}" ]; then
    echo "Error: ${name} is not set" >&2
    exit 1
  fi
}

require_env FLY_API_TOKEN
require_env DATABASE_URL
require_env CLOUDFLARE_API_TOKEN
require_env CLOUDFLARE_ACCOUNT_ID

cf_api() {
  local method="$1"
  local url="$2"
  local data="${3:-}"
  local args=(-sS -X "$method" "$url" -H "Authorization: Bearer ${CLOUDFLARE_API_TOKEN}" -H "Content-Type: application/json")
  if [ -n "$data" ]; then
    args+=(-d "$data")
  fi
  curl "${args[@]}"
}

cf_log_errors() {
  local label="$1"
  local resp="$2"
  echo "$resp" | jq -r --arg label "$label" '
    if .success == true then empty
    else
      $label + " failed:",
      (.errors[]? | "  [\(.code)] \(.message)"),
      (if (.errors | length) == 0 then "  (no error details in response)" else empty end)
    end' >&2
}

cf_ok() {
  local resp="$1"
  echo "$resp" | jq -e '.success == true' >/dev/null
}

cf_delete_worker_script() {
  local script_status delete_resp
  script_status="$(curl -sS -o /dev/null -w '%{http_code}' \
    -X GET "https://api.cloudflare.com/client/v4/accounts/${CLOUDFLARE_ACCOUNT_ID}/workers/scripts/${WORKER_SCRIPT_NAME}" \
    -H "Authorization: Bearer ${CLOUDFLARE_API_TOKEN}")"
  if [ "$script_status" = "404" ]; then
    echo "  worker script ${WORKER_SCRIPT_NAME} not present"
    return 0
  fi
  if [ "$script_status" != "200" ]; then
    echo "  worker script lookup returned HTTP ${script_status} (continuing)"
    return 0
  fi
  echo "  deleting worker script ${WORKER_SCRIPT_NAME}"
  delete_resp="$(cf_api DELETE "https://api.cloudflare.com/client/v4/accounts/${CLOUDFLARE_ACCOUNT_ID}/workers/scripts/${WORKER_SCRIPT_NAME}")"
  if cf_ok "$delete_resp"; then
    echo "  worker script deleted"
    return 0
  fi
  cf_log_errors "Worker script delete" "$delete_resp"
  return 1
}

cf_delete_worker_domains() {
  local domains_resp domain_ids
  domains_resp="$(cf_api GET "https://api.cloudflare.com/client/v4/accounts/${CLOUDFLARE_ACCOUNT_ID}/workers/domains")"
  if ! cf_ok "$domains_resp"; then
    cf_log_errors "Worker domains list" "$domains_resp"
    return 1
  fi

  domain_ids="$(echo "$domains_resp" | jq -r --arg host "$CUSTOM_DOMAIN" '.result[]? | select(.hostname == $host) | .id')"
  if [ -z "$domain_ids" ]; then
    echo "  no worker custom domain for ${CUSTOM_DOMAIN}"
    return 0
  fi

  local domain_id delete_resp
  while IFS= read -r domain_id; do
    [ -z "$domain_id" ] && continue
    echo "  deleting worker domain ${domain_id} (${CUSTOM_DOMAIN})"
    delete_resp="$(cf_api DELETE "https://api.cloudflare.com/client/v4/accounts/${CLOUDFLARE_ACCOUNT_ID}/workers/domains/${domain_id}")"
    if cf_ok "$delete_resp"; then
      echo "  worker domain deleted"
      continue
    fi
    cf_log_errors "Worker domain delete" "$delete_resp"
    # Domain may already be gone after script deletion; treat missing-domain as success.
    if echo "$delete_resp" | jq -e '.errors[]? | select(.code == 10000 or .code == 10001 or .code == 7003)' >/dev/null; then
      echo "  worker domain already removed"
      continue
    fi
    return 1
  done <<< "$domain_ids"
}

cf_zone_id() {
  local hostname="$1"
  local zone_name="${hostname#*.}"
  local resp
  resp="$(cf_api GET "https://api.cloudflare.com/client/v4/zones?name=${zone_name}")"
  echo "$resp" | jq -e -r '.success and (.result | length > 0)' >/dev/null
  echo "$resp" | jq -r '.result[0].id'
}

ensure_ghcr_public() {
  if [ -z "${GITHUB_TOKEN:-}" ]; then
    echo "GITHUB_TOKEN not set — skipping GHCR visibility update"
    return 0
  fi
  echo "Ensuring GHCR package ${GHCR_PACKAGE} is public..."
  local status
  status="$(curl -sS -o /dev/null -w '%{http_code}' \
    -X PATCH "https://api.github.com/user/packages/container/${GHCR_PACKAGE}" \
    -H "Authorization: Bearer ${GITHUB_TOKEN}" \
    -H "Accept: application/vnd.github+json" \
    -H "X-GitHub-Api-Version: 2022-11-28" \
    -d '{"visibility":"public"}')"
  case "$status" in
    200|204) echo "GHCR package visibility: public" ;;
    404) echo "GHCR package not found yet (will be public after first push completes)" ;;
    *) echo "GHCR visibility update returned HTTP ${status} (continuing)" ;;
  esac
}

ensure_fly_app() {
  echo "Ensuring Fly app ${FLY_APP} exists..."
  if flyctl apps list --json | jq -e --arg name "$FLY_APP" '.[] | select(.Name == $name or .name == $name)' >/dev/null; then
    echo "Fly app ${FLY_APP} already exists"
    return 0
  fi
  if flyctl apps create "$FLY_APP" --yes; then
    return 0
  fi
  if flyctl apps list --json | jq -e --arg name "$FLY_APP" '.[] | select(.Name == $name or .name == $name)' >/dev/null; then
    echo "Fly app ${FLY_APP} exists after create attempt"
    return 0
  fi
  echo "Error: failed to create Fly app ${FLY_APP}" >&2
  return 1
}

ensure_fly_secrets() {
  echo "Syncing Fly secrets..."
  flyctl secrets set "DATABASE_URL=${DATABASE_URL}" --app "$FLY_APP"
}

deploy_fly() {
  echo "Deploying ${GHCR_IMAGE} to Fly..."
  flyctl deploy --remote-only --image "$GHCR_IMAGE" --app "$FLY_APP"
}

ensure_fly_cert() {
  echo "Ensuring TLS cert for ${CUSTOM_DOMAIN}..."
  if flyctl certs list --app "$FLY_APP" --json | jq -e --arg host "$CUSTOM_DOMAIN" '.[] | select(.Hostname == $host)' >/dev/null; then
    echo "Fly cert already registered for ${CUSTOM_DOMAIN}"
  else
    flyctl certs add "$CUSTOM_DOMAIN" --app "$FLY_APP"
  fi

  echo "Waiting for Fly cert to become ready..."
  for _ in $(seq 1 36); do
    local status
    status="$(flyctl certs show "$CUSTOM_DOMAIN" --app "$FLY_APP" --json 2>/dev/null | jq -r '.ClientStatus // empty')"
    if [ "$status" = "Ready" ]; then
      echo "Fly cert ready for ${CUSTOM_DOMAIN}"
      return 0
    fi
    echo "  cert status: ${status:-pending} — retrying in 10s"
    sleep 10
  done
  echo "Warning: Fly cert not Ready yet; DNS step may still succeed once validation completes"
}

remove_cf_worker() {
  echo "Removing Cloudflare Worker custom domain and script (if present)..."
  local failed=0

  # Delete script first — custom domains are often released automatically.
  cf_delete_worker_script || failed=1
  sleep 2
  cf_delete_worker_domains || failed=1

  if [ "$failed" -ne 0 ]; then
    echo "Warning: Worker cleanup had errors; continuing with DNS cutover" >&2
  fi
}

ensure_cf_dns() {
  echo "Ensuring Cloudflare DNS: ${CUSTOM_DOMAIN} → ${FLY_HOSTNAME}"
  local zone_id record_name resp records rec_id rec_content write_resp
  zone_id="$(cf_zone_id "$CUSTOM_DOMAIN")"
  record_name="${CUSTOM_DOMAIN%%.*}"

  resp="$(cf_api GET "https://api.cloudflare.com/client/v4/zones/${zone_id}/dns_records?type=CNAME&name=${CUSTOM_DOMAIN}")"
  if ! cf_ok "$resp"; then
    cf_log_errors "DNS list" "$resp"
    return 1
  fi
  records="$(echo "$resp" | jq '.result')"
  rec_content="${FLY_HOSTNAME}"

  if [ "$(echo "$records" | jq 'length')" -gt 0 ]; then
    rec_id="$(echo "$records" | jq -r '.[0].id')"
    local current_content current_proxied
    current_content="$(echo "$records" | jq -r '.[0].content')"
    current_proxied="$(echo "$records" | jq -r '.[0].proxied')"
    if [ "$current_content" = "$rec_content" ] && [ "$current_proxied" = "true" ]; then
      echo "DNS already correct: ${CUSTOM_DOMAIN} → ${rec_content} (proxied)"
      return 0
    fi
    echo "  updating DNS record ${rec_id}"
    write_resp="$(cf_api PUT "https://api.cloudflare.com/client/v4/zones/${zone_id}/dns_records/${rec_id}" \
      "$(jq -nc --arg name "$record_name" --arg content "$rec_content" \
        '{type:"CNAME",name:$name,content:$content,proxied:true}')")"
  else
    echo "  creating DNS record"
    write_resp="$(cf_api POST "https://api.cloudflare.com/client/v4/zones/${zone_id}/dns_records" \
      "$(jq -nc --arg name "$record_name" --arg content "$rec_content" \
        '{type:"CNAME",name:$name,content:$content,proxied:true}')")"
  fi
  if ! cf_ok "$write_resp"; then
    cf_log_errors "DNS write" "$write_resp"
    return 1
  fi
  echo "DNS routed: ${CUSTOM_DOMAIN} → ${rec_content} (proxied)"
}

wait_for_https() {
  local url="$1"
  echo "Waiting for ${url} to respond..."
  for _ in $(seq 1 30); do
    local code
    code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 10 "$url" || true)"
    if [ "$code" = "200" ] || [ "$code" = "302" ] || [ "$code" = "301" ]; then
      echo "${url} is up (HTTP ${code})"
      return 0
    fi
    echo "  HTTP ${code:-000} — retrying in 10s"
    sleep 10
  done
  echo "Warning: ${url} did not become ready in time"
  return 1
}

ensure_fly_app
ensure_fly_secrets
deploy_fly
remove_cf_worker
ensure_cf_dns
ensure_fly_cert
ensure_ghcr_public
wait_for_https "https://${CUSTOM_DOMAIN}/" || true

echo "Deploy complete: https://${CUSTOM_DOMAIN}"
