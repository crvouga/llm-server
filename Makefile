SHELL := /usr/bin/env bash

VENV ?= $(CURDIR)/.venv
VLLM_CONTAINER ?= atlas
COMMIT_MSG ?=
REMOTE_ACCESS_MD ?= remote-access/REMOTE-ACCESS.md
REMOTE_USER ?=
REMOTE_HOST ?=

.PHONY: help server-start server-stop server-free server-metrics server-clear-compile-cache server-tune server-install server-check run start stop kill logs status ssh \
	lm-studio-tunnel lm-studio-stop \
	proxy-install proxy-dev proxy-check proxy-deploy proxy-db bench \
	remote-setup-mac remote-verify pull push gh

help:
	@echo "Server (Atlas engine by default; ENGINE=vllm for the legacy vLLM+DFlash path):"
	@echo "  make server-start  -> start LLM server (python3 server/server.py)"
	@echo "                         ENGINE=vllm to use the vLLM+DFlash fallback"
	@echo "                         ATLAS_MAX_SEQ_LEN / ATLAS_KV_CACHE_DTYPE / ATLAS_NUM_DRAFTS to tune Atlas"
	@echo "  make server-stop       -> stop tunnel + launcher + engine container"
	@echo "  make server-free -> reclaim RAM/GPU before starting (./server/free.sh)"
	@echo "  make server-metrics -> CPU/RAM/GPU/disk + LLM health snapshot"
	@echo "                         METRICS_ARGS='--json' or '--watch 5' for options"
	@echo "  make server-tune -> sweep Atlas KV dtype x num-drafts x context, report decode tok/s"
	@echo "                         TUNE_ARGS='--quick' for a faster sweep"
	@echo "  make server-clear-compile-cache -> wipe torch/Triton cache (vLLM only)"
	@echo "  make server-install -> create .venv + install ruff, pyright, pytest (dev deps)"
	@echo "  make server-check  -> lint + typecheck server code (ruff + pyright)"
	@echo "  make logs          -> tail engine Docker container logs"
	@echo "  make status        -> check server process + container"
	@echo ""
	@echo "LM Studio tunnel:"
	@echo "  make lm-studio-tunnel -> tunnel LM Studio :1234 to llm.chrisvouga.dev"
	@echo "  make lm-studio-stop   -> stop tunnel only (LM Studio keeps running)"
	@echo ""
	@echo "Proxy (Cloudflare Worker):"
	@echo "  make proxy-install -> bun install in proxy/"
	@echo "  make proxy-dev     -> wrangler dev"
	@echo "  make proxy-check   -> type-check proxy"
	@echo "  make proxy-deploy  -> deploy worker ( requires Doppler)"
	@echo "  make proxy-db      -> run database migrations"
	@echo "  make bench         -> benchmark llm-proxy (model + tokens/sec)"
	@echo "                         BENCH_ARGS='--json' or BENCH_RUNS=3 for options"
	@echo ""
	@echo "Remote access (Mac controls Linux):"
	@echo "  make ssh              -> SSH into Linux target (from REMOTE-ACCESS.md)"
	@echo "  make remote-setup-mac -> ./remote-access/setup-controller.sh"
	@echo "  make remote-verify    -> connectivity checks only"
	@echo "  (on Linux target: sudo ./remote-access/setup-target.sh)"
	@echo ""
	@echo "Repo:"
	@echo "  make pull          -> git pull (auto-stash local changes)"
	@echo "  make push          -> git add, commit (COMMIT_MSG=...), push"
	@echo "  make gh            -> open GitHub repo in browser"

server-start run start:
	@set -euo pipefail; \
	command -v python3 >/dev/null || { echo "Missing: python3"; exit 1; }; \
	command -v docker >/dev/null || { echo "Missing: docker"; exit 1; }; \
	echo "Starting vLLM + DFlash server..."; \
	PYTHONUNBUFFERED=1 python3 "$(CURDIR)/server/server.py"

server-stop stop kill:
	@set -euo pipefail; \
	server_pattern='python3 .*/server/server\.py'; \
	launcher_pids=$$(pgrep -f "$$server_pattern" 2>/dev/null || true); \
	if [ -n "$$launcher_pids" ]; then \
		echo "Stopping llm server launcher..."; \
		for pid in $$launcher_pids; do \
			cmd=$$(tr '\0' ' ' < "/proc/$$pid/cmdline" 2>/dev/null || true); \
			case "$$cmd" in \
				*"server/server.py --"*) continue ;; \
			esac; \
			kill -TERM "$$pid" 2>/dev/null || true; \
		done; \
		for _ in $$(seq 1 10); do \
			still_running=false; \
			for pid in $$(pgrep -f "$$server_pattern" 2>/dev/null || true); do \
				cmd=$$(tr '\0' ' ' < "/proc/$$pid/cmdline" 2>/dev/null || true); \
				case "$$cmd" in \
					*"server/server.py --"*) continue ;; \
				esac; \
				still_running=true; \
				break; \
			done; \
			[ "$$still_running" = false ] && break; \
			sleep 1; \
		done; \
	fi; \
	echo "Stopping engine + tunnel..."; \
	python3 "$(CURDIR)/server/server.py" --stop

server-free:
	@set -euo pipefail; \
	"$(CURDIR)/server/free.sh" $(FREE_RAM_ARGS)

server-metrics:
	@set -euo pipefail; \
	"$(CURDIR)/server/metrics.sh" $(METRICS_ARGS)

server-tune:
	@set -euo pipefail; \
	"$(CURDIR)/server/tune.sh" $(TUNE_ARGS)

server-clear-compile-cache:
	@set -euo pipefail; \
	python3 "$(CURDIR)/server/server.py" --clear-compile-cache

lm-studio-tunnel:
	@set -euo pipefail; \
	command -v python3 >/dev/null || { echo "Missing: python3"; exit 1; }; \
	echo "Starting LM Studio Cloudflare tunnel..."; \
	PYTHONUNBUFFERED=1 python3 "$(CURDIR)/lm-studio/tunnel"

lm-studio-stop:
	@set -euo pipefail; \
	python3 "$(CURDIR)/lm-studio/tunnel" --stop

server-install:
	@set -euo pipefail; \
	command -v python3 >/dev/null || { echo "Missing: python3"; exit 1; }; \
	if [ ! -d "$(VENV)" ]; then \
		echo "Creating virtual environment at $(VENV)..."; \
		python3 -m venv "$(VENV)"; \
	fi; \
	"$(VENV)/bin/pip" install -e ".[dev]"; \
	command -v pyenv >/dev/null && pyenv rehash || true

server-check:
	@set -euo pipefail; \
	if [ ! -x "$(VENV)/bin/ruff" ] || [ ! -x "$(VENV)/bin/pyright" ]; then \
		echo "Missing dev tools — run: make server-install"; \
		exit 1; \
	fi; \
	"$(VENV)/bin/ruff" check server lm-studio tests; \
	"$(VENV)/bin/pyright"

logs:
	@set -euo pipefail; \
	docker_cmd="docker"; \
	if [ -f "$(HOME)/.spark-serve/runtime.json" ]; then \
		docker_cmd="$$(python3 -c "import json; print(' '.join(json.load(open('$(HOME)/.spark-serve/runtime.json'))['docker_cmd']))")"; \
	elif ! docker info >/dev/null 2>&1; then docker_cmd="sudo docker"; fi; \
	if ! $$docker_cmd ps -a --format '{{.Names}}' 2>/dev/null | grep -qx "$(VLLM_CONTAINER)"; then \
		echo "Container $(VLLM_CONTAINER) not found. Run: make server-start"; \
		exit 1; \
	fi; \
	$$docker_cmd logs -f "$(VLLM_CONTAINER)"

status:
	@set -euo pipefail; \
	server_pattern='python3 .*/server/server\.py'; \
	if pgrep -f "$$server_pattern" >/dev/null 2>&1; then \
		echo "Server process: running"; \
	else \
		echo " server process: stopped"; \
	fi; \
	docker_cmd="docker"; \
	if [ -f "$(HOME)/.spark-serve/runtime.json" ]; then \
		docker_cmd="$$(python3 -c "import json; print(' '.join(json.load(open('$(HOME)/.spark-serve/runtime.json'))['docker_cmd']))")"; \
	elif ! docker info >/dev/null 2>&1; then docker_cmd="sudo docker"; fi; \
	if $$docker_cmd ps --format '{{.Names}}' 2>/dev/null | grep -qx "$(VLLM_CONTAINER)"; then \
		echo "Container $(VLLM_CONTAINER): running"; \
	elif $$docker_cmd ps -a --format '{{.Names}}' 2>/dev/null | grep -qx "$(VLLM_CONTAINER)"; then \
		echo "Container $(VLLM_CONTAINER): stopped"; \
	else \
		echo "Container $(VLLM_CONTAINER): not found"; \
	fi

proxy-install:
	@cd "$(CURDIR)/proxy" && bun install

proxy-dev:
	@cd "$(CURDIR)/proxy" && bun run dev

proxy-check:
	@cd "$(CURDIR)/proxy" && bun run check

proxy-deploy:
	@cd "$(CURDIR)/proxy" && doppler run -- wrangler deploy

proxy-db:
	@cd "$(CURDIR)/proxy" && doppler run -- bash database/setup.sh

bench:
	@set -euo pipefail; \
	"$(CURDIR)/proxy/bench.sh" $(BENCH_ARGS)

remote-setup-mac:
	@"$(CURDIR)/remote-access/setup-controller.sh"

remote-verify:
	@"$(CURDIR)/remote-access/setup-controller.sh" --verify-only

ssh:
	@set -euo pipefail; \
	user="$(REMOTE_USER)"; \
	host="$(REMOTE_HOST)"; \
	if [ -z "$$user" ]; then \
		user="$$(awk -F'|' '/^\|/ && index($$2, "Login user") { gsub(/^[ \t`]+|[ \t`]+$$/, "", $$3); print $$3; exit }' "$(CURDIR)/$(REMOTE_ACCESS_MD)" 2>/dev/null || true)"; \
	fi; \
	if [ -z "$$host" ]; then \
		host="$$(awk -F'|' '/^\|/ && index($$2, "Tailscale DNS name") { gsub(/^[ \t`]+|[ \t`]+$$/, "", $$3); print $$3; exit }' "$(CURDIR)/$(REMOTE_ACCESS_MD)" 2>/dev/null || true)"; \
	fi; \
	if [ -z "$$user" ] || [ -z "$$host" ]; then \
		echo "Missing REMOTE_USER/REMOTE_HOST. Set them or update $(REMOTE_ACCESS_MD)."; \
		exit 1; \
	fi; \
	exec ssh "$$user@$$host"

pull:
	@set -euo pipefail; \
	branch="$$(git branch --show-current)"; \
	if [ -z "$$branch" ]; then \
		echo "Not on a branch (detached HEAD)."; \
		exit 1; \
	fi; \
	stashed=false; \
	if ! git diff --quiet || ! git diff --cached -- || [ -n "$$(git ls-files --others --exclude-standa")"; then \
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
	if [ -n "$$(git ls-files --others --exclude-standa")"; then has_changes=true; fi; \
	if [ "$$has_changes" = true ]; then \
		if [ -z "$(COMMIT_MSG)" ]; then \
			echo "Changes detected. Set COMMIT_MSG, e.g. COMMIT_MSG='fix tunnel' make push"; \
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
