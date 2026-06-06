#!/usr/bin/env bash
set -euo pipefail

if [[ "$(uname -s)" != "Linux" ]]; then
  echo "This script is for Linux (the headless target) only." >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ "${EUID}" -ne 0 ]]; then
  exec sudo -E "${BASH_SOURCE[0]}" "$@"
fi

echo "== Step 1/2: SSH + Tailscale =="
"${SCRIPT_DIR}/setup-target-headless-remote.sh"

echo
echo "== Step 2/2: Remote desktop (xrdp + XFCE) =="
"${SCRIPT_DIR}/setup-target-remote-desktop.sh"

echo
echo "Target setup complete. Commit REMOTE-ACCESS.md, then on your Mac run:"
echo "  ./scripts/setup-mac-all-remote.sh"
