#!/usr/bin/env bash
#
# ensure-cursor-cloudflare-access.sh
# Idempotently configures Cloudflare so external API clients (e.g. Cursor's
# verification servers) can reach the LM Studio endpoint behind the tunnel.
#
# The tunnel itself works from a browser/residential IP, but Cursor verifies a
# custom OpenAI base URL from its own datacenter IPs. Cloudflare Bot Fight Mode /
# Super Bot Fight Mode / "Block AI bots" / managed WAF rules silently block that
# datacenter request, so it never reaches LM Studio. This script adds a scoped
# WAF *skip* rule for just the LM Studio hostname (bot products, SBFM phase,
# managed rules, and rate limiting) and flags any Zero Trust Access policy that
# would gate the host. Safe to re-run.
#
# Usage:
#   ./ensure-cursor-cloudflare-access.sh
#
# Secrets are pulled from Doppler (not passed as plaintext env vars):
#   CLOUDFLARE_API_TOKEN - Token with "Zone WAF: Edit" + "Zone: Read" on the zone.
#                          For the Access check also add "Access: Apps: Read".
#
# Doppler access (provide ONE of these so the CLI can read the secrets):
#   DOPPLER_TOKEN     - A Doppler service token scoped to the project/config.
#   ...or a pre-configured `doppler setup` / `doppler login` on the host.
#   DOPPLER_PROJECT   - Doppler project (optional; omit if the token is scoped).
#   DOPPLER_CONFIG    - Doppler config, e.g. "dev" / "prd" (optional, same caveat).
#
# Optional environment variables (non-secret):
#   CF_ZONE_NAME      - Apex zone, e.g. "chrisvouga.dev" (default below).
#   LM_HOSTNAME       - Hostname to allow, e.g. "lm-studio.chrisvouga.dev".
#   CF_ZONE_ID        - Skip zone lookup by passing the zone id directly.
#   CF_ACCOUNT_ID     - Account id; enables the Zero Trust Access policy check.

set -euo pipefail

log()  { printf '\033[1;34m[*]\033[0m %s\n' "$*"; }
ok()   { printf '\033[1;32m[ok]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[!]\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31m[x]\033[0m %s\n' "$*" >&2; exit 1; }

CF_ZONE_NAME="${CF_ZONE_NAME:-chrisvouga.dev}"
LM_HOSTNAME="${LM_HOSTNAME:-lm-studio.chrisvouga.dev}"
RULE_DESC="cursor-llm-allow: skip bot/WAF for ${LM_HOSTNAME}"
API="https://api.cloudflare.com/client/v4"

log "Zone: ${CF_ZONE_NAME}  Hostname: ${LM_HOSTNAME}"

# ----------------------------------------------------------------------------
# 0. Tooling: curl + jq
# ----------------------------------------------------------------------------
command -v curl >/dev/null 2>&1 || die "curl is required."
if ! command -v jq >/dev/null 2>&1; then
  log "Installing jq..."
  if   command -v apt-get >/dev/null 2>&1; then sudo apt-get update -y && sudo apt-get install -y jq
  elif command -v brew    >/dev/null 2>&1; then brew install jq
  else die "jq not found and no apt-get/brew to install it."
  fi
  ok "Installed jq."
fi

# ----------------------------------------------------------------------------
# 1. Secrets via Doppler
# ----------------------------------------------------------------------------
log "Ensuring Doppler CLI and loading secrets..."
if ! command -v doppler >/dev/null 2>&1; then
  curl -fsSL https://cli.doppler.com/install.sh | sh
  ok "Installed Doppler CLI."
else
  ok "Doppler CLI already installed."
fi

# The host's Doppler CLI token is unscoped, so a bare `doppler secrets get`
# fails with "must specify a config". Default to this repo's project/config
# (still overridable via env) so the script works when run without flags.
DOPPLER_PROJECT="${DOPPLER_PROJECT:-personal}"
DOPPLER_CONFIG="${DOPPLER_CONFIG:-dev}"

DOPPLER_ARGS=()
[ -n "${DOPPLER_PROJECT:-}" ] && DOPPLER_ARGS+=(--project "${DOPPLER_PROJECT}")
[ -n "${DOPPLER_CONFIG:-}"  ] && DOPPLER_ARGS+=(--config  "${DOPPLER_CONFIG}")

doppler_secret() {
  doppler secrets get "$1" --plain ${DOPPLER_ARGS[@]+"${DOPPLER_ARGS[@]}"} 2>/dev/null || true
}

[ -n "${CLOUDFLARE_API_TOKEN:-}" ] || CLOUDFLARE_API_TOKEN="$(doppler_secret CLOUDFLARE_API_TOKEN)"
[ -n "${CLOUDFLARE_API_TOKEN}" ] || die "CLOUDFLARE_API_TOKEN not found (Doppler or env). Needs Zone WAF:Edit + Zone:Read."
ok "Loaded CLOUDFLARE_API_TOKEN."

# Account id (for the Zero Trust Access check) — env wins, else pull from Doppler.
[ -n "${CF_ACCOUNT_ID:-}" ] || CF_ACCOUNT_ID="$(doppler_secret CLOUDFLARE_ACCOUNT_ID)"

# Thin wrapper around the Cloudflare API. Echoes the JSON body; dies on transport
# error. Callers inspect `.success` for API-level failures.
cf() {
  local method="$1" path="$2"; shift 2
  curl -fsS -X "$method" "${API}${path}" \
    -H "Authorization: Bearer ${CLOUDFLARE_API_TOKEN}" \
    -H "Content-Type: application/json" "$@"
}

cf_ok() { jq -e '.success == true' >/dev/null 2>&1; }

# ----------------------------------------------------------------------------
# 2. Verify token + resolve zone id
# ----------------------------------------------------------------------------
log "Verifying API token..."
cf GET /user/tokens/verify | cf_ok || die "API token failed verification (check value/permissions)."
ok "API token valid."

ZONE_ID="${CF_ZONE_ID:-}"
if [ -z "${ZONE_ID}" ]; then
  log "Resolving zone id for ${CF_ZONE_NAME}..."
  ZONE_ID="$(cf GET "/zones?name=${CF_ZONE_NAME}" | jq -r '.result[0].id // empty')"
  [ -n "${ZONE_ID}" ] || die "Could not resolve zone '${CF_ZONE_NAME}' (token needs Zone:Read on it)."
fi
ok "Zone id: ${ZONE_ID}"

# ----------------------------------------------------------------------------
# 3. WAF custom-rules entrypoint (http_request_firewall_custom phase)
# ----------------------------------------------------------------------------
log "Fetching WAF custom-rules entrypoint ruleset..."
ENTRYPOINT="$(cf GET "/zones/${ZONE_ID}/rulesets/phases/http_request_firewall_custom/entrypoint" 2>/dev/null || true)"

RULESET_ID=""
if printf '%s' "${ENTRYPOINT}" | cf_ok; then
  RULESET_ID="$(printf '%s' "${ENTRYPOINT}" | jq -r '.result.id')"
fi

# Skip-rule expression + action: bypass everything that blocks datacenter clients
# for ONLY this hostname. `phases` covers SBFM + managed WAF + rate limiting;
# `products` covers (Super) Bot Fight Mode, browser integrity, security level,
# UA/zone blocks. Scoped tightly by http.host so the rest of the zone is untouched.
EXPRESSION="(http.host eq \"${LM_HOSTNAME}\")"
RULE_JSON="$(jq -n --arg expr "${EXPRESSION}" --arg desc "${RULE_DESC}" '{
  action: "skip",
  expression: $expr,
  description: $desc,
  enabled: true,
  action_parameters: {
    ruleset: "current",
    phases: ["http_ratelimit", "http_request_sbfm", "http_request_firewall_managed"],
    products: ["zoneLockdown","uaBlock","bic","hot","securityLevel","rateLimit","waf"]
  }
}')"

if [ -z "${RULESET_ID}" ]; then
  log "No custom-rules ruleset yet; creating one with the allow rule..."
  RESP="$(cf POST "/zones/${ZONE_ID}/rulesets" --data "$(jq -n --argjson rule "${RULE_JSON}" '{
    name: "default",
    kind: "zone",
    phase: "http_request_firewall_custom",
    rules: [$rule]
  }')")"
  printf '%s' "${RESP}" | cf_ok || die "Failed to create ruleset: $(printf '%s' "${RESP}" | jq -c '.errors')"
  ok "Created custom-rules ruleset with allow rule."
else
  EXISTING_RULE_ID="$(printf '%s' "${ENTRYPOINT}" | jq -r --arg d "${RULE_DESC}" '.result.rules[]? | select(.description == $d) | .id' | head -n1)"
  if [ -n "${EXISTING_RULE_ID}" ]; then
    log "Allow rule already present (${EXISTING_RULE_ID}); updating to desired state..."
    RESP="$(cf PATCH "/zones/${ZONE_ID}/rulesets/${RULESET_ID}/rules/${EXISTING_RULE_ID}" --data "${RULE_JSON}")"
    printf '%s' "${RESP}" | cf_ok || die "Failed to update rule: $(printf '%s' "${RESP}" | jq -c '.errors')"
    ok "Allow rule updated."
  else
    log "Adding allow rule to existing ruleset..."
    RESP="$(cf POST "/zones/${ZONE_ID}/rulesets/${RULESET_ID}/rules" --data "${RULE_JSON}")"
    printf '%s' "${RESP}" | cf_ok || die "Failed to add rule: $(printf '%s' "${RESP}" | jq -c '.errors')"
    ok "Allow rule added."
  fi
fi

# ----------------------------------------------------------------------------
# 3.5 Bot Fight Mode (Free plan) — NOT skippable by WAF rules, must be off
# ----------------------------------------------------------------------------
# On the Free plan, Bot Fight Mode is zone-wide and all-or-nothing: a WAF skip
# rule cannot exclude a hostname from it (only *Super* Bot Fight Mode on Pro+
# is per-rule skippable). Since Cursor's verify request originates from its own
# datacenter IPs, Bot Fight Mode will block it. Disable it (idempotently).
# Requires the token to have "Zone -> Bot Management -> Edit"; degrades to a
# warning if the permission is missing rather than failing the whole run.
if [ "${BOT_FIGHT_MODE_DISABLE:-yes}" = "yes" ]; then
  log "Checking Bot Fight Mode (Free-plan zone-wide bot block)..."
  # Raw curl (no -f) so we can read the JSON body even on 403.
  BM="$(curl -sS "${API}/zones/${ZONE_ID}/bot_management" \
        -H "Authorization: Bearer ${CLOUDFLARE_API_TOKEN}" || true)"
  if printf '%s' "${BM}" | cf_ok; then
    FIGHT="$(printf '%s' "${BM}" | jq -r '.result.fight_mode // false')"
    if [ "${FIGHT}" = "true" ]; then
      log "Bot Fight Mode is ON; disabling it..."
      RESP="$(curl -sS -X PUT "${API}/zones/${ZONE_ID}/bot_management" \
        -H "Authorization: Bearer ${CLOUDFLARE_API_TOKEN}" \
        -H "Content-Type: application/json" \
        --data '{"fight_mode": false}' || true)"
      if printf '%s' "${RESP}" | cf_ok; then
        ok "Bot Fight Mode disabled."
      else
        warn "Failed to disable Bot Fight Mode: $(printf '%s' "${RESP}" | jq -c '.errors')"
      fi
    else
      ok "Bot Fight Mode already disabled."
    fi
  else
    warn "Cannot read Bot Fight Mode: $(printf '%s' "${BM}" | jq -c '.errors? // "no body"')."
    warn "  -> Token likely lacks 'Zone -> Bot Management -> Edit'. Add it and re-run,"
    warn "     or toggle Bot Fight Mode off manually: Security -> Bots in the dashboard."
  fi
else
  warn "BOT_FIGHT_MODE_DISABLE != yes; leaving Bot Fight Mode untouched."
fi

# ----------------------------------------------------------------------------
# 4. Zero Trust Access policy check (best-effort; needs CF_ACCOUNT_ID)
# ----------------------------------------------------------------------------
if [ -n "${CF_ACCOUNT_ID:-}" ]; then
  log "Checking for Zero Trust Access apps gating ${LM_HOSTNAME}..."
  APPS="$(cf GET "/accounts/${CF_ACCOUNT_ID}/access/apps" 2>/dev/null || true)"
  if printf '%s' "${APPS}" | cf_ok; then
    MATCH="$(printf '%s' "${APPS}" | jq -r --arg h "${LM_HOSTNAME}" '.result[]? | select((.domain // "") | contains($h)) | .name' | head -n1)"
    if [ -n "${MATCH}" ]; then
      warn "Access application '${MATCH}' covers ${LM_HOSTNAME}."
      warn "  -> It will show a login page to Cursor and block verification."
      warn "  -> Remove the policy for this host, or add a service-token bypass in Zero Trust."
    else
      ok "No blocking Access application found for ${LM_HOSTNAME}."
    fi
  else
    warn "Could not list Access apps (token may lack Access:Apps:Read). Skipping check."
  fi
else
  warn "CF_ACCOUNT_ID not set; skipping Zero Trust Access policy check."
  warn "  -> If a login page appears at https://${LM_HOSTNAME}, an Access policy is blocking Cursor."
fi

# ----------------------------------------------------------------------------
# 5. Verify the endpoint answers the OpenAI model list
# ----------------------------------------------------------------------------
log "Verifying https://${LM_HOSTNAME}/v1/models ..."
if curl -fsS -m 20 "https://${LM_HOSTNAME}/v1/models" | jq -e '.data | length > 0' >/dev/null 2>&1; then
  ok "Endpoint returned a non-empty model list."
else
  warn "Endpoint did not return a model list. Is LM Studio's server running on the tunnel origin?"
fi

# ----------------------------------------------------------------------------
# 6. Summary
# ----------------------------------------------------------------------------
echo
log "==================== SUMMARY ===================="
ok  "WAF allow rule ensured for ${LM_HOSTNAME} (bot/SBFM/managed/rate-limit skipped)."
echo
ok  "Now configure Cursor (Settings -> Models -> OpenAI API Key):"
echo "    Base URL : https://${LM_HOSTNAME}/v1"
echo "    API Key  : any non-empty string (e.g. lm-studio)"
echo "    Model    : add an exact id from /v1/models, e.g. qwen/qwen3-coder-next"
echo "    Disable all default Cursor models before clicking Verify."
