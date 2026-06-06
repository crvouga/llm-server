# Declarative Local LLM Environment

`local-llm-env` is a Terraform-like reconciler for a local LLM stack:
- LM Studio runtime provisioning
- model installation from an explicit manifest
- systemd user services for persistent local serving
- Cloudflare Tunnel + DNS route declaration
- Doppler-managed secrets for all credentials

The workflow is idempotent:
- `plan` computes drift and actions
- `apply` reconciles only what's missing/out-of-sync
- `destroy` tears down managed resources with safety controls

## Requirements

- Linux with `systemd --user`
- Python 3.10+
- `sudo` access if using `apt` installs
- Doppler account/project/config with required keys
- Cloudflare account with tunnel + DNS permissions

## Project Layout

- `spec/local-llm-env.yaml`: primary desired-state declaration
- `spec/models.yaml`: explicit model inventory (all managed models)
- `local_llm_env/`: CLI, schema validation, reconcilers, state/diff logic
- `state/local-llm-env-state.json`: last applied managed state
- `systemd/*.service`: template reference units

## Doppler Setup

1. Login and configure Doppler locally:
   - `doppler login`
   - `doppler setup --project local-llm --config dev`
2. Ensure required keys exist in Doppler `dev` config:
   - `CF_API_TOKEN`
   - `CF_ACCOUNT_ID`
   - `CF_ZONE_ID`
   - `CF_TUNNEL_ID`
   - `CF_TUNNEL_CREDENTIALS_JSON` (if used in your tunnel flow)

## Install CLI

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Declarative Lifecycle

### Plan

```bash
local-llm-env plan --spec spec/local-llm-env.yaml --state state/local-llm-env-state.json
```

### Apply

```bash
local-llm-env apply --spec spec/local-llm-env.yaml --state state/local-llm-env-state.json
```

Use `--auto-approve` for non-interactive apply.

### Status

```bash
local-llm-env status --state state/local-llm-env-state.json
```

### Destroy

```bash
local-llm-env destroy --spec spec/local-llm-env.yaml --state state/local-llm-env-state.json
```

## Idempotency and Cleanup

- Re-running `apply` after successful reconciliation should produce no meaningful actions.
- `safety.cleanup_mode` controls destroy behavior:
  - `managed_only`: remove managed service/tunnel resources only.
  - `full_destroy`: remove all managed resources from recorded state.

## Verification Checklist

After `apply`, validate:
- `systemctl --user status local-llm-lmstudio.service`
- `systemctl --user status local-llm-cloudflared.service`
- local endpoint responds (`http://127.0.0.1:1234`)
- tunnel DNS hostnames route to expected local services
- second `plan` shows no-op or only informational drift

## Notes

- LM Studio CLI behavior can vary by release; adjust model install command if your `lms` command differs.
- Cloudflare route creation can require a pre-existing tunnel and account token scopes.
- The reconciler only deletes resources marked as managed by spec/state rules.

