#!/usr/bin/env python3
"""Backward-compatible shim for smoke-only API checks.

Prefer: python3 server_test/check_api.py --smoke-only
"""

from __future__ import annotations

import sys

from check_api import main


def _smoke_argv(argv: list[str] | None) -> list[str]:
    args = list(argv or sys.argv[1:])
    if "--smoke-only" not in args and "--bench-only" not in args:
        args.insert(0, "--smoke-only")
    return args


if __name__ == "__main__":
    raise SystemExit(main(_smoke_argv(sys.argv[1:])))
