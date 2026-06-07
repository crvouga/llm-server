"""Generate the ~/.spark-serve/*.sh convenience scripts (status/logs/stop)."""

from pathlib import Path

from .cloudflare import _cf_public_url
from .console import ok, section


def write_helpers(cfg):
    section("Writing helper scripts")
    d = cfg.helper_dir
    cf_log = d / "cloudflare-tunnel.log"
    d.mkdir(parents=True, exist_ok=True)

    label = "Atlas" if cfg.engine == "atlas" else "vLLM"
    # Atlas serves the OpenAI API but has no dedicated /health route.
    health_path = "/v1/models" if cfg.engine == "atlas" else "/health"

    (d / "logs.sh").write_text(
        f"#!/usr/bin/env bash\n"
        f'echo "=== {label} (last 50 lines) ==="\n'
        f"docker logs --tail 50 {cfg.container_name}\n"
        f'echo ""\n'
        f'echo "=== Cloudflare tunnel (last 20 lines) ==="\n'
        f"tail -20 {cf_log}\n"
    )
    # spark/helpers.py -> spark -> server -> repo root
    root = Path(__file__).resolve().parent.parent.parent
    (d / "stop.sh").write_text(
        f"#!/usr/bin/env bash\n"
        f"exec python3 \"{root}/server/server.py\" --stop\n"
    )
    (d / "stop-hard.sh").unlink(missing_ok=True)
    (d / "status.sh").write_text(
        f"#!/usr/bin/env bash\n"
        f"G='\\033[0;32m'; R='\\033[0;31m'; Y='\\033[1;33m'; X='\\033[0m'\n"
        f"docker ps --filter name={cfg.container_name} --format 'table {{{{.Names}}}}\\t{{{{.Status}}}}'\n"
        f"curl -sf http://localhost:{cfg.vllm_port}{health_path} >/dev/null 2>&1 "
        f'&& echo -e "${{G}}● {label} healthy:{cfg.vllm_port}${{X}}" '
        f'|| echo -e "${{R}}✗ {label} not responding${{X}}"\n'
        f"curl -s http://localhost:{cfg.vllm_port}/v1/models "
        f"| python3 -c \"import sys,json; [print('  •', m['id']) for m in json.load(sys.stdin).get('data',[])]\" "
        f"2>/dev/null || echo '(not ready)'\n"
        f'if [ -f "{d}/cloudflared.pid" ] && kill -0 "$(cat "{d}/cloudflared.pid")" 2>/dev/null; then\n'
        f'  echo -e "${{G}}● tunnel running${{X}}"\n'
        f"else\n"
        f'  echo -e "${{R}}✗ tunnel not running${{X}}"\n'
        f"fi\n"
        f"curl -sf {_cf_public_url(cfg)}{health_path} >/dev/null 2>&1 "
        f'&& echo -e "${{G}}● public: {_cf_public_url(cfg)}${{X}}" '
        f'|| echo -e "${{Y}}! public: {_cf_public_url(cfg)} (not reachable yet)${{X}}"\n'
    )
    for f in d.glob("*.sh"):
        f.chmod(0o755)
    ok(f"Helpers written to {d}/")
