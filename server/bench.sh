#!/usr/bin/env bash
# bench.sh — benchmark OpenAI-compatible API throughput (model + tokens/sec).
#
# Usage:
#   ./server/bench.sh
#   BENCH_RUNS=3 BENCH_MAX_TOKENS=512 ./server/bench.sh
#   ./server/bench.sh --json
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

BENCH_URL="${BENCH_URL:-https://llm-proxy.chrisvouga.dev}"
BENCH_MODEL="${BENCH_MODEL:-}"
BENCH_MAX_TOKENS="${BENCH_MAX_TOKENS:-256}"
BENCH_RUNS="${BENCH_RUNS:-1}"
BENCH_TIMEOUT="${BENCH_TIMEOUT:-300}"
BENCH_USER_AGENT="${BENCH_USER_AGENT:-llm-server-bench/1.0}"
JSON=false

usage() {
  cat <<EOF
Usage: $(basename "$0") [OPTIONS]

Benchmark the OpenAI-compatible API at llm-proxy.chrisvouga.dev (or BENCH_URL).

Reports model name, completion tokens, latency, and tokens/sec.

Options:
  --json            Output JSON (for scripts)
  -h, --help        Show this help

Environment:
  BENCH_URL         Base URL (default: https://llm-proxy.chrisvouga.dev)
  BENCH_MODEL       Model id (default: first model from /v1/models)
  BENCH_MAX_TOKENS  Completion token cap per run (default: 256)
  BENCH_RUNS        Number of timed runs (default: 1)
  BENCH_TIMEOUT     Request timeout in seconds (default: 300)
  BENCH_USER_AGENT  HTTP User-Agent header (default: llm-server-bench/1.0)
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --json) JSON=true ;;
    -h|--help) usage; exit 0 ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
  shift
done

if ! command -v python3 >/dev/null; then
  echo "Missing: python3" >&2
  exit 1
fi
if ! command -v curl >/dev/null; then
  echo "Missing: curl" >&2
  exit 1
fi

export BENCH_URL BENCH_MODEL BENCH_MAX_TOKENS BENCH_RUNS BENCH_TIMEOUT BENCH_USER_AGENT JSON

python3 - <<'PY'
import json
import os
import sys
import time
import urllib.error
import urllib.request

BASE = os.environ["BENCH_URL"].rstrip("/")
MODEL_OVERRIDE = os.environ.get("BENCH_MODEL", "").strip()
MAX_TOKENS = int(os.environ.get("BENCH_MAX_TOKENS", "256"))
RUNS = max(1, int(os.environ.get("BENCH_RUNS", "1")))
TIMEOUT = float(os.environ.get("BENCH_TIMEOUT", "300"))
USER_AGENT = os.environ.get("BENCH_USER_AGENT", "llm-server-bench/1.0")
JSON_OUT = os.environ.get("JSON", "").lower() == "true"

PROMPT = (
    "Write a Python function that computes the nth Fibonacci number "
    "iteratively. Include a short docstring and a brief explanation "
    "of time and space complexity."
)


def http_json(method: str, path: str, body: dict | None = None) -> tuple[int, dict | list]:
    url = f"{BASE}{path}"
    data = None
    headers = {"Accept": "application/json", "User-Agent": USER_AGENT}
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            raw = resp.read().decode()
            return resp.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        try:
            parsed = json.loads(detail)
        except json.JSONDecodeError:
            parsed = {"error": detail or exc.reason}
        raise RuntimeError(f"HTTP {exc.code} {path}: {parsed}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Request failed {path}: {exc.reason}") from exc


def resolve_model() -> str:
    if MODEL_OVERRIDE:
        return MODEL_OVERRIDE
    _, payload = http_json("GET", "/v1/models")
    models = payload.get("data") if isinstance(payload, dict) else None
    if not models:
        raise RuntimeError(f"No models returned from {BASE}/v1/models")
    model_id = models[0].get("id")
    if not model_id:
        raise RuntimeError("Model list missing id field")
    return str(model_id)


def bench_once(model: str) -> dict:
    body = {
        "model": model,
        "messages": [{"role": "user", "content": PROMPT}],
        "max_tokens": MAX_TOKENS,
        "temperature": 0.2,
    }
    started = time.perf_counter()
    _, payload = http_json("POST", "/v1/chat/completions", body)
    elapsed = time.perf_counter() - started

    usage = payload.get("usage") or {}
    completion_tokens = int(usage.get("completion_tokens") or 0)
    prompt_tokens = int(usage.get("prompt_tokens") or 0)
    total_tokens = int(usage.get("total_tokens") or (prompt_tokens + completion_tokens))
    response_model = (
        payload.get("model")
        or (payload.get("choices") or [{}])[0].get("model")
        or model
    )

    tokens_per_sec = (completion_tokens / elapsed) if elapsed > 0 else 0.0
    return {
        "model": str(response_model),
        "latency_s": elapsed,
        "completion_tokens": completion_tokens,
        "prompt_tokens": prompt_tokens,
        "total_tokens": total_tokens,
        "tokens_per_sec": tokens_per_sec,
    }


def main() -> int:
    model = resolve_model()
    runs: list[dict] = []
    for run_idx in range(RUNS):
        try:
            runs.append(bench_once(model))
        except RuntimeError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        if run_idx + 1 < RUNS:
            model = runs[-1]["model"]

    avg_latency = sum(r["latency_s"] for r in runs) / len(runs)
    avg_tps = sum(r["tokens_per_sec"] for r in runs) / len(runs)
    last = runs[-1]
    result = {
        "url": BASE,
        "model": last["model"],
        "runs": RUNS,
        "max_tokens": MAX_TOKENS,
        "latency_s": avg_latency,
        "completion_tokens": last["completion_tokens"],
        "prompt_tokens": last["prompt_tokens"],
        "total_tokens": last["total_tokens"],
        "tokens_per_sec": avg_tps,
        "samples": runs,
    }

    if JSON_OUT:
        print(json.dumps(result, indent=2))
        return 0

    print(f"Benchmark target: {BASE}")
    print("")
    print(f"{'Model':<24} {'Tokens/s':>10} {'Latency':>10} {'Completion':>12} {'Prompt':>8}")
    print(f"{'-' * 24} {'-' * 10} {'-' * 10} {'-' * 12} {'-' * 8}")
    print(
        f"{result['model']:<24} "
        f"{result['tokens_per_sec']:>10.1f} "
        f"{result['latency_s']:>9.2f}s "
        f"{result['completion_tokens']:>12} "
        f"{result['prompt_tokens']:>8}"
    )
    if RUNS > 1:
        print("")
        print(f"Averaged over {RUNS} runs.")
    return 0


raise SystemExit(main())
PY
