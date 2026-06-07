"""Fail-fast prechecks run before the (slow) engine boot."""

from .cloudflare import precheck_cf_tunnel
from .console import ok, section
from .gpu import _check_gpu_memory, precheck_gpu_available
from .models import precheck_models


def run_prechecks(cfg, docker_cmd):
    """Validate config and dependencies before the (slow) engine boot."""
    section("Running prechecks (fail fast)")
    precheck_cf_tunnel(cfg)
    precheck_gpu_available(cfg, docker_cmd)
    if cfg.engine != "atlas":
        # Atlas pre-downloads its checkpoint just before launch (ensure_atlas_model),
        # and its image has no torch for the CUDA memory probe — skip vLLM-only checks.
        precheck_models(cfg)
        _check_gpu_memory(cfg, docker_cmd)
    ok(f"All prechecks passed — starting {'Atlas' if cfg.engine == 'atlas' else 'vLLM'}")
