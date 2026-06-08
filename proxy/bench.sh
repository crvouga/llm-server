#!/usr/bin/env bash
# bench.sh — backward-compatible wrapper for throughput benchmark.
#
# Prefer: python3 server_test/check_api.py --bench-only
#   or:   make bench
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

if ! command -v python3 >/dev/null; then
  echo "Missing: python3" >&2
  exit 1
fi

python3 -m pip install -q -r "${REPO_ROOT}/server_test/requirements.txt"

exec python3 "${REPO_ROOT}/server_test/check_api.py" --bench-only "$@"
