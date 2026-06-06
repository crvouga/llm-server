#!/usr/bin/env bash
set -euo pipefail

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This script is for macOS only." >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "== Step 1/2: Tailscale + SSH client =="
"${SCRIPT_DIR}/setup-mac-controller.sh"

echo
echo "== Step 2/2: Remote desktop client =="
"${SCRIPT_DIR}/setup-mac-remote-desktop.sh"

echo
echo "Mac setup complete. Sign in to Tailscale, then verify:"
echo "  ./scripts/verify-mac-remote-access.sh --desktop"
