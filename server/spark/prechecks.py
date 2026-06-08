"""Fail-fast prechecks run before the (slow) engine boot."""

from .cloudflare import precheck_cf_tunnel
from .console import ok, section
from .gpu import precheck_gpu_available


def run_prechecks(cfg, docker_cmd):
    section("Running prechecks (fail fast)")
    precheck_cf_tunnel(cfg)
    precheck_gpu_available(cfg, docker_cmd)
    ok("All prechecks passed — starting Atlas")
