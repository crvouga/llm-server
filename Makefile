SHELL := /usr/bin/env bash

VENV ?= $(CURDIR)/.venv
ATLAS_CONTAINER ?= atlas
COMMIT_MSG ?=
REMOTE_ACCESS_MD ?= remote-access/REMOTE-ACCESS.md
REMOTE_USER ?=
REMOTE_HOST ?=
CHAT_URL ?= https://llm-proxy.chrisvouga.dev
CHAT_MODEL ?=
AICHAT_VERSION ?= v0.30.0
CHAT_BIN := $(CURDIR)/.chat/bin/aichat

.PHONY: help server-start server-stop server-metrics server-install server-check api-check server-test run start stop kill logs status ssh \
	lm-studio-tunnel lm-studio-stop \
	proxy-install proxy-dev proxy-check proxy-deploy proxy-db bench \
	chat chat-install \
	remote-setup-mac remote-verify pull push gh

help:
	@echo "Server (Atlas + Qwen3.6-35B-A3B-FP8):"
	@echo "  make server-start  -> start Atlas + tunnel (python3 server/server.py)"
	@echo "                         ATLAS_MAX_SEQ_LEN / ATLAS_KV_CACHE_DTYPE / ATLAS_NUM_DRAFTS to tune"
	@echo "  make server-stop       -> stop tunnel + launcher + Atlas container"
	@echo "  make server-metrics -> CPU/RAM/GPU/disk + Atlas health snapshot"
	@echo "                         METRICS_ARGS='--json' or '--watch 5' for options"
	@echo "  make server-install -> create .venv + install ruff, pyright, pytest (dev deps)"
	@echo "  make server-check  -> lint + typecheck server code (ruff + pyright)"
	@echo "  make api-check     -> smoke-test + benchmark OpenAI-compatible API"
	@echo "                         LLM_BASE_URL=... CHECK_ARGS='--json' for options"
	@echo "  make server-test   -> smoke tests only (alias for api-check --smoke-only)"
	@echo "  make bench         -> throughput benchmark only (alias for api-check --bench-only)"
	@echo "  make logs          -> tail Atlas Docker container logs"
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
	@echo ""
	@echo "Chat:"
	@echo "  make chat          -> interactive REPL against CHAT_URL (auto-installs aichat)"
	@echo "  make chat-install  -> download aichat binary to .chat/bin/ (Ubuntu/macOS)"
	@echo "                         CHAT_URL=... CHAT_MODEL=... to override defaults"
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
	echo "Starting Atlas server..."; \
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
	echo "Stopping Atlas + tunnel..."; \
	python3 "$(CURDIR)/server/server.py" --stop

server-metrics:
	@set -euo pipefail; \
	"$(CURDIR)/server/metrics.sh" $(METRICS_ARGS)

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
	"$(VENV)/bin/ruff" check server lm-studio server_test tests; \
	"$(VENV)/bin/pyright"

api-check:
	@set -euo pipefail; \
	command -v python3 >/dev/null || { echo "Missing: python3"; exit 1; }; \
	python3 -m pip install -q -r "$(CURDIR)/server_test/requirements.txt"; \
	python3 "$(CURDIR)/server_test/check_api.py" $(CHECK_ARGS)

server-test:
	@set -euo pipefail; \
	$(MAKE) api-check CHECK_ARGS="--smoke-only $(TEST_ARGS)"

bench:
	@set -euo pipefail; \
	$(MAKE) api-check CHECK_ARGS="--bench-only $(BENCH_ARGS)"

logs:
	@set -euo pipefail; \
	docker_cmd="docker"; \
	if [ -f "$(HOME)/.spark-serve/runtime.json" ]; then \
		docker_cmd="$$(python3 -c "import json; print(' '.join(json.load(open('$(HOME)/.spark-serve/runtime.json'))['docker_cmd']))")"; \
	elif ! docker info >/dev/null 2>&1; then docker_cmd="sudo docker"; fi; \
	if ! $$docker_cmd ps -a --format '{{.Names}}' 2>/dev/null | grep -qx "$(ATLAS_CONTAINER)"; then \
		echo "Container $(ATLAS_CONTAINER) not found. Run: make server-start"; \
		exit 1; \
	fi; \
	$$docker_cmd logs -f "$(ATLAS_CONTAINER)"

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
	if $$docker_cmd ps --format '{{.Names}}' 2>/dev/null | grep -qx "$(ATLAS_CONTAINER)"; then \
		echo "Container $(ATLAS_CONTAINER): running"; \
	elif $$docker_cmd ps -a --format '{{.Names}}' 2>/dev/null | grep -qx "$(ATLAS_CONTAINER)"; then \
		echo "Container $(ATLAS_CONTAINER): stopped"; \
	else \
		echo "Container $(ATLAS_CONTAINER): not found"; \
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

chat-install:
	@set -euo pipefail; \
	command -v curl >/dev/null || { echo "Missing: curl"; exit 1; }; \
	os="$$(uname -s)"; \
	arch="$$(uname -m)"; \
	case "$$os:$$arch" in \
		Darwin:arm64) target="aarch64-apple-darwin" ;; \
		Darwin:x86_64) target="x86_64-apple-darwin" ;; \
		Linux:x86_64) target="x86_64-unknown-linux-musl" ;; \
		Linux:aarch64|Linux:arm64) target="aarch64-unknown-linux-musl" ;; \
		*) \
			echo "Unsupported platform: $$os $$arch"; \
			echo "Install aichat manually: https://github.com/sigoden/aichat/releases"; \
			exit 1 ;; \
	esac; \
	version="$(AICHAT_VERSION)"; \
	url="https://github.com/sigoden/aichat/releases/download/$$version/aichat-$$version-$$target.tar.gz"; \
	tmpdir="$$(mktemp -d)"; \
	trap 'rm -rf "$$tmpdir"' EXIT; \
	echo "Downloading aichat $$version ($$target)..."; \
	curl -fsSL -o "$$tmpdir/aichat.tgz" "$$url"; \
	mkdir -p "$(CURDIR)/.chat/bin"; \
	tar -xzf "$$tmpdir/aichat.tgz" -C "$$tmpdir"; \
	if [ -f "$$tmpdir/aichat" ]; then \
		mv "$$tmpdir/aichat" "$(CHAT_BIN)"; \
	else \
		bin="$$(find "$$tmpdir" -maxdepth 2 -type f -name aichat | head -1)"; \
		[ -n "$$bin" ] || { echo "aichat binary not found in archive"; exit 1; }; \
		mv "$$bin" "$(CHAT_BIN)"; \
	fi; \
	chmod +x "$(CHAT_BIN)"; \
	echo "Installed: $(CHAT_BIN)"

chat:
	@set -euo pipefail; \
	command -v curl >/dev/null || { echo "Missing: curl"; exit 1; }; \
	command -v python3 >/dev/null || { echo "Missing: python3"; exit 1; }; \
	aichat_bin=""; \
	if [ -x "$(CHAT_BIN)" ]; then \
		aichat_bin="$(CHAT_BIN)"; \
	elif command -v aichat >/dev/null; then \
		aichat_bin="$$(command -v aichat)"; \
	else \
		"$(MAKE)" chat-install; \
		aichat_bin="$(CHAT_BIN)"; \
	fi; \
	chat_url="$(CHAT_URL)"; \
	chat_url="$${chat_url%/}"; \
	model="$(CHAT_MODEL)"; \
	if [ -z "$$model" ]; then \
		model="$$(curl -fsSL "$$chat_url/v1/models" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['data'][0]['id'])")"; \
	fi; \
	mkdir -p "$(CURDIR)/.chat"; \
	CHAT_DIR="$(CURDIR)/.chat" CHAT_URL="$$chat_url" CHAT_MODEL="$$model" python3 -c 'import os, pathlib; model=os.environ["CHAT_MODEL"]; url=os.environ["CHAT_URL"].rstrip("/"); p=pathlib.Path(os.environ["CHAT_DIR"])/"config.yaml"; p.write_text("model: llm-proxy:%s\nclients:\n  - type: openai-compatible\n    name: llm-proxy\n    api_base: %s/v1\n    api_key: sk-no-auth\n    models:\n      - name: %s\n" % (model, url, model))'; \
	exec env AICHAT_CONFIG_DIR="$(CURDIR)/.chat" "$$aichat_bin"

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
