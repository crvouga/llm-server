"""Generate the ~/.spark-serve/*.sh convenience scripts (status/logs/stop)."""

from pathlib import Path

from .cloudflare import _cf_public_url
from .console import ok, section
from .runtime import write_runtime_state


def write_helpers(cfg):
    section("Writing helper scripts")
    d = cfg.helper_dir
    cf_log = d / "cloudflare-tunnel.log"
    d.mkdir(parents=True, exist_ok=True)

    docker = " ".join(cfg.docker_cmd)

    (d / "logs.sh").write_text(
        f"#!/usr/bin/env bash\n"
        f'echo "=== Atlas (last 50 lines) ==="\n'
        f"{docker} logs --tail 50 {cfg.container_name}\n"
        f'echo ""\n'
        f'echo "=== Cloudflare tunnel (last 20 lines) ==="\n'
        f"tail -20 {cf_log}\n"
    )
    root = Path(__file__).resolve().parent.parent.parent
    (d / "stop.sh").write_text(
        f"#!/usr/bin/env bash\n"
        f"exec python3 \"{root}/server/server.py\" --stop\n"
    )
    (d / "stop-hard.sh").unlink(missing_ok=True)
    (d / "status.sh").write_text(
        f"#!/usr/bin/env bash\n"
        f"G='\\033[0;32m'; R='\\033[0;31m'; Y='\\033[1;33m'; X='\\033[0m'\n"
        f"{docker} ps --filter name={cfg.container_name} --format 'table {{{{.Names}}}}\\t{{{{.Status}}}}'\n"
        f"curl -sf http://localhost:{cfg.atlas_port}/v1/models >/dev/null 2>&1 "
        f'&& echo -e "${{G}}● Atlas healthy:{cfg.atlas_port}${{X}}" '
        f'|| echo -e "${{R}}✗ Atlas not responding${{X}}"\n'
        f"curl -s http://localhost:{cfg.atlas_port}/v1/models "
        f"| python3 -c \"import sys,json; [print('  •', m['id']) for m in json.load(sys.stdin).get('data',[])]\" "
        f"2>/dev/null || echo '(not ready)'\n"
        f'if [ -f "{d}/cloudflared.pid" ]; then\n'
        f'  tunnel_pid="$(cat "{d}/cloudflared.pid" 2>/dev/null || true)"\n'
        f'  tunnel_state=""\n'
        f'  if [ -n "$tunnel_pid" ] && kill -0 "$tunnel_pid" 2>/dev/null; then\n'
        f'    tunnel_state="$(awk \'{{print $3}}\' "/proc/$tunnel_pid/stat" 2>/dev/null || true)"\n'
        f'  fi\n'
        f'  if [ "$tunnel_state" != "" ] && [ "$tunnel_state" != "Z" ]; then\n'
        f'    echo -e "${{G}}● tunnel running (pid $tunnel_pid)${{X}}"\n'
        f'  else\n'
        f'    echo -e "${{R}}✗ tunnel not running${{X}}"\n'
        f'  fi\n'
        f"else\n"
        f'  echo -e "${{R}}✗ tunnel not running${{X}}"\n'
        f"fi\n"
        f"curl -sf {_cf_public_url(cfg)}/v1/models >/dev/null 2>&1 "
        f'&& echo -e "${{G}}● public: {_cf_public_url(cfg)}${{X}}" '
        f'|| echo -e "${{Y}}! public: {_cf_public_url(cfg)} (not reachable yet)${{X}}"\n'
    )
    for f in d.glob("*.sh"):
        f.chmod(0o755)
    write_runtime_state(cfg)
    ok(f"Helpers written to {d}/")
