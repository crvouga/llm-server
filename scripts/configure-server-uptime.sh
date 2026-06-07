#!/usr/bin/env bash
# Configure this machine for server-like uptime: no sleep, suspend, or hibernate.
# Requires root. Idempotent — safe to re-run.
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root: sudo $0" >&2
  exit 1
fi

echo "==> Masking systemd sleep targets"
systemctl mask sleep.target suspend.target hibernate.target hybrid-sleep.target

echo "==> Configuring systemd-logind (ignore lid/idle/suspend keys)"
install -d /etc/systemd/logind.conf.d
cat > /etc/systemd/logind.conf.d/server.conf <<'EOF'
[Login]
HandleLidSwitch=ignore
HandleLidSwitchExternalPower=ignore
HandleLidSwitchDocked=ignore
HandleSuspendKey=ignore
HandleHibernateKey=ignore
HandleSuspendKeyLongPress=ignore
HandleHibernateKeyLongPress=ignore
IdleAction=ignore
StopIdleSessionSec=infinity
EOF

echo "==> Disabling systemd sleep"
install -d /etc/systemd/sleep.conf.d
cat > /etc/systemd/sleep.conf.d/server.conf <<'EOF'
[Sleep]
AllowSuspend=no
AllowHibernation=no
AllowSuspendThenHibernate=no
AllowHybridSleep=no
EOF

echo "==> Disabling WiFi power save (NetworkManager)"
install -d /etc/NetworkManager/conf.d
cat > /etc/NetworkManager/conf.d/server-no-wifi-powersave.conf <<'EOF'
[connection]
wifi.powersave = 2
EOF

echo "==> Disabling USB autosuspend"
install -d /etc/udev/rules.d
cat > /etc/udev/rules.d/99-server-no-usb-autosuspend.rules <<'EOF'
# Keep USB devices awake for server reliability.
ACTION=="add", SUBSYSTEM=="usb", TEST=="power/control", ATTR{power/control}="on"
EOF

echo "==> Disabling UPower critical battery shutdown"
install -d /etc/UPower
cat > /etc/UPower/UPower.conf <<'EOF'
[UPower]
UsePercentageForPolicy=true
PercentageLow=20
PercentageCritical=5
PercentageAction=2
CriticalPowerAction=None
EOF

echo "==> Reloading services"
systemctl restart systemd-logind
systemctl reload NetworkManager 2>/dev/null || systemctl restart NetworkManager 2>/dev/null || true
systemctl restart upower 2>/dev/null || true
udevadm control --reload-rules
udevadm trigger --subsystem-match=usb

echo "==> Done. Sleep targets:"
systemctl is-enabled sleep.target suspend.target hibernate.target hybrid-sleep.target
