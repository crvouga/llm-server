# Declarative Local LLM Environment

`local-llm-env` is a Terraform-like reconciler for exposing a local LM Studio API:
- host dependency installation (including LM Studio binary helper)
- Cloudflare Tunnel config + DNS route declaration
- systemd user service for `cloudflared`
- Doppler-managed secrets for credentials

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
- `local_llm_env/`: CLI, schema validation, reconcilers, state/diff logic
- `llm-usage-tracker/`: Cloudflare Worker proxy at `llm.chrisvouga.dev` with usage tracking
- `state/local-llm-env-state.json`: last applied managed state
- `systemd/*.service`: template reference units

## Doppler Setup

1. Login and configure Doppler locally:
   - `doppler login`
   - `doppler setup --project personal --config dev`
2. Ensure required keys in `spec/local-llm-env.yaml` exist in your Doppler config.
   The default spec expects:
   - `CLOUDFLARE_API_TOKEN`
   - `CLOUDFLARE_ACCOUNT_ID`
   - `CLOUDFLARE_TUNNEL_ID`
   - `CF_TUNNEL_CREDENTIALS_JSON`
   - `DATABASE_URL` (for `llm-usage-tracker`)

## CI/CD

GitHub Actions runs the [deployment pipeline](.github/workflows/deployment-pipeline.yml) on every push and pull request to `main`:

1. **Checks** — Python tests (`make test`) and Worker typecheck (`make check-worker`)
2. **Deploy** (push to `main` only) — sync Worker secrets and deploy `llm-usage-tracker` (`make deploy-worker`)

All runtime secrets are loaded from Doppler (`personal` / `dev`). GitHub only stores a single bootstrap secret.

### Seed GitHub Secrets

One-time setup to allow CI to access Doppler:

```bash
# Requires: gh auth login, doppler login
make doppler-seed-github-secrets
```

This creates a Doppler service token (or uses `DOPPLER_SERVICE_TOKEN` if already set) and stores it as the `DOPPLER_SERVICE_TOKEN` GitHub Actions secret.

To target a specific repo:

```bash
GITHUB_REPO=crvouga/llm-server make doppler-seed-github-secrets
```

### Local CI parity

```bash
doppler run --project personal --config dev -- make check
doppler run --project personal --config dev -- make deploy-worker
```

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
- `systemctl --user status lm-studio-cloudflared.service`
- local endpoint responds (`http://127.0.0.1:1234`)
- tunnel DNS hostnames route to expected local services
- second `plan` shows no-op or only informational drift

## Notes

- LM Studio model downloads, model selection, and server lifecycle are intentionally user-managed in LM Studio.
- Cloudflare route creation can require a pre-existing tunnel and account token scopes.
- The reconciler only deletes resources marked as managed by spec/state rules.

