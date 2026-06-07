"""Coloured console output. The only module everything else is allowed to import."""

import sys
from typing import NoReturn

# ── ANSI colours ──────────────────────────────────────────────────────────────
R = "\033[0;31m"
G = "\033[0;32m"
Y = "\033[1;33m"
C = "\033[0;36m"
B = "\033[1m"
X = "\033[0m"


def info(msg):
    print(f"{C}[•]{X} {msg}", flush=True)


def ok(msg):
    print(f"{G}[✓]{X} {msg}", flush=True)


def warn(msg):
    print(f"{Y}[!]{X} {msg}", flush=True)


def err(msg):
    print(f"{R}[✗]{X} {msg}", file=sys.stderr, flush=True)


def section(msg):
    print(f"\n{B}━━━  {msg}  ━━━{X}", flush=True)


def die(msg) -> NoReturn:
    err(msg)
    sys.exit(1)
