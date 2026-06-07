# llm-server

Local vLLM inference server with Cloudflare tunnel exposure, plus a Cloudflare Worker proxy that logs API usage.

## Layout

| Path | Purpose |
| --- | --- |
| [`server/`](server/) | vLLM + DFlash launcher (`server/server.py`) |
| [`proxy/`](proxy/) | Cloudflare Worker proxy + usage dashboard |
| [`remote-access/`](remote-access/) | Mac ↔ Linux remote control setup (SSH, Tailscale, NoMachine) |

## LLM server

Requires Docker, NVIDIA container toolkit, and Doppler (`doppler login` + `doppler setup`).

```bash
make server-start   # start vLLM + tunnel
make server-stop    # stop everything
make server-free-ram   # reclaim RAM/GPU (LM Studio, Docker, page cache)
make server-metrics    # CPU/RAM/GPU/disk + LLM health snapshot
make logs     # tail container logs
make status   # check process + container
```

## Proxy

Requires [Bun](https://bun.sh) and Doppler secrets (`DATABASE_URL`, `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID`).

```bash
make proxy-install
make proxy-dev     # local wrangler dev
make proxy-check   # type-check
make proxy-deploy  # deploy to Cloudflare Workers
make proxy-db      # run database migrations
```

See [`proxy/README.md`](proxy/README.md) for architecture and SQL examples.

## Remote access

Set up a headless Linux box to be controlled from a Mac.

```bash
# On Linux target (once):
sudo ./remote-access/setup-target.sh
git add remote-access/REMOTE-ACCESS.md && git commit -m "Add remote access handoff" && git push

# On Mac (once, after git pull):
make remote-setup-mac
# or: ./remote-access/setup-controller.sh
```

Verify connectivity: `make remote-verify`
