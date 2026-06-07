"""Shared constants — no logic, no imports, safe to import from anywhere."""

# Docker label used to detect when a running container's launch config is stale.
_CONFIG_HASH_LABEL = "spark-serve.config-hash"

# Model id vLLM advertises on /v1/models (used for readiness + warmup).
_SERVED_MODEL = "qwen3.6-35b"

# A small coding-shaped prompt to trigger CUDA-graph specialisation on warmup.
_WARMUP_PROMPT = (
    "def fibonacci(n: int) -> int:\n"
    "    if n <= 1:\n"
    "        return n\n"
    "    return fibonacci(n - 1) + fibonacci(n - 2)\n"
)

# Fallback native context window when a model's config.json can't be read.
_DEFAULT_NATIVE_CONTEXT = 32768

# Subdirectories that make up the vLLM torch/Triton compile cache.
_COMPILE_CACHE_SUBDIRS = (
    "triton",
    "torchinductor",
    "torch_compile_cache",
    "dummy_cache",
)
