# llm-server

Local LLM inference server (Atlas + Qwen3-Coder-Next) with Cloudflare tunnel exposure, plus a Cloudflare Worker proxy that logs API usage.

## Layout

| Path | Purpose |
| --- | --- |
| [`server/`](server/) | Atlas launcher (`server/server.py`) |
| [`proxy/`](proxy/) | Cloudflare Worker proxy + usage dashboard |
| [`remote-access/`](remote-access/) | Mac ↔ Linux remote control setup (SSH, Tailscale, NoMachine) |

## LLM server

### Hardware

Inference runs on an **ASUS Ascent GX10 AI Supercomputer** (NVIDIA DGX Spark class):

| | |
| --- | --- |
| **System** | ASUS Ascent GX10 AI Supercomputer, stackable chassis |
| **Platform** | DGX Spark · DGX OS |
| **SoC** | NVIDIA GB10 Superchip (SM121) |
| **Memory** | 128 GB LPDDR5x |
| **Storage** | 1 TB PCIe Gen4 NVMe SSD |
| **Network** | Wi-Fi 7, Bluetooth 5.4 |
| **Agentic AI** | Agentic AI ready; supports OpenClaw, NemoClaw |

Requires Docker, NVIDIA container toolkit, and the secret store (`vault login` + `vault setup --project personal --config dev`).

The launcher serves an OpenAI-compatible API over the Cloudflare tunnel using the **Atlas**
engine (`avarok/atlas-gb10`, purpose-built for GB10/SM121) running
`RedHatAI/Qwen3-Coder-Next-NVFP4` with fp8 KV cache, MTP speculative decoding, and a 128K
context window. Hybrid reasoning is **off by default** for agentic coding latency; clients
can opt in per request.

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
make api-check        # smoke tests + throughput benchmark (default proxy)
make server-test      # smoke tests only
make bench            # throughput benchmark only
```

`make api-check` validates harness compatibility (models, streaming, tool calling) and
reports decode tok/s and TTFT. Override the target with `LLM_BASE_URL=http://localhost:8888`
or legacy `BENCH_URL`. Use `CHECK_ARGS='--json'` for machine-readable output.

### Atlas tuning

| Env var | Default | Purpose |
| --- | --- | --- |
| `ATLAS_MODEL` | `RedHatAI/Qwen3-Coder-Next-NVFP4` | HF model id (pre-downloaded to `~/.cache/huggingface` before launch) |
| `ATLAS_MAX_SEQ_LEN` | `131072` | Context window (128K) |
| `ATLAS_MAX_BATCH_SIZE` | `6` | Concurrent sequences (128K fp8 KV on GB10; raise only with shorter context) |
| `ATLAS_KV_CACHE_DTYPE` | `fp8` | `bf16` / `fp8` / `turbo8` / `nvfp4` / `turbo4` / `turbo3` |
| `ATLAS_NUM_DRAFTS` | `2` | MTP speculative depth (K); `ATLAS_NO_SPECULATIVE=1` to disable |
| `ATLAS_MTP_QUANTIZATION` | `nvfp4` | MTP draft-head quant (required for qwen3_next MoE + speculative) |
| `ATLAS_OOM_GUARD_MB` | `1024` | Headroom Atlas keeps free on GPU during inference |
| `ATLAS_SSM_CACHE_SLOTS` | `0` | GDN/SSM snapshot slots (`0` saves memory on qwen3_next) |
| `ATLAS_GPU_MEM_UTIL` | `0.88` | Fraction of GPU memory Atlas may use |
| `ATLAS_MAX_THINKING_BUDGET` | _(unset)_ | Cap reasoning tokens when thinking is enabled (`0` = omit flag) |
| `ATLAS_FORCE_RESTART` | _(unset)_ | Set to `1` to recreate the container on next start |

The public API model id is `atlas`. Expected single-stream speed is ~80+ tok/s on GB10 with
Qwen3-Coder-Next in non-thinking mode.

### Thinking mode

Hybrid reasoning models emit a long internal chain before the first answer token. For
agentic coding (many sequential tool calls), that dominates wall-clock latency.

- **Proxy default:** chat requests without explicit thinking intent get
  `chat_template_kwargs.enable_thinking: false` injected before forwarding to Atlas.
- **Client opt-in:** pass `reasoning_effort`, `enable_thinking: true`,
  `chat_template_kwargs.enable_thinking: true`, or `/think` in the last user message.
- **Server cap:** `ATLAS_MAX_THINKING_BUDGET` bounds reasoning length when thinking is on.

`make api-check` benchmarks production (non-thinking) mode by default. Use
`--thinking` or `LLM_BENCH_THINKING=1` to measure thinking latency on demand.

## Proxy

Transparent forwarder to Atlas with request logging. For `/v1/chat/completions` and
`/v1/messages`, the proxy injects `enable_thinking: false` unless the client opts into
reasoning (see **Thinking mode** above).

Requires [Bun](https://bun.sh) and secrets from `secret/personal/<config>` (`DATABASE_URL`, `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID`).

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
