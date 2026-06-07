#!/usr/bin/env bash
# tune.sh — Atlas single-stream tuning sweep for the GB10 box.
#
# Sweeps KV-cache dtype x MTP num-drafts x context window. For each combo it
# launches a throwaway Atlas container on a test port (does NOT touch the live
# `atlas` container or the Cloudflare tunnel), runs the streaming bench at a
# short prompt and a deep prompt, and records true decode tok/s. It then prints
# a ranked table and recommends the winning combo to bake into Config defaults.
#
# Usage:
#   ./server/tune.sh                 # full sweep
#   ./server/tune.sh --quick         # fast sweep (fewer combos)
#   TUNE_KV="fp8 turbo4" TUNE_DRAFTS="2 3" ./server/tune.sh
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
BENCH="${ROOT_DIR}/proxy/bench.sh"

IMAGE="${ATLAS_IMAGE:-avarok/atlas-gb10:latest}"
MODEL="${ATLAS_MODEL:-Qwen/Qwen3.6-35B-A3B-FP8}"
TUNE_CONTAINER="${TUNE_CONTAINER:-atlas-tune}"
TUNE_PORT="${TUNE_PORT:-8899}"
GPU_MEM_UTIL="${ATLAS_GPU_MEM_UTIL:-0.90}"
SCHED="${ATLAS_SCHEDULING_POLICY:-slai}"
TOOL_PARSER="${ATLAS_TOOL_CALL_PARSER:-qwen3_coder}"
READY_TIMEOUT="${TUNE_READY_TIMEOUT:-2400}"
BENCH_MAX_TOKENS="${TUNE_MAX_TOKENS:-256}"
BENCH_RUNS="${TUNE_RUNS:-2}"
HF_CACHE="${HF_CACHE:-${HOME}/.cache/huggingface}"

# Sweep grids (space-separated). Override via env.
TUNE_KV="${TUNE_KV:-fp8 nvfp4 turbo4}"
TUNE_DRAFTS="${TUNE_DRAFTS:-2 3}"
TUNE_CTX="${TUNE_CTX:-65536 131072}"
TUNE_DEPTHS="${TUNE_DEPTHS:-0 32000}"

QUICK=false

usage() {
  cat <<EOF
Usage: $(basename "$0") [--quick] [-h]

Atlas tuning sweep: KV dtype x num-drafts x context -> true decode tok/s.

Options:
  --quick     Smaller grid (TUNE_KV="fp8 turbo4", TUNE_DRAFTS="2", TUNE_CTX="65536", depths "0")
  -h, --help  Show this help

Environment:
  ATLAS_IMAGE / ATLAS_MODEL   Image + model id
  TUNE_KV / TUNE_DRAFTS / TUNE_CTX / TUNE_DEPTHS   Sweep grids
  TUNE_PORT (8899)            Test port for the throwaway container
  TUNE_MAX_TOKENS (256) / TUNE_RUNS (2)            Bench params
  HF_TOKEN                    HF token (else pulled from Doppler if available)
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --quick) QUICK=true ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 1 ;;
  esac
  shift
done

if $QUICK; then
  TUNE_KV="${TUNE_KV_QUICK:-fp8 turbo4}"
  TUNE_DRAFTS="${TUNE_DRAFTS_QUICK:-2}"
  TUNE_CTX="${TUNE_CTX_QUICK:-65536}"
  TUNE_DEPTHS="${TUNE_DEPTHS_QUICK:-0}"
fi

for bin in docker python3 curl; do
  command -v "$bin" >/dev/null || { echo "Missing: $bin" >&2; exit 1; }
done

# Resolve HF token (env first, then Doppler if present).
HF_TOKEN="${HF_TOKEN:-${HUGGING_FACE_HUB_TOKEN:-}}"
if [[ -z "${HF_TOKEN}" ]] && command -v doppler >/dev/null; then
  HF_TOKEN="$(doppler secrets get HF_TOKEN --plain 2>/dev/null || true)"
fi

GPU_FLAGS=(--runtime nvidia -e NVIDIA_VISIBLE_DEVICES=all -e NVIDIA_DRIVER_CAPABILITIES=compute,utility)

RESULTS_FILE="$(mktemp -t atlas-tune.XXXXXX)"
trap 'docker rm -f "${TUNE_CONTAINER}" >/dev/null 2>&1 || true; rm -f "${RESULTS_FILE}"' EXIT

mkdir -p "${HF_CACHE}"

wait_ready() {
  local elapsed=0 interval=5
  while (( elapsed < READY_TIMEOUT )); do
    local status
    status="$(docker inspect -f '{{.State.Status}}' "${TUNE_CONTAINER}" 2>/dev/null || echo missing)"
    if [[ "${status}" != "running" ]]; then
      echo "  container ${status} — recent logs:" >&2
      docker logs --tail 30 "${TUNE_CONTAINER}" 2>&1 | sed 's/^/    /' >&2 || true
      return 1
    fi
    if curl -sf "http://127.0.0.1:${TUNE_PORT}/v1/models" >/dev/null 2>&1; then
      return 0
    fi
    sleep "${interval}"
    elapsed=$(( elapsed + interval ))
  done
  return 1
}

# MTP acceptance, if Atlas surfaces it in logs (best-effort; N/A otherwise).
mtp_acceptance() {
  docker logs "${TUNE_CONTAINER}" 2>&1 \
    | grep -oiE 'accept(ance)?[ _-]?(rate|ratio)?[ :=]+[0-9.]+%?' \
    | tail -1 \
    | grep -oE '[0-9.]+%?' \
    | tail -1 || true
}

run_combo() {
  local kv="$1" drafts="$2" ctx="$3"
  echo ""
  echo "=== KV=${kv}  drafts=${drafts}  ctx=${ctx} ==="
  docker rm -f "${TUNE_CONTAINER}" >/dev/null 2>&1 || true

  local args=(
    serve "${MODEL}"
    --port "${TUNE_PORT}"
    --max-seq-len "${ctx}"
    --kv-cache-dtype "${kv}"
    --gpu-memory-utilization "${GPU_MEM_UTIL}"
    --scheduling-policy "${SCHED}"
    --tool-call-parser "${TOOL_PARSER}"
    --enable-prefix-caching
    --speculative --num-drafts "${drafts}"
  )
  if [[ "${kv}" != "bf16" ]]; then
    args+=(--kv-high-precision-layers auto)
  fi

  docker run -d --name "${TUNE_CONTAINER}" \
    "${GPU_FLAGS[@]}" \
    --network host --ipc host --ulimit memlock=-1:-1 \
    -v "${HF_CACHE}:/root/.cache/huggingface" \
    -e "HF_TOKEN=${HF_TOKEN}" -e "HUGGING_FACE_HUB_TOKEN=${HF_TOKEN}" \
    "${IMAGE}" "${args[@]}" >/dev/null

  echo "  waiting for readiness (first run downloads the model)..."
  if ! wait_ready; then
    echo "  FAILED to become ready — skipping combo" >&2
    docker rm -f "${TUNE_CONTAINER}" >/dev/null 2>&1 || true
    return 0
  fi
  local accept; accept="$(mtp_acceptance)"; accept="${accept:-N/A}"

  local depth
  for depth in ${TUNE_DEPTHS}; do
    local out tps ttft
    out="$(BENCH_URL="http://127.0.0.1:${TUNE_PORT}" BENCH_MODEL=atlas \
      BENCH_STREAM=1 BENCH_DEPTH="${depth}" \
      BENCH_MAX_TOKENS="${BENCH_MAX_TOKENS}" BENCH_RUNS="${BENCH_RUNS}" \
      bash "${BENCH}" --json 2>/dev/null || echo '{}')"
    tps="$(printf '%s' "${out}" | python3 -c 'import sys,json;d=json.load(sys.stdin);print(f"{d.get(\"decode_tps\",0):.1f}")' 2>/dev/null || echo 0)"
    ttft="$(printf '%s' "${out}" | python3 -c 'import sys,json;d=json.load(sys.stdin);v=d.get("ttft_s");print(f"{v:.2f}" if v else "-")' 2>/dev/null || echo -)"
    printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
      "${kv}" "${drafts}" "${ctx}" "${depth}" "${tps}" "${ttft}" "${accept}" \
      >> "${RESULTS_FILE}"
    echo "  depth=${depth}: decode ${tps} tok/s  (TTFT ${ttft}s, MTP accept ${accept})"
  done

  docker rm -f "${TUNE_CONTAINER}" >/dev/null 2>&1 || true
}

echo "Atlas tuning sweep"
echo "  image:   ${IMAGE}"
echo "  model:   ${MODEL}"
echo "  KV:      ${TUNE_KV}"
echo "  drafts:  ${TUNE_DRAFTS}"
echo "  ctx:     ${TUNE_CTX}"
echo "  depths:  ${TUNE_DEPTHS}"
[[ -z "${HF_TOKEN}" ]] && echo "  WARN: no HF_TOKEN found (gated model pulls may fail)"

for kv in ${TUNE_KV}; do
  for drafts in ${TUNE_DRAFTS}; do
    for ctx in ${TUNE_CTX}; do
      run_combo "${kv}" "${drafts}" "${ctx}"
    done
  done
done

echo ""
echo "================ RANKED RESULTS (by decode tok/s) ================"
if [[ ! -s "${RESULTS_FILE}" ]]; then
  echo "No successful combos." >&2
  exit 1
fi

python3 - "${RESULTS_FILE}" <<'PY'
import sys

rows = []
with open(sys.argv[1]) as fh:
    for line in fh:
        parts = line.rstrip("\n").split("\t")
        if len(parts) != 7:
            continue
        kv, drafts, ctx, depth, tps, ttft, accept = parts
        try:
            tps_f = float(tps)
        except ValueError:
            tps_f = 0.0
        rows.append(
            {
                "kv": kv, "drafts": drafts, "ctx": ctx, "depth": depth,
                "tps": tps_f, "ttft": ttft, "accept": accept,
            }
        )

rows.sort(key=lambda r: r["tps"], reverse=True)

print(f"{'KV':<8} {'drafts':>6} {'ctx':>8} {'depth':>7} {'tok/s':>8} {'TTFT':>7} {'MTP%':>8}")
print(f"{'-'*8} {'-'*6} {'-'*8} {'-'*7} {'-'*8} {'-'*7} {'-'*8}")
for r in rows:
    print(
        f"{r['kv']:<8} {r['drafts']:>6} {r['ctx']:>8} {r['depth']:>7} "
        f"{r['tps']:>8.1f} {r['ttft']:>7} {r['accept']:>8}"
    )

# Recommend the winner: prefer the deepest depth tested (most realistic), else top overall.
if rows:
    depths = sorted({int(r["depth"]) for r in rows})
    deepest = str(max(depths))
    deep_rows = [r for r in rows if r["depth"] == deepest] or rows
    best = max(deep_rows, key=lambda r: r["tps"])
    print("")
    print(
        f"Recommended (at depth {deepest}): "
        f"ATLAS_KV_CACHE_DTYPE={best['kv']} ATLAS_NUM_DRAFTS={best['drafts']} "
        f"ATLAS_MAX_SEQ_LEN={best['ctx']}  ->  {best['tps']:.1f} tok/s"
    )
    print("Bake the winner into Config defaults in server/server.py.")
PY
