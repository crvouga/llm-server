#!/usr/bin/env bash
# bench.sh — benchmark OpenAI-compatible API throughput.
#
# Streaming mode (default) separates TTFT from true decode speed:
#   decode tok/s = 1 / median(inter-token latency), the number that actually
#   reflects single-stream generation rate (vs. end-to-end tok/s which folds in
#   prompt processing + TTFT and understates a fast engine).
#
# Usage:
#   ./proxy/bench.sh                              # stream against the public proxy
#   BENCH_URL=http://localhost:8888 ./proxy/bench.sh   # local engine (Atlas/vLLM)
#   BENCH_DEPTH=32000 ./proxy/bench.sh            # measure decode tok/s at ~32K context
#   BENCH_STREAM=0 ./proxy/bench.sh               # non-streaming end-to-end timing
#   ./proxy/bench.sh --json
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

BENCH_URL="${BENCH_URL:-https://llm-proxy.chrisvouga.dev}"
BENCH_MODEL="${BENCH_MODEL:-}"
BENCH_MAX_TOKENS="${BENCH_MAX_TOKENS:-512}"
BENCH_RUNS="${BENCH_RUNS:-3}"
BENCH_TIMEOUT="${BENCH_TIMEOUT:-600}"
BENCH_STREAM="${BENCH_STREAM:-1}"
BENCH_DEPTH="${BENCH_DEPTH:-0}"
BENCH_USER_AGENT="${BENCH_USER_AGENT:-llm-server-bench/2.0}"
JSON=false

usage() {
  cat <<EOF
Usage: $(basename "$0") [OPTIONS]

Benchmark the OpenAI-compatible API at BENCH_URL.

Streaming mode (default) reports TTFT and true decode tok/s (1 / median
inter-token latency). Non-streaming mode reports end-to-end tok/s.

Options:
  --json            Output JSON (for scripts)
  -h, --help        Show this help

Environment:
  BENCH_URL         Base URL (default: https://llm-proxy.chrisvouga.dev;
                    local: http://localhost:8888)
  BENCH_MODEL       Model id (default: first model from /v1/models)
  BENCH_MAX_TOKENS  Completion token cap per run (default: 512)
  BENCH_RUNS        Number of timed runs (default: 3)
  BENCH_STREAM      1 = streaming true-decode metrics, 0 = end-to-end (default: 1)
  BENCH_DEPTH       Prompt-depth padding in ~tokens to measure tok/s at real
                    context, not empty context (default: 0)
  BENCH_TIMEOUT     Request timeout in seconds (default: 600)
  BENCH_USER_AGENT  HTTP User-Agent header (default: llm-server-bench/2.0)
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

export BENCH_URL BENCH_MODEL BENCH_MAX_TOKENS BENCH_RUNS BENCH_TIMEOUT \
  BENCH_STREAM BENCH_DEPTH BENCH_USER_AGENT JSON

python3 - <<'PY'
import json
import os
import statistics
import sys
import time
import urllib.error
import urllib.request

BASE = os.environ["BENCH_URL"].rstrip("/")
MODEL_OVERRIDE = os.environ.get("BENCH_MODEL", "").strip()
MAX_TOKENS = int(os.environ.get("BENCH_MAX_TOKENS", "512"))
RUNS = max(1, int(os.environ.get("BENCH_RUNS", "3")))
TIMEOUT = float(os.environ.get("BENCH_TIMEOUT", "600"))
STREAM = os.environ.get("BENCH_STREAM", "1").lower() in ("1", "true", "yes")
DEPTH = max(0, int(os.environ.get("BENCH_DEPTH", "0")))
USER_AGENT = os.environ.get("BENCH_USER_AGENT", "llm-server-bench/2.0")
JSON_OUT = os.environ.get("JSON", "").lower() == "true"

QUESTION = (
    "Write a Python function that computes the nth Fibonacci number "
    "iteratively. Include a short docstring and a brief explanation "
    "of time and space complexity."
)


def build_prompt() -> str:
    if DEPTH <= 0:
        return QUESTION
    # Pad with realistic code-review-style filler so we measure decode tok/s at
    # real context depth. ~0.75 words per token is a reasonable rough ratio.
    filler_line = (
        "def process(record):  # legacy helper, do not change signature\n"
        "    return {k: v for k, v in record.items() if v is not None}\n"
    )
    approx_tokens_per_line = 24
    n_lines = max(1, DEPTH // approx_tokens_per_line)
    preamble = filler_line * n_lines
    return (
        "Here is a large codebase excerpt for context:\n\n"
        + preamble
        + "\n\nNow, ignoring the excerpt above, answer this:\n"
        + QUESTION
    )


PROMPT = build_prompt()


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


def bench_once_blocking(model: str) -> dict:
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
    response_model = payload.get("model") or model
    tps = (completion_tokens / elapsed) if elapsed > 0 else 0.0
    return {
        "model": str(response_model),
        "stream": False,
        "latency_s": elapsed,
        "ttft_s": None,
        "decode_tps": tps,
        "e2e_tps": tps,
        "completion_tokens": completion_tokens,
        "prompt_tokens": prompt_tokens,
        "total_tokens": total_tokens,
    }


def bench_once_stream(model: str) -> dict:
    body = {
        "model": model,
        "messages": [{"role": "user", "content": PROMPT}],
        "max_tokens": MAX_TOKENS,
        "temperature": 0.2,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    data = json.dumps(body).encode()
    headers = {
        "Accept": "text/event-stream",
        "Content-Type": "application/json",
        "User-Agent": USER_AGENT,
    }
    req = urllib.request.Request(
        f"{BASE}/v1/chat/completions", data=data, headers=headers, method="POST"
    )

    started = time.perf_counter()
    tok_times: list[float] = []
    first_tok = None
    response_model = model
    usage: dict = {}
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            for raw_line in resp:
                line = raw_line.decode(errors="replace").strip()
                if not line or not line.startswith("data:"):
                    continue
                payload_str = line[len("data:"):].strip()
                if payload_str == "[DONE]":
                    break
                try:
                    chunk = json.loads(payload_str)
                except json.JSONDecodeError:
                    continue
                if chunk.get("model"):
                    response_model = chunk["model"]
                if chunk.get("usage"):
                    usage = chunk["usage"]
                choices = chunk.get("choices") or []
                if not choices:
                    continue
                delta = choices[0].get("delta") or {}
                piece = delta.get("content")
                if piece:
                    now = time.perf_counter()
                    if first_tok is None:
                        first_tok = now
                    tok_times.append(now)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        raise RuntimeError(f"HTTP {exc.code} (stream): {detail[:300]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Request failed (stream): {exc.reason}") from exc

    end = time.perf_counter()
    if first_tok is None:
        raise RuntimeError("Stream produced no content tokens")

    ttft = first_tok - started
    inter = [t2 - t1 for t1, t2 in zip(tok_times, tok_times[1:])]
    median_inter = statistics.median(inter) if inter else 0.0
    decode_tps = (1.0 / median_inter) if median_inter > 0 else 0.0

    completion_tokens = int(usage.get("completion_tokens") or len(tok_times))
    prompt_tokens = int(usage.get("prompt_tokens") or 0)
    total_tokens = int(usage.get("total_tokens") or (prompt_tokens + completion_tokens))
    decode_window = end - first_tok
    e2e_tps = (completion_tokens / decode_window) if decode_window > 0 else 0.0

    return {
        "model": str(response_model),
        "stream": True,
        "latency_s": end - started,
        "ttft_s": ttft,
        "decode_tps": decode_tps,
        "e2e_tps": e2e_tps,
        "completion_tokens": completion_tokens,
        "prompt_tokens": prompt_tokens,
        "total_tokens": total_tokens,
    }


def bench_once(model: str) -> dict:
    return bench_once_stream(model) if STREAM else bench_once_blocking(model)


def main() -> int:
    try:
        model = resolve_model()
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    runs: list[dict] = []
    for _ in range(RUNS):
        try:
            runs.append(bench_once(model))
        except RuntimeError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        model = runs[-1]["model"]

    def avg(key: str) -> float:
        vals = [r[key] for r in runs if r.get(key) is not None]
        return (sum(vals) / len(vals)) if vals else 0.0

    last = runs[-1]
    result = {
        "url": BASE,
        "model": last["model"],
        "stream": STREAM,
        "runs": RUNS,
        "max_tokens": MAX_TOKENS,
        "depth_tokens": DEPTH,
        "latency_s": avg("latency_s"),
        "ttft_s": avg("ttft_s") if STREAM else None,
        "decode_tps": avg("decode_tps"),
        "e2e_tps": avg("e2e_tps"),
        "completion_tokens": last["completion_tokens"],
        "prompt_tokens": last["prompt_tokens"],
        "total_tokens": last["total_tokens"],
        "samples": runs,
    }

    if JSON_OUT:
        print(json.dumps(result, indent=2))
        return 0

    mode = "streaming (true decode)" if STREAM else "non-streaming (end-to-end)"
    print(f"Benchmark target: {BASE}")
    print(f"Mode: {mode}  |  runs: {RUNS}  |  max_tokens: {MAX_TOKENS}  |  depth: {DEPTH}")
    print("")
    if STREAM:
        print(f"{'Model':<28} {'Decode tok/s':>13} {'TTFT':>9} {'Compl':>7} {'Prompt':>8}")
        print(f"{'-' * 28} {'-' * 13} {'-' * 9} {'-' * 7} {'-' * 8}")
        print(
            f"{result['model']:<28} "
            f"{result['decode_tps']:>13.1f} "
            f"{result['ttft_s']:>8.2f}s "
            f"{result['completion_tokens']:>7} "
            f"{result['prompt_tokens']:>8}"
        )
        print("")
        print(
            f"decode tok/s = 1/median(inter-token); end-to-end decode tok/s = "
            f"{result['e2e_tps']:.1f}"
        )
    else:
        print(f"{'Model':<28} {'Tok/s':>10} {'Latency':>10} {'Compl':>7} {'Prompt':>8}")
        print(f"{'-' * 28} {'-' * 10} {'-' * 10} {'-' * 7} {'-' * 8}")
        print(
            f"{result['model']:<28} "
            f"{result['e2e_tps']:>10.1f} "
            f"{result['latency_s']:>9.2f}s "
            f"{result['completion_tokens']:>7} "
            f"{result['prompt_tokens']:>8}"
        )
    if RUNS > 1:
        print("")
        print(f"Averaged over {RUNS} runs.")
    return 0


raise SystemExit(main())
PY
