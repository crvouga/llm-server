SHELL := /usr/bin/env bash

VLLM_CONTAINER ?= vllm-qwen36-dflash
COMMIT_MSG ?=

.PHONY: help server-start server-stop run start stop kill logs status \
	proxy-install proxy-dev proxy-check proxy-deploy proxy-db \
	remote-setup-mac remote-verify pull push gh

help:
	@echo "Server (vLLM):"
	@echo "  make server-start  -> start LLM server (python3 server/server.py)"
	@echo "  make server-stop   -> stop LLM server"
	@echo "  make logs          -> tail vLLM Docker container logs"
	@echo "  make status        -> check server process + container"
	@echo ""
	@echo "Proxy (Cloudflare Worker):"
	@echo "  make proxy-install -> bun install in proxy/"
	@echo "  make proxy-dev     -> wrangler dev"
	@echo "  make proxy-check   -> type-check proxy"
	@echo "  make proxy-deploy  -> deploy worker (requires Doppler)"
	@echo "  make proxy-db      -> run database migrations"
	@echo ""
	@echo "Remote access (Mac controls Linux):"
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

logs:
	@set -euo pipefail; \
	docker_cmd="docker"; \
	if ! docker info >/dev/null 2>&1; then docker_cmd="sudo docker"; fi; \
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
		echo "Server process: stopped"; \
	fi; \
	docker_cmd="docker"; \
	if ! docker info >/dev/null 2>&1; then docker_cmd="sudo docker"; fi; \
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

remote-setup-mac:
	@"$(CURDIR)/remote-access/setup-controller.sh"

remote-verify:
	@"$(CURDIR)/remote-access/setup-controller.sh" --verify-only

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
