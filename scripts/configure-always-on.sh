#!/usr/bin/env bash
# Configure this machine to stay awake like a server (no suspend/hibernate).
# Run: sudo bash scripts/configure-always-on.sh
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root: sudo bash $0" >&2
  exit 1
fi

echo "==> Writing systemd logind drop-in..."
mkdir -p /etc/systemd/logind.conf.d
tee /etc/systemd/logind.conf.d/server.conf >/dev/null <<'EOF'
[Login]
# Keep the machine awake like a server — ignore all sleep triggers.
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

echo "==> Writing systemd sleep drop-in..."
mkdir -p /etc/systemd/sleep.conf.d
tee /etc/systemd/sleep.conf.d/server.conf >/dev/null <<'EOF'
[Sleep]
AllowSuspend=no
AllowHibernation=no
AllowSuspendThenHibernate=no
AllowHybridSleep=no
EOF

echo "==> Masking sleep/suspend/hibernate targets..."
systemctl mask sleep.target suspend.target hibernate.target hybrid-sleep.target suspend-then-hibernate.target

echo "==> Restarting systemd-logind..."
systemctl restart systemd-logind

TARGET_USER="${SUDO_USER:-${USER}}"
if [[ -n "${TARGET_USER}" && "${TARGET_USER}" != "root" ]]; then
  echo "==> Applying GNOME power settings for ${TARGET_USER}..."
  sudo -u "${TARGET_USER}" DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$(id -u "${TARGET_USER}")/bus" \
    gsettings set org.gnome.settings-daemon.plugins.power sleep-inactive-ac-type 'nothing' 2>/dev/null || true
  sudo -u "${TARGET_USER}" DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$(id -u "${TARGET_USER}")/bus" \
    gsettings set org.gnome.settings-daemon.plugins.power sleep-inactive-battery-type 'nothing' 2>/dev/null || true
  sudo -u "${TARGET_USER}" DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$(id -u "${TARGET_USER}")/bus" \
    gsettings set org.gnome.settings-daemon.plugins.power sleep-inactive-ac-timeout 0 2>/dev/null || true
  sudo -u "${TARGET_USER}" DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$(id -u "${TARGET_USER}")/bus" \
    gsettings set org.gnome.settings-daemon.plugins.power sleep-inactive-battery-timeout 0 2>/dev/null || true
  sudo -u "${TARGET_USER}" DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$(id -u "${TARGET_USER}")/bus" \
    gsettings set org.gnome.desktop.session idle-delay 0 2>/dev/null || true
  sudo -u "${TARGET_USER}" DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$(id -u "${TARGET_USER}")/bus" \
    gsettings set org.gnome.desktop.screensaver idle-activation-enabled false 2>/dev/null || true
  sudo -u "${TARGET_USER}" DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$(id -u "${TARGET_USER}")/bus" \
    gsettings set org.gnome.desktop.screensaver lock-enabled false 2>/dev/null || true
fi

echo "==> Done. Verify with: systemd-analyze cat-config systemd/logind.conf"
echo "    Sleep targets should show 'masked' in: systemctl status sleep.target"
