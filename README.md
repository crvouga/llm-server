# llm-server

Local LLM inference server (Atlas + Qwen3-Coder-Next) with Cloudflare tunnel exposure, plus a Cloudflare Worker proxy that logs API usage.

## Layout

| Path | Purpose |
| --- | --- |
| [`server/`](server/) | Atlas launcher (`server/server.py`) |
| [`proxy/`](proxy/) | Cloudflare Worker proxy + usage dashboard |
| [`remote-access/`](remote-access/) | Mac ↔ Linux remote control setup (SSH, Tailscale, NoMachine) |

## LLM server

Requires Docker, NVIDIA container toolkit, and Doppler (`doppler login` + `doppler setup`).

The launcher serves an OpenAI-compatible API over the Cloudflare tunnel using the **Atlas**
engine (`avarok/atlas-gb10`, purpose-built for GB10/SM121) running
`Qwen/Qwen3-Coder-Next-NVFP4` with fp8 KV cache, MTP speculative decoding, and a 128K
context window.

```bash
make server-start        # start Atlas + tunnel
make server-stop         # stop Atlas container + tunnel
make server-metrics      # CPU/RAM/GPU/disk + Atlas health snapshot
make logs                # tail container logs
make status              # check process + container
```

The launcher serves the OpenAI-compatible API publicly at `https://llm.chrisvouga.dev`.

### Development

```bash
make server-install   # one-time: install ruff + pyright + pytest (dev deps)
make server-check     # lint + typecheck server/ and tests/
```

### Atlas tuning

| Env var | Default | Purpose |
| --- | --- | --- |
| `ATLAS_MODEL` | `Qwen/Qwen3-Coder-Next-NVFP4` | HF model id (pre-downloaded to `~/.cache/huggingface` before launch) |
| `ATLAS_MAX_SEQ_LEN` | `131072` | Context window (128K) |
| `ATLAS_KV_CACHE_DTYPE` | `fp8` | `bf16` / `fp8` / `turbo8` / `nvfp4` / `turbo4` / `turbo3` |
| `ATLAS_NUM_DRAFTS` | `2` | MTP speculative depth (K); `ATLAS_NO_SPECULATIVE=1` to disable |
| `ATLAS_FORCE_RESTART` | _(unset)_ | Set to `1` to recreate the container on next start |

The public API model id is `atlas`. Expected single-stream speed is ~80+ tok/s on GB10 with
Qwen3-Coder-Next.

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
