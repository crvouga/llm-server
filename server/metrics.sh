#!/usr/bin/env bash
# metrics.sh — snapshot of CPU, RAM, GPU, disk, and LLM server health.
#
# Usage:
#   ./server/metrics.sh           # human-readable report
#   ./server/metrics.sh --json    # machine-readable JSON
#   ./server/metrics.sh --watch 5 # refresh every 5s (Ctrl+C to stop)
#
set -euo pipefail

JSON=false
WATCH_INTERVAL=""
ENGINE_CONTAINER="${ENGINE_CONTAINER:-${ATLAS_CONTAINER:-vllm}}"
ATLAS_CONTAINER="${ATLAS_CONTAINER:-$ENGINE_CONTAINER}"
ATLAS_PORT="${ATLAS_PORT:-8888}"
HEALTH_PATH="${HEALTH_PATH:-/v1/models}"
MODEL_CACHE="${MODEL_CACHE:-${HOME}/.cache/huggingface}"
HELPER_DIR="${HELPER_DIR:-${HOME}/.spark-serve}"

B=$'\033[1m'
D=$'\033[2m'
X=$'\033[0m'

usage() {
  cat <<EOF
Usage: $(basename "$0") [OPTIONS]

Print current system and LLM server metrics.

Options:
  --json            Output JSON (for scripts / dashboards)
  --watch SECONDS   Refresh continuously (default snapshot only)
  -h, --help        Show this help

Environment:
  ENGINE_CONTAINER  Docker container name (default: vllm)
  ATLAS_CONTAINER   Alias for ENGINE_CONTAINER (legacy)
  ATLAS_PORT        Server HTTP port (default: 8888)
  HEALTH_PATH       Health probe path (default: /v1/models)
  MODEL_CACHE       HF weights cache (default: ~/.cache/huggingface)
  HELPER_DIR        Runtime state dir (~/.spark-serve)
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --json) JSON=true ;;
    --watch)
      shift
      WATCH_INTERVAL="${1:-5}"
      ;;
    -h|--help) usage; exit 0 ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
  shift
done

status_word() {
  local code="$1"
  case "${code}" in
    200) echo "ok" ;;
    000) echo "down" ;;
    *) echo "http${code}" ;;
  esac
}

gib_short() {
  awk -v kib="$1" 'BEGIN {printf "%.0f", kib/1024/1024}'
}

compact_line() {
  printf '%s\n' "$*"
}

docker_cmd() {
  if docker info >/dev/null 2>&1; then
    echo "docker"
  elif sudo docker info >/dev/null 2>&1; then
    echo "sudo docker"
  else
    echo ""
  fi
}

cpu_usage_percent() {
  local u1 n1 s1 i1 iw1 irq1 sirq1 st1
  local u2 n2 s2 i2 iw2 irq2 sirq2 st2
  read -r u1 n1 s1 i1 iw1 irq1 sirq1 st1 <<< "$(awk '/^cpu / {print $2,$3,$4,$5,$6,$7,$8; exit}' /proc/stat)"
  sleep 0.25
  read -r u2 n2 s2 i2 iw2 irq2 sirq2 st2 <<< "$(awk '/^cpu / {print $2,$3,$4,$5,$6,$7,$8; exit}' /proc/stat)"
  local total1=$((u1 + n1 + s1 + i1 + iw1 + irq1 + sirq1 + st1))
  local total2=$((u2 + n2 + s2 + i2 + iw2 + irq2 + sirq2 + st2))
  local idle1=$((i1 + iw1))
  local idle2=$((i2 + iw2))
  local total_delta=$((total2 - total1))
  local idle_delta=$((idle2 - idle1))
  if [[ "${total_delta}" -le 0 ]]; then
    echo "0.0"
    return
  fi
  awk -v t="${total_delta}" -v i="${idle_delta}" 'BEGIN {printf "%.1f", (t - i) * 100 / t}'
}

mem_kib() {
  awk -v key="$1" '$1 == key ":" {print $2; exit}' /proc/meminfo
}

dir_size_human() {
  local path="$1"
  if [[ ! -d "${path}" ]]; then
    echo "missing"
    return
  fi
  timeout 3 du -sh "${path}" 2>/dev/null | awk '{print $1}' || echo ">(timeout)"
}

gpu_compute_used_mib() {
  nvidia-smi --query-compute-apps=used_gpu_memory --format=csv,noheader,nounits 2>/dev/null \
    | awk -F',' '{gsub(/ /,"",$1); if ($1 ~ /^[0-9]+$/) s+=$1} END {if (s>0) printf "%.0f", s}'
}

http_code() {
  local url="$1"
  local code
  code="$(curl -s -o /dev/null -w '%{http_code}' --connect-timeout 2 --max-time 3 "${url}" 2>/dev/null)"
  echo "${code:-000}"
}

collect_metrics() {
  local now host uptime_str load1 load5 load15 cores cpu_pct
  local mem_total mem_avail mem_free mem_used swap_total swap_free swap_used
  local gpu_name gpu_driver gpu_temp gpu_util gpu_mem_util gpu_power gpu_mem_used gpu_mem_total gpu_procs
  local disk_root_pct disk_root_avail disk_root_avail_gib model_cache_size
  local server_running server_pid container_status health_code models_code tunnel_running dc

  now="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
  host="$(hostname)"
  read -r load1 load5 load15 _ _ _ _ <<< "$(cat /proc/loadavg)"
  cores="$(nproc)"
  cpu_pct="$(cpu_usage_percent)"
  uptime_str="$(uptime -p 2>/dev/null || uptime | sed 's/.*up/up/')"

  mem_total="$(mem_kib MemTotal)"
  mem_avail="$(mem_kib MemAvailable)"
  mem_free="$(mem_kib MemFree)"
  mem_used=$((mem_total - mem_avail))
  swap_total="$(mem_kib SwapTotal)"
  swap_free="$(mem_kib SwapFree)"
  swap_used=$((swap_total - swap_free))

  dc="$(docker_cmd)"
  container_status="not found"
  if [[ -n "${dc}" ]]; then
    if ${dc} ps --format '{{.Names}}' 2>/dev/null | grep -qx "${ATLAS_CONTAINER}"; then
      container_status="running"
    elif ${dc} ps -a --format '{{.Names}}' 2>/dev/null | grep -qx "${ATLAS_CONTAINER}"; then
      container_status="stopped"
    fi
  else
    container_status="docker unavailable"
  fi

  gpu_name=""
  gpu_driver=""
  gpu_temp=""
  gpu_util=""
  gpu_mem_util=""
  gpu_power=""
  gpu_mem_used="N/A"
  gpu_mem_total="N/A"
  gpu_procs=""

  if command -v nvidia-smi >/dev/null 2>&1; then
    local gpu_csv
    gpu_csv="$(nvidia-smi --query-gpu=name,driver_version,temperature.gpu,utilization.gpu,utilization.memory,memory.used,memory.total,power.draw \
      --format=csv,noheader 2>/dev/null | head -n1)"
    IFS=',' read -r gpu_name gpu_driver gpu_temp gpu_util gpu_mem_util gpu_mem_used gpu_mem_total gpu_power <<< "${gpu_csv}"
    gpu_name="${gpu_name#"${gpu_name%%[![:space:]]*}"}"
    gpu_name="${gpu_name%"${gpu_name##*[![:space:]]}"}"
    gpu_temp="${gpu_temp//[[:space:]]/}"
    gpu_util="${gpu_util//[[:space:]]/}"
    gpu_mem_util="${gpu_mem_util//[[:space:]]/}"
    gpu_procs="$(nvidia-smi --query-compute-apps=pid,process_name,used_gpu_memory \
      --format=csv,noheader 2>/dev/null | sed '/^$/d' || true)"
    if [[ "${gpu_mem_used}" == "[N/A]" || "${gpu_mem_total}" == "[N/A]" ]]; then
      local compute_used_mib
      compute_used_mib="$(gpu_compute_used_mib)"
      if [[ -n "${compute_used_mib}" ]]; then
        gpu_mem_used="$(awk -v m="${compute_used_mib}" 'BEGIN {printf "%.1f GiB", m/1024}')"
      fi
    fi
  fi

  read -r disk_root_pct disk_root_avail _ <<< \
    "$(df -P / 2>/dev/null | awk 'NR==2 {print $5, $4, $6}')"
  disk_root_avail_gib="$(awk -v kib="${disk_root_avail:-0}" 'BEGIN {printf "%.0fG", kib/1024/1024}')"
  model_cache_size="$([[ -d "${MODEL_CACHE}" ]] && echo yes || echo no)"
  if [[ "${JSON}" == true ]]; then
    model_cache_size="$(dir_size_human "${MODEL_CACHE}")"
  fi

  server_running="no"
  server_pid=""
  if server_pid="$(pgrep -f 'python3 .*/server/server\.py' 2>/dev/null | head -n1 || true)"; then
    [[ -n "${server_pid}" ]] && server_running="yes"
  fi

  health_code="$(http_code "http://127.0.0.1:${ATLAS_PORT}${HEALTH_PATH}")"
  models_code="$(http_code "http://127.0.0.1:${ATLAS_PORT}/v1/models")"

  tunnel_running="no"
  if [[ -f "${HELPER_DIR}/cloudflared.pid" ]]; then
    local tunnel_pid tunnel_state
    tunnel_pid="$(cat "${HELPER_DIR}/cloudflared.pid" 2>/dev/null || true)"
    tunnel_state=""
    if [[ -n "${tunnel_pid}" ]] && kill -0 "${tunnel_pid}" 2>/dev/null; then
      tunnel_state="$(awk '{print $3}' "/proc/${tunnel_pid}/stat" 2>/dev/null || true)"
    fi
    if [[ -n "${tunnel_state}" && "${tunnel_state}" != "Z" ]]; then
      tunnel_running="yes"
    fi
  fi

  if [[ "${JSON}" == true ]]; then
    python3 - "${now}" "${host}" "${uptime_str}" "${load1}" "${load5}" "${load15}" "${cores}" "${cpu_pct}" \
      "${mem_total}" "${mem_used}" "${mem_avail}" "${swap_total}" "${swap_used}" \
      "${gpu_name}" "${gpu_driver}" "${gpu_temp}" "${gpu_util}" "${gpu_mem_util}" \
      "${gpu_mem_used}" "${gpu_mem_total}" "${gpu_procs:-}" \
      "${disk_root_pct}" "${model_cache_size}" \
      "${server_running}" "${server_pid:-}" "${container_status}" \
      "${health_code}" "${models_code}" "${tunnel_running}" \
      "${ATLAS_CONTAINER}" "${ATLAS_PORT}" <<'PY'
import json, sys

def pct(value):
    value = (value or "").strip().rstrip("%")
    try:
        return float(value)
    except ValueError:
        return None

(
    now, host, uptime, load1, load5, load15, cores, cpu_pct,
    mem_total, mem_used, mem_avail, swap_total, swap_used,
    gpu_name, gpu_driver, gpu_temp, gpu_util, gpu_mem_util,
    gpu_mem_used, gpu_mem_total, gpu_procs,
    disk_root_pct, model_cache_size,
    server_running, server_pid, container_status,
    health_code, models_code, tunnel_running,
    atlas_container, atlas_port,
) = sys.argv[1:]

def kib_gib(v):
    return round(int(v) / 1024 / 1024, 2)

def kib_mib(v):
    return round(int(v) / 1024, 0)

payload = {
    "timestamp_utc": now,
    "host": host,
    "uptime": uptime,
    "cpu": {
        "cores": int(cores),
        "usage_pct": float(cpu_pct),
        "load_1m": float(load1),
        "load_5m": float(load5),
        "load_15m": float(load15),
    },
    "memory": {
        "total_gib": kib_gib(mem_total),
        "used_gib": kib_gib(mem_used),
        "available_gib": kib_gib(mem_avail),
        "swap_total_mib": kib_mib(swap_total),
        "swap_used_mib": kib_mib(swap_used),
    },
    "gpu": {
        "name": gpu_name or None,
        "driver": gpu_driver or None,
        "temperature_c": pct(gpu_temp),
        "utilization_pct": pct(gpu_util),
        "memory_utilization_pct": pct(gpu_mem_util),
        "memory_used": gpu_mem_used,
        "memory_total": gpu_mem_total,
        "compute_processes": [line.strip() for line in gpu_procs.splitlines() if line.strip()],
    },
    "disk": {
        "root_used_pct": disk_root_pct,
        "model_cache": model_cache_size,
    },
    "llm_server": {
        "launcher_running": server_running == "yes",
        "launcher_pid": int(server_pid) if server_pid else None,
        "container": atlas_container,
        "container_status": container_status,
        "health_http": int(health_code),
        "models_http": int(models_code),
        "tunnel_running": tunnel_running == "yes",
        "port": int(atlas_port),
    },
}
print(json.dumps(payload, indent=2))
PY
    return 0
  fi

  local health_status models_status gpu_proc_summary
  local mem_used_gib mem_total_gib mem_avail_gib swap_used_gib swap_total_gib

  echo -e "${B}metrics${X}  ${host}  ${D}${now}${X}"

  mem_used_gib="$(gib_short "${mem_used}")"
  mem_total_gib="$(gib_short "${mem_total}")"
  mem_avail_gib="$(gib_short "${mem_avail}")"
  swap_used_gib="$(gib_short "${swap_used}")"
  swap_total_gib="$(gib_short "${swap_total}")"

  compact_line "cpu  ${cpu_pct}%  load ${load1}/${load5}/${load15}  ·  ${cores}c  ·  ${uptime_str#up }"
  compact_line "ram  ${mem_used_gib}/${mem_total_gib} GiB used  ·  ${mem_avail_gib} GiB free  ·  swap ${swap_used_gib}/${swap_total_gib} GiB"

  if [[ -z "${gpu_name}" ]]; then
    compact_line "gpu  n/a"
  else
    gpu_proc_summary="none"
    if [[ -n "${gpu_procs:-}" ]]; then
      gpu_proc_summary="$(echo "${gpu_procs}" | head -n1 \
        | awk -F',' '{gsub(/^ +| +$/,"",$2); gsub(/^ +| +$/,"",$3); printf "%s %s", $2, $3}')"
    fi
    compact_line "gpu  ${gpu_name}  ${gpu_temp}°C  ${gpu_util:-0}/${gpu_mem_util:-0}  ·  ${gpu_mem_used}/${gpu_mem_total}  ·  ${gpu_power}  ·  ${gpu_proc_summary}"
  fi

  compact_line "disk  / ${disk_root_pct} used  ·  ${disk_root_avail_gib} free  ·  models ${model_cache_size}"

  health_status="$(status_word "${health_code}")"
  models_status="$(status_word "${models_code}")"

  compact_line "atlas  ${container_status}  health ${health_status}  models ${models_status}  ·  tunnel $([[ "${tunnel_running}" == yes ]] && echo on || echo off)  ·  launcher $([[ "${server_running}" == yes ]] && echo "pid ${server_pid}" || echo off)"
}

if [[ -n "${WATCH_INTERVAL}" ]]; then
  while true; do
    if [[ "${JSON}" != true ]]; then
      clear 2>/dev/null || printf '\033[H\033[J'
    fi
    collect_metrics
    sleep "${WATCH_INTERVAL}"
  done
else
  collect_metrics
fi
