SHELL := /usr/bin/env bash

VENV ?= .venv
LOCAL_BIN ?= $(HOME)/.local/bin
export PATH := $(LOCAL_BIN):$(PATH)

PYTHON := $(VENV)/bin/python3
PIP := $(VENV)/bin/pip
LLM_ENV := $(VENV)/bin/local-llm-env

SPEC ?= spec/local-llm-env.yaml
STATE ?= state/local-llm-env-state.json

LMSTUDIO_SERVICE ?= local-llm-lmstudio.service
CLOUDFLARED_SERVICE ?= local-llm-cloudflared.service
SERVICES := $(LMSTUDIO_SERVICE) $(CLOUDFLARED_SERVICE)

.PHONY: help venv install setup doctor ensure-system-deps plan apply apply-auto status destroy destroy-auto \
	start stop restart logs logs-lmstudio logs-cloudflared \
	service-status shell clean-venv

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
	@echo ""
	@echo "Overrides:"
	@echo "  SPEC=<path> STATE=<path> make plan"

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
	echo "System dependencies ensured."

doctor:
	@echo "Checking required binaries..."
	@for cmd in python3 systemctl curl rg doppler cloudflared; do \
		command -v "$$cmd" >/dev/null || { echo "Missing: $$cmd"; exit 1; }; \
		echo "  - $$cmd: OK"; \
	done
	@echo "Doctor checks completed."

setup: ensure-system-deps install doctor

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
	@journalctl --user -f -u "$(LMSTUDIO_SERVICE)" -u "$(CLOUDFLARED_SERVICE)"

logs-lmstudio:
	@journalctl --user -f -u "$(LMSTUDIO_SERVICE)"

logs-cloudflared:
	@journalctl --user -f -u "$(CLOUDFLARED_SERVICE)"

shell: install
	@bash -lc "source \"$(VENV)/bin/activate\" && exec bash"

clean-venv:
	@rm -rf "$(VENV)"
	@echo "Removed $(VENV)"

