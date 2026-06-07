#!/usr/bin/env bash
# metrics.sh — snapshot of CPU, RAM, GPU, temps, disk, and LLM server health.
#
# Usage:
#   ./server/metrics.sh           # human-readable report
#   ./server/metrics.sh --json    # machine-readable JSON
#   ./server/metrics.sh --watch 5 # refresh every 5s (Ctrl+C to stop)
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

JSON=false
WATCH_INTERVAL=""
VLLM_CONTAINER="${VLLM_CONTAINER:-vllm-qwen36-dflash}"
VLLM_PORT="${VLLM_PORT:-8000}"
MODEL_CACHE="${MODEL_CACHE:-${HOME}/.cache/qwen36}"
COMPILE_CACHE="${COMPILE_CACHE:-${HOME}/.cache/vllm-spark-compile}"
HELPER_DIR="${HELPER_DIR:-${HOME}/.spark-serve}"

R=$'\033[0;31m'
G=$'\033[0;32m'
Y=$'\033[1;33m'
C=$'\033[0;36m'
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
  VLLM_CONTAINER    Docker container name (default: vllm-qwen36-dflash)
  VLLM_PORT         vLLM HTTP port (default: 8000)
  MODEL_CACHE       Model weights cache directory
  COMPILE_CACHE     vLLM compile cache directory
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

section() { :; }

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

read_cpu_times() {
  awk '/^cpu / {print $2,$3,$4,$5,$6,$7,$8; exit}' /proc/stat
}

cpu_usage_percent() {
  local u1 n1 s1 i1 iw1 irq1 sirq1 st1
  local u2 n2 s2 i2 iw2 irq2 sirq2 st2
  local total1 total2 idle1 idle2 total_delta idle_delta

  read -r u1 n1 s1 i1 iw1 irq1 sirq1 st1 <<< "$(read_cpu_times)"
  sleep 0.25
  read -r u2 n2 s2 i2 iw2 irq2 sirq2 st2 <<< "$(read_cpu_times)"

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

format_gib() {
  awk -v kib="$1" 'BEGIN {printf "%.2f GiB", kib / 1024 / 1024}'
}

format_mib() {
  awk -v kib="$1" 'BEGIN {printf "%.0f MiB", kib / 1024}'
}

dir_size_human() {
  local path="$1"
  if [[ ! -d "${path}" ]]; then
    echo "missing"
    return
  fi
  timeout 3 du -sh "${path}" 2>/dev/null | awk '{print $1}' || echo ">(timeout)"
}

probe_gpu_memory_cuda() {
  local dc="$1"
  local container="$2"

  if [[ -n "${dc}" ]] && ${dc} ps --format '{{.Names}}' 2>/dev/null | grep -qx "${container}"; then
    timeout 8 ${dc} exec "${container}" python3 -c \
      'import torch; f,t=torch.cuda.mem_get_info(); print(f"{f},{t}")' 2>/dev/null
  fi
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
  local gpu_name gpu_driver gpu_temp gpu_util gpu_mem_util gpu_power gpu_sm_clock
  local gpu_mem_used gpu_mem_total gpu_mem_free gpu_mem_source
  local disk_root_pct disk_root_avail disk_root_avail_gib model_cache_size compile_cache_size
  local server_running server_pid container_status container_cpu container_mem
  local health_code models_code tunnel_running top_procs gpu_procs sensors_text
  local dc json_blob

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
  container_cpu=""
  container_mem=""
  if [[ -n "${dc}" ]]; then
    if ${dc} ps --format '{{.Names}}' 2>/dev/null | grep -qx "${VLLM_CONTAINER}"; then
      container_status="running"
      if [[ "${JSON}" == true ]]; then
        IFS='|' read -r container_cpu container_mem _ <<< \
          "$(timeout 3 ${dc} stats --no-stream --format '{{.CPUPerc}}|{{.MemUsage}}' "${VLLM_CONTAINER}" 2>/dev/null || echo '|')"
      fi
    elif ${dc} ps -a --format '{{.Names}}' 2>/dev/null | grep -qx "${VLLM_CONTAINER}"; then
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
  gpu_sm_clock=""
  gpu_mem_used="N/A"
  gpu_mem_total="N/A"
  gpu_mem_free="N/A"
  gpu_mem_source="unavailable"

  if command -v nvidia-smi >/dev/null 2>&1; then
    local gpu_csv
    gpu_csv="$(nvidia-smi --query-gpu=name,driver_version,temperature.gpu,utilization.gpu,utilization.memory,memory.used,memory.total,power.draw,power.limit,clocks.current.sm,clocks.current.memory,pcie.link.gen.current,pcie.link.width.current \
      --format=csv,noheader 2>/dev/null | head -n1)"
    IFS=',' read -r gpu_name gpu_driver gpu_temp gpu_util gpu_mem_util \
      gpu_mem_used gpu_mem_total gpu_power _ gpu_sm_clock _ _ _ <<< "${gpu_csv}"
    gpu_name="${gpu_name#"${gpu_name%%[![:space:]]*}"}"
    gpu_name="${gpu_name%"${gpu_name##*[![:space:]]}"}"
    gpu_driver="${gpu_driver#"${gpu_driver%%[![:space:]]*}"}"
    gpu_driver="${gpu_driver%"${gpu_driver##*[![:space:]]}"}"
    gpu_temp="${gpu_temp//[[:space:]]/}"
    gpu_util="${gpu_util//[[:space:]]/}"
    gpu_mem_util="${gpu_mem_util//[[:space:]]/}"
    gpu_power="${gpu_power#"${gpu_power%%[![:space:]]*}"}"
    gpu_sm_clock="${gpu_sm_clock#"${gpu_sm_clock%%[![:space:]]*}"}"

    gpu_procs="$(nvidia-smi --query-compute-apps=pid,process_name,used_gpu_memory \
      --format=csv,noheader 2>/dev/null | sed '/^$/d' || true)"

    local cuda_line
    if [[ "${JSON}" == true ]]; then
      cuda_line="$(probe_gpu_memory_cuda "${dc}" "${VLLM_CONTAINER}")" || true
    else
      cuda_line=""
    fi
    if [[ -n "${cuda_line}" ]]; then
      local free_b total_b
      IFS=',' read -r free_b total_b <<< "${cuda_line}"
      gpu_mem_free="$(awk -v b="${free_b}" 'BEGIN {printf "%.1f GiB", b/1024/1024/1024}')"
      gpu_mem_total="$(awk -v b="${total_b}" 'BEGIN {printf "%.1f GiB", b/1024/1024/1024}')"
      gpu_mem_used="$(awk -v u="${total_b}" -v f="${free_b}" 'BEGIN {printf "%.1f GiB", (u-f)/1024/1024/1024}')"
      gpu_mem_source="cuda"
    elif [[ "${gpu_mem_used}" == "[N/A]" || "${gpu_mem_total}" == "[N/A]" ]]; then
      local compute_used_mib
      compute_used_mib="$(gpu_compute_used_mib)"
      if [[ -n "${compute_used_mib}" ]]; then
        gpu_mem_used="$(awk -v m="${compute_used_mib}" 'BEGIN {printf "%.1f GiB", m/1024}')"
        gpu_mem_total="[N/A]"
        gpu_mem_free="[N/A]"
        gpu_mem_source="nvidia-smi compute apps"
      else
        gpu_mem_source="gb10-host-na (start container for CUDA view)"
      fi
    else
      gpu_mem_source="nvidia-smi"
    fi
  fi

  if [[ "${JSON}" == true ]] && command -v sensors >/dev/null 2>&1; then
    sensors_text="$(sensors 2>/dev/null \
      | awk '/^[^ ]/ {chip=$0; next} /\+/ {gsub(/^[ \t]+/,""); print chip " " $0}' \
      | head -n 12 || true)"
  fi

  read -r disk_root_pct disk_root_avail _ <<< \
    "$(df -P / 2>/dev/null | awk 'NR==2 {print $5, $4, $6}')"
  disk_root_avail_gib="$(awk -v kib="${disk_root_avail:-0}" 'BEGIN {printf "%.0fG", kib/1024/1024}')"
  if [[ "${JSON}" == true ]]; then
    model_cache_size="$(dir_size_human "${MODEL_CACHE}")"
    compile_cache_size="$(dir_size_human "${COMPILE_CACHE}")"
    disk_root_avail="$(format_mib "${disk_root_avail}")"
  else
    model_cache_size="$([[ -d "${MODEL_CACHE}" ]] && echo yes || echo no)"
    compile_cache_size="$([[ -d "${COMPILE_CACHE}" ]] && echo yes || echo no)"
  fi

  server_running="no"
  server_pid=""
  if server_pid="$(pgrep -f 'python3 .*/server/server\.py' 2>/dev/null | head -n1 || true)"; then
    [[ -n "${server_pid}" ]] && server_running="yes"
  fi

  health_code="$(http_code "http://127.0.0.1:${VLLM_PORT}/health")"
  models_code="$(http_code "http://127.0.0.1:${VLLM_PORT}/v1/models")"

  tunnel_running="no"
  if [[ -f "${HELPER_DIR}/cloudflared.pid" ]]; then
    local tunnel_pid
    tunnel_pid="$(cat "${HELPER_DIR}/cloudflared.pid" 2>/dev/null || true)"
    if [[ -n "${tunnel_pid}" ]] && kill -0 "${tunnel_pid}" 2>/dev/null; then
      tunnel_running="yes"
    fi
  fi

  top_procs=""
  if [[ "${JSON}" == true ]]; then
    top_procs="$(ps -eo pid,rss,comm --sort=-rss 2>/dev/null \
      | awk 'NR==1 {next} NR<=8 {printf "%s:%.0fMiB:%s,", $1, $2/1024, $3}' \
      | sed 's/,$//' || true)"
  fi

  if [[ "${JSON}" == true ]]; then
    python3 - "${now}" "${host}" "${uptime_str}" "${load1}" "${load5}" "${load15}" "${cores}" "${cpu_pct}" \
      "${mem_total}" "${mem_used}" "${mem_avail}" "${mem_free}" "${swap_total}" "${swap_used}" \
      "${gpu_name}" "${gpu_driver}" "${gpu_temp}" "${gpu_util}" "${gpu_mem_util}" \
      "${gpu_mem_used}" "${gpu_mem_total}" "${gpu_mem_free}" "${gpu_mem_source}" \
      "${gpu_power}" "${gpu_sm_clock}" "${gpu_procs:-}" \
      "${disk_root_pct}" "${disk_root_avail}" "${model_cache_size}" "${compile_cache_size}" \
      "${server_running}" "${server_pid:-}" "${container_status}" "${container_cpu}" "${container_mem}" \
      "${health_code}" "${models_code}" "${tunnel_running}" "${top_procs}" "${sensors_text:-}" \
      "${VLLM_CONTAINER}" "${VLLM_PORT}" <<'PY'
import json, sys

def pct(value):
    value = (value or "").strip().rstrip("%")
    try:
        return float(value)
    except ValueError:
        return None

def watts(value):
    value = (value or "").strip().rstrip(" W")
    if not value or value.startswith("["):
        return None
    try:
        return float(value)
    except ValueError:
        return None

def mhz(value):
    value = (value or "").strip().rstrip(" MHz")
    if not value or value.startswith("["):
        return None
    try:
        return float(value)
    except ValueError:
        return None

(
    now, host, uptime, load1, load5, load15, cores, cpu_pct,
    mem_total, mem_used, mem_avail, mem_free, swap_total, swap_used,
    gpu_name, gpu_driver, gpu_temp, gpu_util, gpu_mem_util,
    gpu_mem_used, gpu_mem_total, gpu_mem_free, gpu_mem_source,
    gpu_power, gpu_sm_clock, gpu_procs,
    disk_root_pct, disk_root_avail, model_cache_size, compile_cache_size,
    server_running, server_pid, container_status, container_cpu, container_mem,
    health_code, models_code, tunnel_running, top_procs, sensors_text,
    vllm_container, vllm_port,
) = sys.argv[1:]

def kib_gib(v):
    return round(int(v) / 1024 / 1024, 2)

def kib_mib(v):
    return round(int(v) / 1024, 0)

procs = [line.strip() for line in gpu_procs.splitlines() if line.strip()]

top = []
for item in top_procs.split(","):
    if not item:
        continue
    pid, rss, comm = item.split(":", 2)
    top.append({"pid": int(pid), "rss_mib": float(rss.replace("MiB", "")), "comm": comm})

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
        "free_gib": kib_gib(mem_free),
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
        "memory_free": gpu_mem_free,
        "memory_source": gpu_mem_source,
        "power_w": watts(gpu_power),
        "sm_clock_mhz": mhz(gpu_sm_clock),
        "compute_processes": procs,
    },
    "temperatures": {
        "gpu_c": pct(gpu_temp),
        "sensors": sensors_text or None,
    },
    "disk": {
        "root_used_pct": disk_root_pct,
        "root_available": disk_root_avail,
        "model_cache": model_cache_size,
        "compile_cache": compile_cache_size,
    },
    "llm_server": {
        "launcher_running": server_running == "yes",
        "launcher_pid": int(server_pid) if server_pid else None,
        "container": vllm_container,
        "container_status": container_status,
        "container_cpu": container_cpu or None,
        "container_memory": container_mem or None,
        "health_http": int(health_code),
        "models_http": int(models_code),
        "tunnel_running": tunnel_running == "yes",
        "port": int(vllm_port),
    },
    "top_processes_rss": top,
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

  compact_line "disk  / ${disk_root_pct} used  ·  ${disk_root_avail_gib} free  ·  models ${model_cache_size}  ·  compile ${compile_cache_size}"

  health_status="$(status_word "${health_code}")"
  models_status="$(status_word "${models_code}")"
  container_cpu="${container_cpu:-}"
  container_mem="${container_mem:-}"
  if [[ "${container_mem}" == *" / "* ]]; then
    container_mem="${container_mem%% / *}"
  fi

  local vllm_stats=""
  if [[ -n "${container_cpu}" && -n "${container_mem}" ]]; then
    vllm_stats="${container_cpu} cpu  ${container_mem} ram  ·  "
  fi

  compact_line "vllm  ${container_status}  ${vllm_stats}health ${health_status}  models ${models_status}  ·  tunnel $([[ "${tunnel_running}" == yes ]] && echo on || echo off)  ·  launcher $([[ "${server_running}" == yes ]] && echo "pid ${server_pid}" || echo off)"
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
