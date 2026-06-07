# llm-server

Local LLM inference server (Atlas engine by default) with Cloudflare tunnel exposure, plus a Cloudflare Worker proxy that logs API usage.

## Layout

| Path | Purpose |
| --- | --- |
| [`server/`](server/) | Atlas / vLLM launcher (`server/server.py`) |
| [`proxy/`](proxy/) | Cloudflare Worker proxy + usage dashboard |
| [`remote-access/`](remote-access/) | Mac ↔ Linux remote control setup (SSH, Tailscale, NoMachine) |

## LLM server

Requires Docker, NVIDIA container toolkit, and Doppler (`doppler login` + `doppler setup`).

The launcher serves an OpenAI-compatible API over the Cloudflare tunnel. It defaults to the
**Atlas** engine (`avarok/atlas-gb10`, purpose-built for GB10/SM121) running
`Qwen/Qwen3.6-35B-A3B-FP8` with native fp8 KV cache, MTP speculative decoding, and a 128K
context window. The legacy **vLLM + DFlash** path is kept as a one-env-var fallback.

```bash
make server-start        # start the engine + tunnel (Atlas by default)
make server-stop         # stop engine container + tunnel
make server-free-ram     # reclaim RAM/GPU (LM Studio, Docker, page cache)
make server-metrics      # CPU/RAM/GPU/disk + LLM health snapshot
make server-tune         # sweep Atlas KV dtype x num-drafts x context for best decode tok/s
make logs                # tail container logs
make status              # check process + container

ENGINE=vllm make server-start    # use the legacy vLLM + DFlash engine instead
```

The launcher serves the OpenAI-compatible API publicly at `https://llm.chrisvouga.dev`.

### Development

```bash
make server-install   # one-time: install ruff + pyright + pytest (dev deps)
make server-check     # lint + typecheck server/ and tests/
```

### Engine selection & Atlas tuning

| Env var | Default | Purpose |
| --- | --- | --- |
| `ENGINE` | `atlas` | `atlas` or `vllm` |
| `ATLAS_MODEL` | `Qwen/Qwen3.6-35B-A3B-FP8` | HF model id (pre-downloaded to `~/.cache/huggingface` before launch) |
| `ATLAS_MAX_SEQ_LEN` | `131072` | Context window (128K) |
| `ATLAS_KV_CACHE_DTYPE` | `fp8` | `bf16` / `fp8` / `turbo8` / `nvfp4` / `turbo4` / `turbo3` |
| `ATLAS_NUM_DRAFTS` | `2` | MTP speculative depth (K); `ATLAS_NO_SPECULATIVE=1` to disable |
| `ATLAS_HIGH_SPEED_SWAP_DIR` | _(unset)_ | NVMe path for KV offload to push context toward 256K |

The public API model id is `atlas`. Expected single-stream speed is ~130-140 tok/s — the GB10
memory-bandwidth ceiling for a smart 35B-A3B model.

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
