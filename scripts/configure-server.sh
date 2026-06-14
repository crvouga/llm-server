#!/usr/bin/env bash
# Configure this Ubuntu machine to be as "server-friendly" as possible:
#   - never sleep / suspend / hibernate (24/7 uptime)
#   - keep the NVIDIA GPU initialized for low-latency inference
#   - server-tuned kernel / network / file-descriptor limits
#   - persistent, size-capped journald logs
#   - synced clock, automatic security updates, fail2ban, and a safe firewall
#
# Idempotent: safe to re-run. Only changed files trigger service reloads.
# Requires root.
#
# This box is HEADLESS and reached over SSH (:22), NoMachine (:4000), and
# Tailscale. The firewall section always allows those *before* enabling, so
# re-running this cannot lock you out.
#
# Tunables (env vars):
#   SERVER_SKIP_FIREWALL=1     do not touch ufw
#   SERVER_SKIP_APT=1          do not install/upgrade apt packages (offline)
#   SERVER_SSH_TAILSCALE_ONLY=1  restrict SSH to the tailscale0 interface only
#   SERVER_AUTO_REBOOT=1       let unattended-upgrades auto-reboot (default off)
#   SERVER_AUTO_REBOOT_TIME=04:00  reboot time when SERVER_AUTO_REBOOT=1
#   SERVER_SSH_PORT=22         SSH port to keep open (auto-detected otherwise)
#   SERVER_NOMACHINE_PORT=4000 NoMachine port to keep open
set -euo pipefail

# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------
if [[ -t 1 ]]; then
  C_BOLD=$'\033[1m'; C_DIM=$'\033[2m'; C_GREEN=$'\033[32m'
  C_YELLOW=$'\033[33m'; C_BLUE=$'\033[34m'; C_RESET=$'\033[0m'
else
  C_BOLD=""; C_DIM=""; C_GREEN=""; C_YELLOW=""; C_BLUE=""; C_RESET=""
fi

CHANGES=0
section() { printf '\n%s==> %s%s\n' "$C_BOLD$C_BLUE" "$*" "$C_RESET"; }
changed() { CHANGES=$((CHANGES + 1)); printf '   %schanged%s  %s\n' "$C_GREEN" "$C_RESET" "$*"; }
ok()      { printf '   %sok%s      %s\n' "$C_DIM" "$C_RESET" "$*"; }
warn()    { printf '   %swarn%s    %s\n' "$C_YELLOW" "$C_RESET" "$*"; }

# Write $1 with content from stdin only if it differs. Returns 0 if changed.
write_file() {
  local path="$1" tmp
  tmp="$(mktemp)"
  cat > "$tmp"
  install -d "$(dirname "$path")"
  if [[ -f "$path" ]] && cmp -s "$tmp" "$path"; then
    rm -f "$tmp"
    ok "$path"
    return 1
  fi
  install -m 0644 "$tmp" "$path"
  rm -f "$tmp"
  changed "$path"
  return 0
}

# ---------------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------------
if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root: sudo $0" >&2
  exit 1
fi

RELOAD_LOGIND=0
RELOAD_SYSCTL=0
RELOAD_SYSTEMD=0
RELOAD_NM=0
RELOAD_UDEV=0
RELOAD_JOURNALD=0

# Detect the active SSH port (falls back to 22).
SSH_PORT="${SERVER_SSH_PORT:-}"
if [[ -z "$SSH_PORT" ]]; then
  SSH_PORT="$(sshd -T 2>/dev/null | awk '/^port /{print $2; exit}')"
  [[ -z "$SSH_PORT" ]] && SSH_PORT=22
fi
NOMACHINE_PORT="${SERVER_NOMACHINE_PORT:-4000}"

printf '%sConfiguring server: %s (%s)%s\n' "$C_BOLD" "$(hostname)" "$(. /etc/os-release 2>/dev/null && echo "$PRETTY_NAME" || uname -s)" "$C_RESET"

# ===========================================================================
# 1. Stay awake — no sleep / suspend / hibernate
# ===========================================================================
section "Uptime: mask sleep targets"
mask_out="$(systemctl mask sleep.target suspend.target hibernate.target hybrid-sleep.target 2>&1)"
if grep -q 'Created symlink' <<<"$mask_out"; then changed "masked sleep/suspend/hibernate targets"; else ok "sleep targets already masked"; fi

section "Uptime: systemd-logind (ignore lid/idle/power keys)"
write_file /etc/systemd/logind.conf.d/server.conf <<'EOF' && RELOAD_LOGIND=1
[Login]
HandleLidSwitch=ignore
HandleLidSwitchExternalPower=ignore
HandleLidSwitchDocked=ignore
HandleSuspendKey=ignore
HandleHibernateKey=ignore
HandlePowerKey=ignore
HandleSuspendKeyLongPress=ignore
HandleHibernateKeyLongPress=ignore
IdleAction=ignore
StopIdleSessionSec=infinity
EOF

section "Uptime: disable systemd sleep mechanisms"
write_file /etc/systemd/sleep.conf.d/server.conf <<'EOF' || true
[Sleep]
AllowSuspend=no
AllowHibernation=no
AllowSuspendThenHibernate=no
AllowHybridSleep=no
EOF

section "Uptime: disable WiFi power-save (NetworkManager)"
write_file /etc/NetworkManager/conf.d/server-no-wifi-powersave.conf <<'EOF' && RELOAD_NM=1
[connection]
wifi.powersave = 2
EOF

section "Uptime: disable USB autosuspend"
write_file /etc/udev/rules.d/99-server-no-usb-autosuspend.rules <<'EOF' && RELOAD_UDEV=1
# Keep USB devices awake for server reliability.
ACTION=="add", SUBSYSTEM=="usb", TEST=="power/control", ATTR{power/control}="on"
EOF

section "Uptime: UPower (do not shut down on low battery)"
write_file /etc/UPower/UPower.conf <<'EOF' || true
[UPower]
UsePercentageForPolicy=true
PercentageLow=20
PercentageCritical=5
PercentageAction=2
CriticalPowerAction=None
EOF

# ===========================================================================
# 2. GPU — keep the NVIDIA device warm for low-latency inference
# ===========================================================================
section "GPU: NVIDIA persistence daemon"
if systemctl list-unit-files nvidia-persistenced.service >/dev/null 2>&1; then
  if systemctl is-enabled nvidia-persistenced.service >/dev/null 2>&1; then
    ok "nvidia-persistenced enabled"
  else
    systemctl enable nvidia-persistenced.service >/dev/null 2>&1 && changed "enabled nvidia-persistenced"
  fi
  if systemctl is-active nvidia-persistenced.service >/dev/null 2>&1; then
    ok "nvidia-persistenced running"
  else
    systemctl start nvidia-persistenced.service >/dev/null 2>&1 && changed "started nvidia-persistenced" || warn "could not start nvidia-persistenced"
  fi
elif command -v nvidia-smi >/dev/null 2>&1; then
  nvidia-smi -pm 1 >/dev/null 2>&1 && ok "persistence mode set via nvidia-smi" || warn "nvidia-smi -pm 1 failed"
else
  warn "no NVIDIA GPU tooling found — skipping"
fi

# ===========================================================================
# 3. Kernel / network / memory tuning
# ===========================================================================
section "Kernel: sysctl server tuning"
# Enable BBR if available (best-effort; module may be built-in).
modprobe tcp_bbr 2>/dev/null || true
if sysctl net.ipv4.tcp_available_congestion_control 2>/dev/null | grep -qw bbr; then
  BBR_QDISC=$'net.core.default_qdisc = fq\nnet.ipv4.tcp_congestion_control = bbr'
else
  BBR_QDISC='# bbr unavailable on this kernel; leaving congestion control default'
fi
if write_file /etc/sysctl.d/99-server.conf <<EOF
# Managed by scripts/configure-server.sh

# Memory: prefer RAM over swap on a 128GB box, but keep swap as a safety net.
vm.swappiness = 10
vm.vfs_cache_pressure = 50
vm.dirty_background_ratio = 5
vm.dirty_ratio = 15
# Allow services (vLLM, Docker) to map many memory regions.
vm.max_map_count = 1048576

# Reboot automatically a few seconds after a kernel panic/oops (unattended box).
kernel.panic = 10
kernel.panic_on_oops = 1

# Network throughput / connection backlog for a busy API host.
net.core.somaxconn = 4096
net.core.netdev_max_backlog = 16384
net.core.rmem_max = 16777216
net.core.wmem_max = 16777216
net.ipv4.tcp_max_syn_backlog = 8192
net.ipv4.tcp_fastopen = 3
net.ipv4.tcp_mtu_probing = 1
net.ipv4.ip_local_port_range = 1024 65535
$BBR_QDISC

# More inotify watches for dev tooling / file watchers.
fs.inotify.max_user_watches = 524288
fs.inotify.max_user_instances = 1024
EOF
then RELOAD_SYSCTL=1; fi

# ===========================================================================
# 4. File-descriptor / process limits
# ===========================================================================
section "Limits: raise nofile/nproc (PAM)"
write_file /etc/security/limits.d/99-server.conf <<'EOF' || true
# Managed by scripts/configure-server.sh
*    soft  nofile  1048576
*    hard  nofile  1048576
root soft  nofile  1048576
root hard  nofile  1048576
*    soft  nproc   unlimited
*    hard  nproc   unlimited
EOF

section "Limits: systemd default limits"
if write_file /etc/systemd/system.conf.d/99-server-limits.conf <<'EOF'
[Manager]
DefaultLimitNOFILE=1048576:1048576
DefaultLimitNPROC=infinity
DefaultLimitMEMLOCK=infinity
EOF
then RELOAD_SYSTEMD=1; fi

# ===========================================================================
# 5. Logging — persistent, size-capped journald
# ===========================================================================
section "Logging: persistent + capped journald"
if write_file /etc/systemd/journald.conf.d/99-server.conf <<'EOF'
[Journal]
Storage=persistent
Compress=yes
SystemMaxUse=1G
SystemKeepFree=2G
SystemMaxFileSize=128M
MaxRetentionSec=1month
EOF
then RELOAD_JOURNALD=1; fi

# ===========================================================================
# 6. Clock — keep NTP sync on
# ===========================================================================
section "Time: enable NTP synchronization"
if timedatectl show -p NTP --value 2>/dev/null | grep -qx yes; then
  ok "NTP already enabled"
else
  timedatectl set-ntp true >/dev/null 2>&1 && changed "enabled NTP sync" || warn "could not enable NTP"
fi

# ===========================================================================
# 7. Automatic security updates
# ===========================================================================
section "Updates: unattended-upgrades (security only)"
if [[ "${SERVER_SKIP_APT:-0}" == "1" ]]; then
  warn "SERVER_SKIP_APT=1 — skipping package install"
elif ! command -v apt-get >/dev/null 2>&1; then
  warn "apt-get not found — skipping"
else
  if ! dpkg -s unattended-upgrades >/dev/null 2>&1; then
    DEBIAN_FRONTEND=noninteractive apt-get update -qq >/dev/null 2>&1 || warn "apt-get update failed"
    if DEBIAN_FRONTEND=noninteractive apt-get install -y -qq unattended-upgrades >/dev/null 2>&1; then
      changed "installed unattended-upgrades"
    else
      warn "failed to install unattended-upgrades"
    fi
  else
    ok "unattended-upgrades installed"
  fi

  if dpkg -s unattended-upgrades >/dev/null 2>&1; then
    write_file /etc/apt/apt.conf.d/20auto-upgrades <<'EOF' || true
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
APT::Periodic::Download-Upgradeable-Packages "1";
APT::Periodic::AutocleanInterval "7";
EOF
    if [[ "${SERVER_AUTO_REBOOT:-0}" == "1" ]]; then
      REBOOT_LINE="Unattended-Upgrade::Automatic-Reboot \"true\";"
      REBOOT_TIME_LINE="Unattended-Upgrade::Automatic-Reboot-Time \"${SERVER_AUTO_REBOOT_TIME:-04:00}\";"
    else
      REBOOT_LINE="Unattended-Upgrade::Automatic-Reboot \"false\";"
      REBOOT_TIME_LINE="// Unattended-Upgrade::Automatic-Reboot-Time \"04:00\";"
    fi
    write_file /etc/apt/apt.conf.d/52server-unattended-upgrades <<EOF || true
// Managed by scripts/configure-server.sh
Unattended-Upgrade::Allowed-Origins {
    "\${distro_id}:\${distro_codename}";
    "\${distro_id}:\${distro_codename}-security";
    "\${distro_id}ESMApps:\${distro_codename}-apps-security";
    "\${distro_id}ESM:\${distro_codename}-infra-security";
};
Unattended-Upgrade::Remove-Unused-Kernel-Packages "true";
Unattended-Upgrade::Remove-Unused-Dependencies "true";
$REBOOT_LINE
$REBOOT_TIME_LINE
EOF
    systemctl enable --now unattended-upgrades >/dev/null 2>&1 || true
  fi
fi

# ===========================================================================
# 8. fail2ban — throttle SSH brute force
# ===========================================================================
section "Security: fail2ban (sshd jail)"
if [[ "${SERVER_SKIP_APT:-0}" == "1" ]]; then
  warn "SERVER_SKIP_APT=1 — skipping package install"
elif ! command -v apt-get >/dev/null 2>&1; then
  warn "apt-get not found — skipping"
else
  if ! dpkg -s fail2ban >/dev/null 2>&1; then
    DEBIAN_FRONTEND=noninteractive apt-get install -y -qq fail2ban >/dev/null 2>&1 \
      && changed "installed fail2ban" || warn "failed to install fail2ban"
  else
    ok "fail2ban installed"
  fi
  if dpkg -s fail2ban >/dev/null 2>&1; then
    # Never ban loopback, LAN, or Tailscale CGNAT ranges.
    if write_file /etc/fail2ban/jail.d/99-server.local <<EOF
[DEFAULT]
ignoreip = 127.0.0.1/8 ::1 10.0.0.0/8 172.16.0.0/12 192.168.0.0/16 100.64.0.0/10
bantime  = 1h
findtime = 10m
maxretry = 5
backend  = systemd

[sshd]
enabled = true
port    = ${SSH_PORT}
EOF
    then
      systemctl enable fail2ban >/dev/null 2>&1 || true
      systemctl restart fail2ban >/dev/null 2>&1 && changed "reloaded fail2ban" || warn "fail2ban restart failed"
    else
      systemctl enable --now fail2ban >/dev/null 2>&1 || true
    fi
  fi
fi

# ===========================================================================
# 9. Firewall — deny inbound by default, but keep remote access open
# ===========================================================================
section "Firewall: ufw (SSH + NoMachine + Tailscale always allowed)"
if [[ "${SERVER_SKIP_FIREWALL:-0}" == "1" ]]; then
  warn "SERVER_SKIP_FIREWALL=1 — leaving firewall untouched"
elif ! command -v ufw >/dev/null 2>&1; then
  warn "ufw not installed — skipping"
else
  ufw default deny incoming  >/dev/null 2>&1 || true
  ufw default allow outgoing >/dev/null 2>&1 || true
  # Always trust the Tailscale interface (mesh VPN).
  ufw allow in on tailscale0 >/dev/null 2>&1 || true
  ufw allow 41641/udp        >/dev/null 2>&1 || true   # Tailscale direct connections
  # Keep the GUI remote desktop reachable.
  ufw allow "${NOMACHINE_PORT}/tcp" >/dev/null 2>&1 || true
  # SSH: lock to Tailscale only if requested, otherwise allow from anywhere.
  if [[ "${SERVER_SSH_TAILSCALE_ONLY:-0}" == "1" ]]; then
    ufw delete allow "${SSH_PORT}/tcp" >/dev/null 2>&1 || true
    ufw delete allow OpenSSH           >/dev/null 2>&1 || true
    warn "SSH restricted to tailscale0 only (port ${SSH_PORT} closed on other interfaces)"
  else
    ufw allow "${SSH_PORT}/tcp" >/dev/null 2>&1 || true
  fi
  if ufw status 2>/dev/null | grep -q "Status: active"; then
    ufw reload >/dev/null 2>&1 || true
    ok "ufw active (rules synced)"
  else
    ufw --force enable >/dev/null 2>&1 && changed "enabled ufw" || warn "could not enable ufw"
  fi
fi

# ===========================================================================
# Apply / reload changed services
# ===========================================================================
section "Applying changes"
if [[ $RELOAD_SYSTEMD -eq 1 ]]; then systemctl daemon-reexec >/dev/null 2>&1 && changed "reloaded systemd manager"; fi
if [[ $RELOAD_SYSCTL  -eq 1 ]]; then sysctl --system >/dev/null 2>&1 && changed "applied sysctl"; fi
if [[ $RELOAD_LOGIND  -eq 1 ]]; then systemctl restart systemd-logind >/dev/null 2>&1 && changed "restarted systemd-logind"; fi
if [[ $RELOAD_JOURNALD -eq 1 ]]; then systemctl restart systemd-journald >/dev/null 2>&1 && changed "restarted systemd-journald"; fi
if [[ $RELOAD_NM -eq 1 ]]; then
  systemctl reload NetworkManager >/dev/null 2>&1 || systemctl restart NetworkManager >/dev/null 2>&1 || true
  changed "reloaded NetworkManager"
fi
if [[ $RELOAD_UDEV -eq 1 ]]; then
  udevadm control --reload-rules >/dev/null 2>&1 || true
  udevadm trigger --subsystem-match=usb >/dev/null 2>&1 || true
  changed "reloaded udev rules"
fi

# ===========================================================================
# Summary
# ===========================================================================
section "Done"
if [[ $CHANGES -eq 0 ]]; then
  printf '   %sAlready fully configured — nothing changed.%s\n' "$C_GREEN" "$C_RESET"
else
  printf '   %s%d change(s) applied.%s\n' "$C_GREEN" "$CHANGES" "$C_RESET"
fi
echo
echo "Sleep targets : $(systemctl is-enabled sleep.target suspend.target hibernate.target hybrid-sleep.target 2>/dev/null | tr '\n' ' ')"
echo "Swappiness    : $(cat /proc/sys/vm/swappiness 2>/dev/null)"
echo "NTP synced    : $(timedatectl show -p NTPSynchronized --value 2>/dev/null)"
if command -v ufw >/dev/null 2>&1; then echo "Firewall      : $(ufw status 2>/dev/null | head -1 | sed 's/Status: //')"; fi
if command -v nvidia-smi >/dev/null 2>&1; then
  echo "GPU persist   : $(nvidia-smi --query-gpu=persistence_mode --format=csv,noheader 2>/dev/null | head -1)"
fi
