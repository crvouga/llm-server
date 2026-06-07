#!/usr/bin/env bash
# Shared Cloudflare API helpers — all Cloudflare access uses CLOUDFLARE_API_TOKEN.

CF_API_BASE="${CF_API_BASE:-https://api.cloudflare.com/client/v4}"

load_cloudflare_secrets() {
  # Populate CLOUDFLARE_API_TOKEN and CLOUDFLARE_ACCOUNT_ID from env or Doppler.
  # Returns 0 when both are set, 1 otherwise.
  if [ -z "${CLOUDFLARE_API_TOKEN:-}" ] && command -v doppler_secret >/dev/null 2>&1; then
    CLOUDFLARE_API_TOKEN="$(doppler_secret CLOUDFLARE_API_TOKEN)"
  fi
  if [ -z "${CLOUDFLARE_ACCOUNT_ID:-}" ] && command -v doppler_secret >/dev/null 2>&1; then
    CLOUDFLARE_ACCOUNT_ID="$(doppler_secret CLOUDFLARE_ACCOUNT_ID)"
  fi
  [ -n "${CLOUDFLARE_API_TOKEN:-}" ] && [ -n "${CLOUDFLARE_ACCOUNT_ID:-}" ]
}

cf_api() {
  local method="$1" path="$2"
  shift 2
  curl -fsS -X "$method" "${CF_API_BASE}${path}" \
    -H "Authorization: Bearer ${CLOUDFLARE_API_TOKEN}" \
    -H "Content-Type: application/json" "$@"
}

cf_api_ok() {
  jq -e '.success == true' >/dev/null 2>&1
}

_cf_tunnel_base() {
  echo "${CF_API_BASE}/accounts/${CLOUDFLARE_ACCOUNT_ID}/cfd_tunnel"
}

# Ensure a named tunnel exists; prints tunnel id to stdout. Returns 1 on failure.
cf_ensure_tunnel() {
  local name="$1"
  local resp tunnel_id secret

  resp="$(cf_api GET "/accounts/${CLOUDFLARE_ACCOUNT_ID}/cfd_tunnel?name=${name}&is_deleted=false")" \
    || return 1
  printf '%s' "${resp}" | cf_api_ok || return 1

  tunnel_id="$(printf '%s' "${resp}" | jq -r '.result[0].id // empty')"
  if [ -n "${tunnel_id}" ]; then
    printf '%s' "${tunnel_id}"
    return 0
  fi

  secret="$(openssl rand -hex 32)"
  resp="$(cf_api POST "/accounts/${CLOUDFLARE_ACCOUNT_ID}/cfd_tunnel" \
    --data "{\"name\":\"${name}\",\"tunnel_secret\":\"${secret}\"}")" \
    || return 1
  printf '%s' "${resp}" | cf_api_ok || return 1
  tunnel_id="$(printf '%s' "${resp}" | jq -r '.result.id // empty')"
  [ -n "${tunnel_id}" ] || return 1
  printf '%s' "${tunnel_id}"
}

# Fetch a connector token for `cloudflared tunnel run --token`. Returns 1 on failure.
cf_tunnel_connector_token() {
  local tunnel_id="$1"
  local resp token

  resp="$(cf_api GET "/accounts/${CLOUDFLARE_ACCOUNT_ID}/cfd_tunnel/${tunnel_id}/token")" \
    || return 1
  printf '%s' "${resp}" | cf_api_ok || return 1
  token="$(printf '%s' "${resp}" | jq -r '.result // empty')"
  [ -n "${token}" ] || return 1
  printf '%s' "${token}"
}

# Create or update a proxied CNAME for a tunnel hostname. Returns 1 on failure.
cf_ensure_tunnel_dns() {
  local tunnel_id="$1" hostname="$2"
  local zone_name="${hostname#*.}"
  local record_name="${hostname%.${zone_name}}"
  local zone_id resp existing_id content

  resp="$(cf_api GET "/zones?name=${zone_name}")" || return 1
  printf '%s' "${resp}" | cf_api_ok || return 1
  zone_id="$(printf '%s' "${resp}" | jq -r '.result[0].id // empty')"
  [ -n "${zone_id}" ] || return 1

  content="${tunnel_id}.cfargotunnel.com"
  resp="$(cf_api GET "/zones/${zone_id}/dns_records?type=CNAME&name=${hostname}")" || return 1
  existing_id="$(printf '%s' "${resp}" | jq -r '.result[0].id // empty')"
  if [ -n "${existing_id}" ]; then
    resp="$(cf_api PATCH "/zones/${zone_id}/dns_records/${existing_id}" \
      --data "{\"type\":\"CNAME\",\"name\":\"${record_name}\",\"content\":\"${content}\",\"proxied\":true}")" \
      || return 1
  else
    resp="$(cf_api POST "/zones/${zone_id}/dns_records" \
      --data "{\"type\":\"CNAME\",\"name\":\"${record_name}\",\"content\":\"${content}\",\"proxied\":true}")" \
      || return 1
  fi
  printf '%s' "${resp}" | cf_api_ok || return 1
}
