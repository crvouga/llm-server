"""Subprocess helper. `run` raises on non-zero exit (check=True)."""

import subprocess


def run(cmd, **kwargs):
    return subprocess.run(cmd, check=True, **kwargs)
