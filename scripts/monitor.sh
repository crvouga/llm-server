#!/usr/bin/env bash
# Compact real-time system metrics. Refreshes until Ctrl+C.
#
# Usage:
#   ./scripts/monitor.sh
#   INTERVAL=1 ./scripts/monitor.sh
#   ./scripts/monitor.sh -i 0.5 --once
set -uo pipefail

INTERVAL="${INTERVAL:-2}"
ONCE=0
USE_COLOR=1

usage() {
  echo "Usage: $0 [-i SECONDS] [--once] [--no-color]"
  exit 0
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -i) INTERVAL="${2:?missing value for -i}"; shift 2 ;;
    --once) ONCE=1; shift ;;
    --no-color) USE_COLOR=0; shift ;;
    -h|--help) usage ;;
    *) echo "Unknown argument: $1" >&2; exit 1 ;;
  esac
done

if (( USE_COLOR )) && [[ -t 1 ]] && command -v tput &>/dev/null && [[ $(tput colors 2>/dev/null || echo 0) -ge 8 ]]; then
  RESET='\033[0m'; DIM='\033[2m'; BOLD='\033[1m'
  HI='\033[1;36m'; WARN='\033[1;33m'; HOT='\033[1;31m'
else
  RESET=''; DIM=''; BOLD=''; HI=''; WARN=''; HOT=''
  USE_COLOR=0
fi

RUNNING=1

cleanup() {
  [[ -t 1 ]] && printf '\033[?25h\033[0m\n'
}

quit() {
  RUNNING=0
  cleanup
  exit 0
}

trap cleanup EXIT
trap quit INT TERM

fmt_bytes() {
  awk -v b="${1:-0}" 'BEGIN {
    split("B KB MB GB TB", u)
    i = 1
    while (b >= 1024 && i < 5) { b /= 1024; i++ }
    if (i == 1) printf "%d %s", b, u[i]
    else printf "%.1f %s", b, u[i]
  }'
}

bar() {
  awk -v p="${1:-0}" -v w="${2:-12}" 'BEGIN {
    if (p < 0) p = 0; if (p > 100) p = 100
    n = int(p * w / 100 + 0.5)
    for (i = 0; i < w; i++) printf (i < n ? "#" : "-")
  }'
}

val_color() {
  local p="${1:-0}"; p=${p%.*}
  [[ -z "$p" || ! "$p" =~ ^[0-9]+$ ]] && p=0
  if (( ! USE_COLOR )); then echo ""; return; fi
  if (( p >= 90 )); then echo "$HOT"
  elif (( p >= 70 )); then echo "$WARN"
  else echo "$HI"
  fi
}

metric() {
  local label="$1" pct="$2" detail="$3"
  local c; c=$(val_color "$pct")
  printf "  %-4s  %s%3.0f%%%s  [%s]  %s\n" "$label" "$c" "$pct" "$RESET" "$(bar "$pct")" "$detail"
}

snapshot_cpu() {
  awk '/^cpu / { print $2+$3+$4+$5+$6+$7+$8, $5+$6 }' /proc/stat
}

cpu_pct() {
  awk -v b="$1" -v a="$2" 'BEGIN {
    split(b, x, " "); split(a, y, " ")
    dt = y[1]-x[1]; di = y[2]-x[2]
    printf "%.1f", (dt > 0) ? (dt-di)*100/dt : 0
  }'
}

snapshot_io() {
  awk '
    NR > 2 && $1 !~ /^(lo|docker|veth|br-|virbr)/ {
      gsub(":", "", $1); rx += $2; tx += $10
    }
    $3 ~ /^nvme[0-9]+$/ { dr += $6; dw += $10 }
    END { printf "%d %d %d %d\n", rx, tx, dr, dw }' /proc/net/dev /proc/diskstats
}

wait_interval() {
  local elapsed=0 step=0.2 tty_in=""
  [[ -r /dev/tty ]] && tty_in=/dev/tty

  while (( RUNNING )) && awk -v e="$elapsed" -v t="$INTERVAL" 'BEGIN { exit !(e < t) }'; do
    if [[ -n "$tty_in" ]]; then
      local key=""
      if IFS= read -r -t "$step" -n 1 key <"$tty_in" 2>/dev/null; then
        case "$key" in
          q|Q) quit ;;
        esac
      fi
    else
      sleep "$step" 2>/dev/null || true
    fi
    elapsed=$(awk -v e="$elapsed" -v s="$step" 'BEGIN { printf "%.2f", e + s }')
  done
  (( RUNNING )) || exit 0
}

io_rates() {
  awk -v b="$1" -v a="$2" -v dt="$INTERVAL" 'BEGIN {
    split(b, x, " "); split(a, y, " ")
    rx = (y[1]-x[1])/dt; tx = (y[2]-x[2])/dt
    dr = (y[3]-x[3])*512/dt; dw = (y[4]-x[4])*512/dt
    if (rx < 0) rx = 0; if (tx < 0) tx = 0
    if (dr < 0) dr = 0; if (dw < 0) dw = 0
    printf "%.0f %.0f %.0f %.0f\n", rx, tx, dr, dw
  }'
}

render() {
  (( RUNNING )) || exit 0
  local cpu_b io_b
  cpu_b=$(snapshot_cpu)
  io_b=$(snapshot_io)
  wait_interval
  local cpu_a io_a
  cpu_a=$(snapshot_cpu)
  io_a=$(snapshot_io)

  local cpu load1 uptime_s ncpu
  cpu=$(cpu_pct "$cpu_b" "$cpu_a")
  read -r load1 _ _ _ _ < /proc/loadavg
  ncpu=$(nproc)
  uptime_s=$(awk '{print int($1)}' /proc/uptime)

  local mem_total mem_used mem_pct
  read -r mem_total mem_used mem_pct < <(awk '
    /MemTotal:/ { t=$2 } /MemAvailable:/ { a=$2 }
    END { u=t-a; printf "%d %d %.1f\n", t, u, (t>0)?u*100/t:0 }' /proc/meminfo)

  local gpu_util="" gpu_temp="" gpu_power=""
  if command -v nvidia-smi &>/dev/null && nvidia-smi &>/dev/null; then
    read -r gpu_util gpu_temp gpu_power < <(nvidia-smi \
      --query-gpu=utilization.gpu,temperature.gpu,power.draw \
      --format=csv,noheader,nounits 2>/dev/null \
      | awk -F', ' '{ gsub(/\[|\]/, "", $3); print $1, $2, $3 }')
  fi

  local disk_pct disk_used disk_total
  read -r disk_pct disk_used disk_total < <(df -B1 / 2>/dev/null | awk 'NR==2 {
    gsub(/%/, "", $5); printf "%s %s %s\n", $5, $3, $2 }')

  local rx tx dr dw
  read -r rx tx dr dw < <(io_rates "$io_b" "$io_a")

  if [[ -t 1 ]]; then
    printf '\033[H\033[J'
  fi

  local host ts
  host=$(hostname -s 2>/dev/null || hostname)
  ts=$(date '+%H:%M:%S')
  printf '%s%s%s%s  %s  up %dd %dh %dm  load %.1f%s\n\n' \
    "$BOLD" "$host" "$RESET" "$DIM" "$ts" \
    "$((uptime_s/86400))" "$((uptime_s%86400/3600))" "$((uptime_s%3600/60))" "$load1" "$RESET"

  metric "cpu" "$cpu" "${ncpu} cores"
  metric "ram" "$mem_pct" "$(fmt_bytes $((mem_used*1024))) / $(fmt_bytes $((mem_total*1024)))"
  if [[ -n "$gpu_util" ]]; then
    local gpu_detail="${gpu_temp}C"
    [[ "$gpu_power" != "N/A" && -n "$gpu_power" ]] && gpu_detail="${gpu_detail}, ${gpu_power}W"
    metric "gpu" "$gpu_util" "$gpu_detail"
  else
    printf '  %-4s  %s\n' "gpu" "unavailable"
  fi
  metric "disk" "$disk_pct" "$(fmt_bytes "$disk_used") / $(fmt_bytes "$disk_total")"

  printf '\n'
  printf '  %-4s  in %-10s   out %-10s\n' "net" "$(fmt_bytes "$rx")/s" "$(fmt_bytes "$tx")/s"
  printf '  %-4s  read %-10s  write %-10s\n' "io" "$(fmt_bytes "$dr")/s" "$(fmt_bytes "$dw")/s"
  printf '%s\n' "$DIM"
  if [[ -r /dev/tty ]]; then
    printf '  refresh every %ss  (q or ctrl+c to quit)%s\n' "$INTERVAL" "$RESET"
  else
    printf '  refresh every %ss  (ctrl+c to quit)%s\n' "$INTERVAL" "$RESET"
  fi
}

if (( ONCE )); then
  render
else
  while (( RUNNING )); do render; done
fi
