#!/usr/bin/env bash
# free-ram.sh — aggressively reclaim RAM (and GPU memory) before starting vLLM.
#
# torch.compile on GB10 can spike system RAM; run this when the box feels tight or
# another workload (often LM Studio) was using memory.
#
# Usage:
#   ./server/free-ram.sh              # aggressive cleanup (default)
#   ./server/free-ram.sh --dry-run    # show actions without changing anything
#   ./server/free-ram.sh --no-swap    # skip swapoff/swapon (needs less sudo)
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

DRY_RUN=false
RESET_SWAP=true
VLLM_CONTAINER="${VLLM_CONTAINER:-vllm-qwen36-dflash}"

R=$'\033[0;31m'
G=$'\033[0;32m'
Y=$'\033[1;33m'
C=$'\033[0;36m'
B=$'\033[1m'
X=$'\033[0m'

usage() {
  cat <<EOF
Usage: $(basename "$0") [OPTIONS]

Reclaim system RAM and GPU memory so vLLM can start cleanly.

Options:
  --dry-run       Print planned actions only
  --no-swap       Do not run swapoff/swapon (still drops page cache if permitted)
  -h, --help      Show this help

Environment:
  VLLM_CONTAINER  Docker container name (default: vllm-qwen36-dflash)
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY_RUN=true ;;
    --no-swap) RESET_SWAP=false ;;
    -h|--help) usage; exit 0 ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
  shift
done

run() {
  if [[ "${DRY_RUN}" == true ]]; then
    echo -e "${Y}[dry-run]${X} $*"
  else
    "$@"
  fi
}

run_sudo() {
  if [[ "${DRY_RUN}" == true ]]; then
    echo -e "${Y}[dry-run sudo]${X} $*"
    return 0
  fi
  if [[ "$(id -u)" -eq 0 ]]; then
    "$@"
  elif command -v sudo >/dev/null 2>&1; then
    sudo "$@"
  else
    echo -e "${Y}[!]${X} Skipping (needs root): $*"
    return 0
  fi
}

section() {
  echo -e "\n${B}━━━  $*  ━━━${X}"
}

info() { echo -e "${C}[•]${X} $*"; }
ok() { echo -e "${G}[✓]${X} $*"; }
warn() { echo -e "${Y}[!]${X} $*"; }

mem_report() {
  local label="$1"
  section "Memory: ${label}"
  free -h
  if command -v nvidia-smi >/dev/null 2>&1; then
    echo
    local gpu_mem
    gpu_mem="$(nvidia-smi --query-gpu=memory.free,memory.total --format=csv,noheader,nounits 2>/dev/null || true)"
    if [[ -n "${gpu_mem}" ]]; then
      echo "${gpu_mem}" \
        | awk -F', ' '{printf "GPU: %.1f / %.1f GiB free\n", $1/1024, $2/1024}'
    else
      echo "GPU: (nvidia-smi unavailable)"
    fi
    local gpu_procs
    gpu_procs="$(nvidia-smi --query-compute-apps=pid,process_name,used_gpu_memory \
      --format=csv,noheader 2>/dev/null || true)"
    if [[ -n "${gpu_procs}" ]]; then
      echo "GPU processes:"
      echo "${gpu_procs}" | sed 's/^/  /'
    fi
  fi
  echo
  ps -eo pid,rss,comm --sort=-rss 2>/dev/null \
    | awk 'NR==1 || NR<=11 {rss=$2; if (NR>1) rss=sprintf("%.0f MiB", $2/1024); printf "  %-8s %8s  %s\n", $1, rss, $3}'
}

stop_server_managed() {
  section "Stopping llm-server (vLLM + tunnel)"
  local pattern='python3 .*/server/server\.py'
  if pgrep -f "${pattern}" >/dev/null 2>&1; then
    info "Sending SIGTERM to server/server.py..."
    if [[ "${DRY_RUN}" == true ]]; then
      pgrep -af "${pattern}" || true
    else
      pkill -TERM -f "${pattern}" || true
      for _ in $(seq 1 10); do
        pgrep -f "${pattern}" >/dev/null 2>&1 || break
        sleep 1
      done
      if pgrep -f "${pattern}" >/dev/null 2>&1; then
        warn "Server still running — sending SIGKILL"
        pkill -KILL -f "${pattern}" || true
      fi
    fi
  else
    info "No server/server.py process running"
  fi
  if [[ -f "${REPO_ROOT}/server/server.py" ]]; then
    info "Running server/server.py --stop-hard..."
    run python3 "${REPO_ROOT}/server/server.py" --stop-hard || true
  fi
  ok "llm-server stopped"
}

stop_lmstudio() {
  section "Stopping LM Studio"
  local lms=""
  if command -v lms >/dev/null 2>&1; then
    lms="$(command -v lms)"
  elif [[ -x "${HOME}/.lmstudio/bin/lms" ]]; then
    lms="${HOME}/.lmstudio/bin/lms"
  fi

  if [[ -n "${lms}" ]]; then
    info "Stopping LM Studio server (${lms} server stop)..."
    run "${lms}" server stop 2>/dev/null || true
  else
    info "lms CLI not found — killing LM Studio processes directly"
  fi

  local patterns=(
    'lmstudio'
    'LM Studio'
    'lms-server'
    'node.*lmstudio'
  )
  for pat in "${patterns[@]}"; do
    if pgrep -f "${pat}" >/dev/null 2>&1; then
      info "Stopping processes matching: ${pat}"
      if [[ "${DRY_RUN}" == true ]]; then
        pgrep -af "${pat}" || true
      else
        pkill -TERM -f "${pat}" 2>/dev/null || true
      fi
    fi
  done

  if [[ "${DRY_RUN}" != true ]]; then
    sleep 2
    for pat in "${patterns[@]}"; do
      pkill -KILL -f "${pat}" 2>/dev/null || true
    done
  fi
  ok "LM Studio cleanup done"
}

stop_user_services() {
  section "Stopping related user systemd units"
  if ! command -v systemctl >/dev/null 2>&1; then
    info "systemctl not available — skipping"
    return
  fi
  local units=(
    local-llm-cloudflared.service
  )
  for unit in "${units[@]}"; do
    if systemctl --user is-active --quiet "${unit}" 2>/dev/null; then
      info "Stopping ${unit}..."
      run systemctl --user stop "${unit}" || true
    fi
  done
}

stop_other_llm_runtimes() {
  section "Stopping other local LLM runtimes"
  local patterns=(
    'ollama serve'
    'ollama runner'
    'text-generation-webui'
    'koboldcpp'
    'llama-server'
    'llama.cpp'
  )
  for pat in "${patterns[@]}"; do
    if pgrep -f "${pat}" >/dev/null 2>&1; then
      info "Stopping: ${pat}"
      if [[ "${DRY_RUN}" == true ]]; then
        pgrep -af "${pat}" || true
      else
        pkill -TERM -f "${pat}" 2>/dev/null || true
        sleep 1
        pkill -KILL -f "${pat}" 2>/dev/null || true
      fi
    fi
  done
}

kill_gpu_compute_processes() {
  section "Clearing GPU compute processes"
  if ! command -v nvidia-smi >/dev/null 2>&1; then
    info "nvidia-smi not found — skipping"
    return
  fi

  local pids
  pids="$(nvidia-smi --query-compute-apps=pid --format=csv,noheader 2>/dev/null \
    | tr -d ' ' | sort -u || true)"
  if [[ -z "${pids}" ]]; then
    ok "No GPU compute processes"
    return
  fi

  while read -r pid; do
    [[ -z "${pid}" || ! "${pid}" =~ ^[0-9]+$ ]] && continue
    [[ "${pid}" -eq "$$" || "${pid}" -eq "${PPID}" ]] && continue
    local cmd=""
    cmd="$(ps -p "${pid}" -o comm= 2>/dev/null || true)"
    info "Stopping GPU PID ${pid} (${cmd:-unknown})..."
    if [[ "${DRY_RUN}" == true ]]; then
      ps -p "${pid}" -o pid,rss,args 2>/dev/null || true
    else
      kill -TERM "${pid}" 2>/dev/null || true
    fi
  done <<<"${pids}"

  if [[ "${DRY_RUN}" != true ]]; then
    sleep 3
    pids="$(nvidia-smi --query-compute-apps=pid --format=csv,noheader 2>/dev/null \
      | tr -d ' ' | sort -u || true)"
    while read -r pid; do
      [[ -z "${pid}" || ! "${pid}" =~ ^[0-9]+$ ]] && continue
      warn "Force-killing stubborn GPU PID ${pid}"
      kill -KILL "${pid}" 2>/dev/null || true
    done <<<"${pids}"
  fi
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

stop_docker_workloads() {
  section "Stopping Docker workloads"
  local dc
  dc="$(docker_cmd)"
  if [[ -z "${dc}" ]]; then
    warn "Docker not available — skipping container cleanup"
    return
  fi

  local running
  running="$(${dc} ps -q 2>/dev/null || true)"
  if [[ -n "${running}" ]]; then
    info "Stopping all running containers..."
    if [[ "${DRY_RUN}" == true ]]; then
      ${dc} ps --format 'table {{.Names}}\t{{.Status}}\t{{.Size}}' 2>/dev/null || true
    else
      ${dc} stop ${running} 2>/dev/null || true
    fi
  else
    info "No running containers"
  fi

  info "Removing stopped containers..."
  run ${dc} container prune -f >/dev/null 2>&1 || true

  info "Pruning unused Docker networks..."
  run ${dc} network prune -f >/dev/null 2>&1 || true

  info "Pruning Docker build cache..."
  run ${dc} builder prune -f >/dev/null 2>&1 || true

  ok "Docker cleanup done (images kept — re-pulling vLLM is slow)"
}

trim_page_cache() {
  section "Dropping Linux page cache"
  info "sync + drop_caches (pagecache, dentries, inodes)..."
  run_sudo sh -c 'sync; echo 3 > /proc/sys/vm/drop_caches' || true
  ok "Page cache dropped"
}

reset_swap() {
  section "Resetting swap"
  local swap_used_kb
  swap_used_kb="$(awk '/SwapTotal/ {t=$2} /SwapFree/ {f=$2} END {print t-f}' /proc/meminfo)"
  if [[ "${swap_used_kb}" -eq 0 ]]; then
    info "Swap unused — skipping swapoff/swapon"
    return
  fi
  warn "Swap in use ($(( swap_used_kb / 1024 )) MiB) — recycling..."
  run_sudo swapoff -a
  run_sudo swapon -a
  ok "Swap reset"
}

main() {
  echo -e "${B}free-ram${X} — reclaim memory for vLLM"
  if [[ "${DRY_RUN}" == true ]]; then
    warn "Dry run — no changes will be made"
  fi

  mem_report "before"

  stop_server_managed
  stop_lmstudio
  stop_user_services
  stop_other_llm_runtimes
  kill_gpu_compute_processes
  stop_docker_workloads
  trim_page_cache
  if [[ "${RESET_SWAP}" == true ]]; then
    reset_swap
  fi

  mem_report "after"
  ok "Ready to start server: make server-start"
}

main "$@"
