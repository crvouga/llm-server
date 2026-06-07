SHELL := /usr/bin/env bash

VENV ?= .venv
LOCAL_BIN ?= $(HOME)/.local/bin
export PATH := $(LOCAL_BIN):$(PATH)

PYTHON := $(VENV)/bin/python3
PIP := $(VENV)/bin/pip
LLM_ENV := $(VENV)/bin/local-llm-env

SPEC ?= spec/local-llm-env.yaml
STATE ?= state/local-llm-env-state.json

CLOUDFLARED_SERVICE ?= lm-studio-cloudflared.service
SERVICES := $(CLOUDFLARED_SERVICE)

REMOTE_ACCESS_MD ?= REMOTE-ACCESS.md
REMOTE_USER ?= $(shell awk -F'|' '/^\|/ && index($$2, "Login user") { gsub(/^[ \t`]+|[ \t`]+$$/, "", $$3); print $$3; exit }' "$(REMOTE_ACCESS_MD)" 2>/dev/null)
REMOTE_HOST ?= $(shell awk -F'|' '/^\|/ && index($$2, "Tailscale DNS name") { gsub(/^[ \t`]+|[ \t`]+$$/, "", $$3); print $$3; exit }' "$(REMOTE_ACCESS_MD)" 2>/dev/null)

COMMIT_MSG ?=

DOPPLER_PROJECT ?= personal
DOPPLER_CONFIG ?= dev
GITHUB_REPO ?=

VLLM_CONTAINER ?= vllm-qwen36-dflash

.PHONY: help venv install setup doctor ensure-system-deps plan apply apply-auto status destroy destroy-auto \
	start stop restart logs logs-cloudflared logs-vllm \
	service-status shell clean-venv ssh-target target-tmux pull push gh \
	check test doppler-seed-github-secrets setup-tunnel run kill configure-always-on monitor

help:
	@echo "Targets:"
	@echo "  make setup          -> install system deps + venv deps, then run full checks"
	@echo "  make ensure-system-deps -> install required system binaries (idempotent)"
	@echo "  make doctor         -> validate all required prerequisites"
	@echo "  make plan           -> show reconcile plan"
	@echo "  make apply          -> apply reconcile plan (interactive confirmation)"
	@echo "  make apply-auto     -> apply reconcile plan (non-interactive)"
	@echo "  make status         -> show last applied state file"
	@echo "  make destroy        -> destroy managed resources (interactive confirmation)"
	@echo "  make destroy-auto   -> destroy managed resources (non-interactive)"
	@echo "  make start          -> start all managed systemd user services"
	@echo "  make stop           -> stop all managed systemd user services"
	@echo "  make restart        -> restart all managed systemd user services"
	@echo "  make service-status -> show status for managed services"
	@echo "  make logs           -> tail logs for all services"
	@echo "  make shell          -> open shell with venv activated"
	@echo "  make clean-venv     -> remove local virtual environment"
	@echo "  make ssh-target     -> SSH into the Linux target (via Tailscale)"
	@echo "  make target-tmux    -> SSH into target with tmux session 'work'"
	@echo "  make pull           -> git pull from upstream (auto-stash local changes)"
	@echo "  make push           -> git add, commit (if needed), push to upstream"
	@echo "  make gh             -> open GitHub webpage for this repo"
	@echo "  make check          -> run all CI checks (Python tests)"
	@echo "  make test           -> run Python tests"
	@echo "  make doppler-seed-github-secrets -> seed DOPPLER_SERVICE_TOKEN in GitHub secrets"
	@echo "  make setup-tunnel       -> Cloudflare tunnel for LM Studio (port 1234 → lm-studio.chrisvouga.dev)"
	@echo "  make setup-vllm-tunnel  -> Cloudflare tunnel routes for vLLM (port 8000 → vllm.chrisvouga.dev)"
	@echo "  make run            -> start vLLM + DFlash server (requires Docker, NVIDIA toolkit, Doppler login)"
	@echo "                         Doppler must have CLOUDFLARE_API_TOKEN + CLOUDFLARE_ACCOUNT_ID"
	@echo "                         Reuses booting/healthy/stopped containers. Auto-O2 when compile cache warm + exclusive GPU"
	@echo "                         VLLM_PRODUCTION=1 for max throughput. VLLM_OPTIMIZATION_LEVEL=0 for fastest boot"
	@echo "                         VLLM_FORCE_RESTART=1 or VLLM_REMOVE_CONTAINER=1 to recreate container on stop"
	@echo "                         VLLM_PULL=always to force image pull. VLLM_ALLOW_GPU_SHARING=1 to share GPU with LM Studio"
	@echo "  make kill           -> stop the llm server started by make run"
	@echo "  make logs-vllm      -> tail vLLM Docker container logs (make run)"
	@echo "  make configure-always-on -> disable suspend/hibernate (server-like uptime)"
	@echo "  make monitor            -> real-time system metrics (Ctrl+C to exit)"
	@echo ""
	@echo "Overrides:"
	@echo "  SPEC=<path> STATE=<path> make plan"
	@echo "  REMOTE_USER=<user> REMOTE_HOST=<host> make ssh-target"
	@echo "  COMMIT_MSG='message' make push"
	@echo "  DOPPLER_PROJECT=<project> DOPPLER_CONFIG=<config> make doppler-seed-github-secrets"
	@echo "  GITHUB_REPO=<owner/repo> make doppler-seed-github-secrets"

venv:
	@test -d "$(VENV)" || python3 -m venv "$(VENV)"

install: venv
	@"$(PYTHON)" -m pip install --upgrade pip
	@"$(PIP)" install -e ".[dev]"

ensure-system-deps:
	@set -euo pipefail; \
	mkdir -p "$(LOCAL_BIN)"; \
	if ! command -v rg >/dev/null; then \
		echo "Installing ripgrep (rg)..."; \
		if command -v apt-get >/dev/null; then \
			sudo apt-get update && sudo apt-get install -y ripgrep; \
		elif command -v brew >/dev/null; then \
			brew install ripgrep; \
		else \
			echo "No supported package manager found to install ripgrep."; \
			exit 1; \
		fi; \
	fi; \
	if ! command -v cloudflared >/dev/null; then \
		echo "Installing cloudflared to $(LOCAL_BIN)..."; \
		arch="$$(uname -m)"; \
		case "$$arch" in \
			x86_64) cf_arch="amd64" ;; \
			aarch64|arm64) cf_arch="arm64" ;; \
			armv7l) cf_arch="arm" ;; \
			i386|i686) cf_arch="386" ;; \
			*) echo "Unsupported architecture for cloudflared: $$arch"; exit 1 ;; \
		esac; \
		curl -fsSL "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-$$cf_arch" -o "$(LOCAL_BIN)/cloudflared"; \
		chmod +x "$(LOCAL_BIN)/cloudflared"; \
	fi; \
	if ! command -v doppler >/dev/null; then \
		echo "Installing Doppler CLI to $(LOCAL_BIN)..."; \
		arch="$$(uname -m)"; \
		case "$$arch" in \
			x86_64) dop_arch="amd64" ;; \
			aarch64|arm64) dop_arch="arm64" ;; \
			armv7l) dop_arch="armv7" ;; \
			armv6l) dop_arch="armv6" ;; \
			i386|i686) dop_arch="i386" ;; \
			*) echo "Unsupported architecture for Doppler CLI: $$arch"; exit 1 ;; \
		esac; \
		version="$$(python3 -c 'import json,urllib.request; print(json.load(urllib.request.urlopen("https://api.github.com/repos/DopplerHQ/cli/releases/latest"))["tag_name"].lstrip("v"))')"; \
		tmp_dir="$$(mktemp -d)"; \
		curl -fsSL "https://github.com/DopplerHQ/cli/releases/download/$$version/doppler_$${version}_linux_$${dop_arch}.tar.gz" -o "$$tmp_dir/doppler.tar.gz"; \
		tar -xzf "$$tmp_dir/doppler.tar.gz" -C "$$tmp_dir"; \
		install -m 0755 "$$tmp_dir/doppler" "$(LOCAL_BIN)/doppler"; \
		rm -rf "$$tmp_dir"; \
	fi; \
	if ! command -v aichat >/dev/null; then \
		echo "Installing aichat to $(LOCAL_BIN)..."; \
		arch="$$(uname -m)"; \
		case "$$arch" in \
			x86_64) aichat_arch="x86_64-unknown-linux-musl" ;; \
			aarch64|arm64) aichat_arch="aarch64-unknown-linux-musl" ;; \
			*) echo "Unsupported architecture for aichat: $$arch"; exit 1 ;; \
		esac; \
		version="$$(python3 -c 'import json,urllib.request; print(json.load(urllib.request.urlopen("https://api.github.com/repos/sigoden/aichat/releases/latest"))["tag_name"].lstrip("v"))')"; \
		tmp_dir="$$(mktemp -d)"; \
		curl -fsSL "https://github.com/sigoden/aichat/releases/download/v$$version/aichat-v$${version}-$${aichat_arch}.tar.gz" -o "$$tmp_dir/aichat.tar.gz"; \
		tar -xzf "$$tmp_dir/aichat.tar.gz" -C "$$tmp_dir"; \
		install -m 0755 "$$tmp_dir/aichat" "$(LOCAL_BIN)/aichat"; \
		rm -rf "$$tmp_dir"; \
	fi; \
	echo "System dependencies ensured."

doctor:
	@echo "Checking required binaries..."
	@for cmd in python3 curl rg doppler cloudflared aichat; do \
		command -v "$$cmd" >/dev/null || { echo "Missing: $$cmd"; exit 1; }; \
		echo "  - $$cmd: OK"; \
	done
	@if [[ "$$(uname)" == "Linux" ]]; then \
		if ! command -v systemctl >/dev/null; then \
			echo "Missing: systemctl (required on Linux)"; \
			exit 1; \
		fi; \
		echo "  - systemctl: OK"; \
	else \
		echo "  - systemctl: SKIPPED (not on Linux)"; \
	fi
	@echo "Doctor checks completed."

setup: ensure-system-deps install doctor

check: test

test: install
	@"$(VENV)/bin/pytest" -q

doppler-seed-github-secrets:
	@set -euo pipefail; \
	command -v gh >/dev/null || { echo "Missing: gh (https://cli.github.com)"; exit 1; }; \
	command -v doppler >/dev/null || { echo "Missing: doppler"; exit 1; }; \
	repo_flag=""; \
	if [ -n "$(GITHUB_REPO)" ]; then \
		repo_flag="--repo $(GITHUB_REPO)"; \
	fi; \
	if [ -n "$${DOPPLER_SERVICE_TOKEN:-}" ]; then \
		token="$$DOPPLER_SERVICE_TOKEN"; \
		echo "Using DOPPLER_SERVICE_TOKEN from environment."; \
	else \
		echo "Creating Doppler service token for $(DOPPLER_PROJECT)/$(DOPPLER_CONFIG)..."; \
		token="$$(doppler configs tokens create github-actions \
			--project "$(DOPPLER_PROJECT)" \
			--config "$(DOPPLER_CONFIG)" \
			--plain)"; \
	fi; \
	printf '%s' "$$token" | gh secret set DOPPLER_SERVICE_TOKEN $$repo_flag; \
	echo "Seeded DOPPLER_SERVICE_TOKEN to GitHub secrets."

plan: install
	@"$(LLM_ENV)" --spec "$(SPEC)" --state "$(STATE)" plan

apply: install
	@"$(LLM_ENV)" --spec "$(SPEC)" --state "$(STATE)" apply

apply-auto: install
	@"$(LLM_ENV)" --spec "$(SPEC)" --state "$(STATE)" apply --auto-approve

status: install
	@"$(LLM_ENV)" --state "$(STATE)" status

destroy: install
	@"$(LLM_ENV)" --spec "$(SPEC)" --state "$(STATE)" destroy

destroy-auto: install
	@"$(LLM_ENV)" --spec "$(SPEC)" --state "$(STATE)" destroy --auto-approve

start:
	@systemctl --user daemon-reload
	@for svc in $(SERVICES); do \
		echo "Starting $$svc"; \
		systemctl --user start "$$svc"; \
	done

stop:
	@for svc in $(SERVICES); do \
		echo "Stopping $$svc"; \
		systemctl --user stop "$$svc" || true; \
	done

restart:
	@systemctl --user daemon-reload
	@for svc in $(SERVICES); do \
		echo "Restarting $$svc"; \
		systemctl --user restart "$$svc"; \
	done

service-status:
	@for svc in $(SERVICES); do \
		echo "===== $$svc ====="; \
		systemctl --user --no-pager --full status "$$svc" || true; \
	done

logs:
	@journalctl --user -f -u "$(CLOUDFLARED_SERVICE)"

logs-cloudflared:
	@journalctl --user -f -u "$(CLOUDFLARED_SERVICE)"

shell: install
	@bash -lc "source \"$(VENV)/bin/activate\" && exec bash"

clean-venv:
	@rm -rf "$(VENV)"
	@echo "Removed $(VENV)"

ssh-target:
	@test -n "$(REMOTE_USER)" && test -n "$(REMOTE_HOST)" || { \
		echo "Missing REMOTE_USER/REMOTE_HOST. Set them or update $(REMOTE_ACCESS_MD)."; \
		exit 1; \
	}
	@ssh "$(REMOTE_USER)@$(REMOTE_HOST)"

target-tmux:
	@test -n "$(REMOTE_USER)" && test -n "$(REMOTE_HOST)" || { \
		echo "Missing REMOTE_USER/REMOTE_HOST. Set them or update $(REMOTE_ACCESS_MD)."; \
		exit 1; \
	}
	@ssh -t "$(REMOTE_USER)@$(REMOTE_HOST)" 'tmux new -A -s work'

pull:
	@set -euo pipefail; \
	branch="$$(git branch --show-current)"; \
	if [ -z "$$branch" ]; then \
		echo "Not on a branch (detached HEAD)."; \
		exit 1; \
	fi; \
	stashed=false; \
	if ! git diff --quiet || ! git diff --cached --quiet || [ -n "$$(git ls-files --others --exclude-standard)" ]; then \
		echo "Stashing local changes before pull..."; \
		git stash push -u -m "make pull ($$(date -u +%Y-%m-%dT%H:%M:%SZ))"; \
		stashed=true; \
	fi; \
	git pull --ff-only origin "$$branch"; \
	if [ "$$stashed" = true ]; then \
		echo "Restoring stashed changes..."; \
		if git stash pop; then \
			echo "Pull complete (stash restored)."; \
		else \
			echo "Pull complete, but stash pop had conflicts. Run: git stash list && git stash pop"; \
			exit 1; \
		fi; \
	else \
		echo "Pull complete."; \
	fi

push:
	@set -euo pipefail; \
	branch="$$(git branch --show-current)"; \
	if [ -z "$$branch" ]; then \
		echo "Not on a branch (detached HEAD)."; \
		exit 1; \
	fi; \
	has_changes=false; \
	if ! git diff --quiet || ! git diff --cached --quiet; then has_changes=true; fi; \
	if [ -n "$$(git ls-files --others --exclude-standard)" ]; then has_changes=true; fi; \
	if [ "$$has_changes" = true ]; then \
		if [ -z "$(COMMIT_MSG)" ]; then \
			echo "Changes detected. Set COMMIT_MSG, e.g. COMMIT_MSG='fix tunnel apply' make push"; \
			exit 1; \
		fi; \
		git add -A; \
		git commit -m "$(COMMIT_MSG)"; \
	else \
		echo "No local changes to commit."; \
	fi; \
	if git rev-parse --abbrev-ref --symbolic-full-name '@{u}' >/dev/null 2>&1; then \
		git push; \
	else \
		git push -u origin "$$branch"; \
	fi

gh:
	@git remote get-url origin | sed 's/.*github.com[:\/]//' | sed 's/\.git$$//' | xargs -I {} open "https://github.com/{}"

setup-tunnel:
	@set -euo pipefail; \
	command -v cloudflared >/dev/null || { echo "cloudflared not found. Run: make ensure-system-deps"; exit 1; }; \
	bash "$(CURDIR)/scripts/setup-tunnel.sh"

setup-vllm-tunnel:
	@set -euo pipefail; \
	command -v python3 >/dev/null || { echo "Missing: python3"; exit 1; }; \
	bash "$(CURDIR)/scripts/setup-vllm-tunnel.sh"

run:
	@set -euo pipefail; \
	command -v python3 >/dev/null || { echo "Missing: python3"; exit 1; }; \
	command -v docker >/dev/null || { echo "Missing: docker"; exit 1; }; \
	echo "Starting vLLM + DFlash server..."; \
	PYTHONUNBUFFERED=1 python3 "$(CURDIR)/server/server.py"

configure-always-on:
	@sudo bash "$(CURDIR)/scripts/configure-always-on.sh"

monitor:
	@bash "$(CURDIR)/scripts/monitor.sh"

logs-vllm:
	@set -euo pipefail; \
	docker_cmd="docker"; \
	if ! docker info >/dev/null 2>&1; then docker_cmd="sudo docker"; fi; \
	if ! $$docker_cmd ps -a --format '{{.Names}}' 2>/dev/null | grep -qx "$(VLLM_CONTAINER)"; then \
		echo "Container $(VLLM_CONTAINER) not found. Run: make run"; \
		exit 1; \
	fi; \
	$$docker_cmd logs -f "$(VLLM_CONTAINER)"

kill:
	@set -euo pipefail; \
	server_pattern='python3 .*/server/server\.py'; \
	if pgrep -f "$$server_pattern" >/dev/null 2>&1; then \
		echo "Stopping llm server (server/server.py)..."; \
		pkill -TERM -f "$$server_pattern" || true; \
		for _ in $$(seq 1 10); do \
			pgrep -f "$$server_pattern" >/dev/null 2>&1 || break; \
			sleep 1; \
		done; \
	fi; \
	echo "Stopping vLLM + tunnel..."; \
	python3 "$(CURDIR)/server/server.py" --stop

