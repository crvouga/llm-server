#!/usr/bin/env bash
# =============================================================================
#  spark-serve.sh — vLLM + DFlash + Cloudflare Tunnel for DGX Spark / GB10
#  Idempotent: safe to run multiple times. Re-running restarts stale services.
# =============================================================================
set -euo pipefail

# ── Colour helpers ────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

info()    { echo -e "${CYAN}[•]${RESET} $*"; }
ok()      { echo -e "${GREEN}[✓]${RESET} $*"; }
warn()    { echo -e "${YELLOW}[!]${RESET} $*"; }
die()     { echo -e "${RED}[✗]${RESET} $*" >&2; exit 1; }
section() { echo -e "\n${BOLD}━━━  $*  ━━━${RESET}"; }

# ── Configuration — edit these ────────────────────────────────────────────────
: "${HF_TOKEN:=""}"                          # Hugging Face token (required for gated models)
: "${CF_TUNNEL_TOKEN:=""}"                   # Cloudflare Tunnel token (from Zero Trust dashboard)
: "${MODEL:="Qwen/Qwen3-Coder-Next-FP8"}"   # Primary model to serve
: "${DFLASH_DRAFTER:="z-lab/Qwen3-Coder-Next-DFlash"}"  # DFlash drafter model
: "${MODEL_DIR:="$HOME/.cache/huggingface"}" # Model cache dir (reuses LM Studio downloads)
: "${VLLM_PORT:=8000}"                       # vLLM API port
: "${MAX_MODEL_LEN:=65536}"                  # Context window (lower = faster, more concurrent)
: "${GPU_MEMORY_UTILIZATION:=0.85}"          # Leave headroom for KV cache
: "${MAX_NUM_SEQS:=16}"                      # Max concurrent requests
: "${CONTAINER_NAME:="vllm-dflash"}"
: "${VLLM_IMAGE:="ghcr.io/aeon-7/vllm-dflash:latest"}"

# ── Validate required config ──────────────────────────────────────────────────
section "Checking configuration"

[[ -z "$CF_TUNNEL_TOKEN" ]] && die \
  "CF_TUNNEL_TOKEN is not set.\n  Get it from: https://one.dash.cloudflare.com → Networks → Tunnels → Create tunnel → Docker\n  Then run: CF_TUNNEL_TOKEN=<token> $0"

[[ -z "$HF_TOKEN" ]] && warn \
  "HF_TOKEN not set — fine for public models, required for gated ones.\n  Set with: HF_TOKEN=hf_... $0"

ok "Config looks good"
info "  Model:       $MODEL"
info "  DFlash:      $DFLASH_DRAFTER"
info "  Context:     $MAX_MODEL_LEN tokens"
info "  Concurrency: $MAX_NUM_SEQS max sequences"
info "  Port:        $VLLM_PORT"
info "  Model dir:   $MODEL_DIR"

# ── Check architecture (GB10 is aarch64) ─────────────────────────────────────
ARCH=$(uname -m)
[[ "$ARCH" != "aarch64" ]] && warn "Expected aarch64 (GB10), got $ARCH — some optimisations may not apply"

# ── Dependency: Docker ────────────────────────────────────────────────────────
section "Checking Docker"

if ! command -v docker &>/dev/null; then
  info "Docker not found — installing..."
  curl -fsSL https://get.docker.com | sudo sh
  sudo usermod -aG docker "$USER"
  warn "Added $USER to docker group. If this is the first install, log out and back in, then re-run."
  # Continue using sudo docker for this session
  DOCKER="sudo docker"
else
  ok "Docker $(docker --version | cut -d' ' -f3 | tr -d ',')"
  DOCKER="docker"
fi

# Verify NVIDIA container toolkit
if ! $DOCKER run --rm --runtime nvidia \
  -e NVIDIA_VISIBLE_DEVICES=all \
  -e NVIDIA_DRIVER_CAPABILITIES=compute,utility \
  nvidia/cuda:12.0.0-base-ubuntu22.04 nvidia-smi &>/dev/null; then
  info "NVIDIA container toolkit not found — installing..."
  curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
  curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
    | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
    | sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
  sudo apt-get update -qq
  sudo apt-get install -y -q nvidia-container-toolkit
  sudo nvidia-ctk runtime configure --runtime=docker
  sudo mkdir -p /etc/cdi
  sudo nvidia-ctk cdi generate --output=/etc/cdi/nvidia.yaml 2>/dev/null || true
  sudo systemctl restart docker
  ok "NVIDIA container toolkit installed"
else
  ok "NVIDIA container toolkit working"
fi

# ── Dependency: cloudflared ───────────────────────────────────────────────────
section "Checking cloudflared"

if ! command -v cloudflared &>/dev/null; then
  info "cloudflared not found — installing for $ARCH..."
  case "$ARCH" in
    aarch64) CF_ARCH="arm64" ;;
    x86_64)  CF_ARCH="amd64" ;;
    *)        die "Unsupported arch for cloudflared: $ARCH" ;;
  esac
  TMP=$(mktemp)
  curl -fsSL "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-${CF_ARCH}.deb" -o "$TMP"
  sudo dpkg -i "$TMP"
  rm -f "$TMP"
  ok "cloudflared $(cloudflared --version)"
else
  ok "cloudflared $(cloudflared --version)"
fi

# ── Dependency: git-lfs (for model downloads) ─────────────────────────────────
section "Checking git-lfs"

if ! command -v git-lfs &>/dev/null; then
  info "git-lfs not found — installing..."
  sudo apt-get install -y -q git-lfs
  git lfs install
  ok "git-lfs installed"
else
  ok "git-lfs $(git-lfs version | cut -d'/' -f2)"
fi

# ── Pull vLLM DFlash image ────────────────────────────────────────────────────
section "Pulling vLLM DFlash container image"

info "Image: $VLLM_IMAGE"
info "This may take several minutes on first run (~9 GB)..."
$DOCKER pull "$VLLM_IMAGE"
ok "Image ready"

# ── Model download ────────────────────────────────────────────────────────────
section "Checking models"

mkdir -p "$MODEL_DIR"

download_model_if_missing() {
  local repo="$1"
  local local_name
  local_name=$(echo "$repo" | tr '/' '_')
  local target_dir="$MODEL_DIR/hub/models--$(echo "$repo" | tr '/' '--')"

  if [[ -d "$target_dir" ]]; then
    ok "Model already cached: $repo"
    return
  fi

  info "Downloading $repo..."
  info "(this can take a while — the FP8 model is ~40 GB, the drafter ~4 GB)"

  $DOCKER run --rm \
    -v "$MODEL_DIR:/root/.cache/huggingface" \
    -e HF_TOKEN="${HF_TOKEN:-}" \
    -e HUGGING_FACE_HUB_TOKEN="${HF_TOKEN:-}" \
    python:3.11-slim bash -c "
      pip install -q huggingface_hub[hf_transfer] && \
      HF_HUB_ENABLE_HF_TRANSFER=1 python -c \"
from huggingface_hub import snapshot_download
snapshot_download('$repo', ignore_patterns=['*.pt', '*.bin'])
print('Done: $repo')
\"
    "
  ok "Downloaded: $repo"
}

download_model_if_missing "$MODEL"
download_model_if_missing "$DFLASH_DRAFTER"

# ── Stop stale vLLM container (idempotency) ───────────────────────────────────
section "Managing vLLM container"

if $DOCKER ps -a --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
  CURRENT_STATUS=$($DOCKER inspect --format='{{.State.Status}}' "$CONTAINER_NAME" 2>/dev/null || echo "gone")
  if [[ "$CURRENT_STATUS" == "running" ]]; then
    info "Stopping existing container '$CONTAINER_NAME'..."
    $DOCKER stop "$CONTAINER_NAME" >/dev/null
  fi
  info "Removing old container..."
  $DOCKER rm "$CONTAINER_NAME" >/dev/null
fi

# ── Start vLLM + DFlash container ─────────────────────────────────────────────
section "Starting vLLM + DFlash server"

info "Starting container (first request after boot takes ~30 s for CUDA graph capture)..."

$DOCKER run -d \
  --name "$CONTAINER_NAME" \
  --runtime nvidia \
  -e NVIDIA_VISIBLE_DEVICES=all \
  -e NVIDIA_DRIVER_CAPABILITIES=compute,utility \
  --network host \
  --ipc host \
  --ulimit memlock=-1:-1 \
  --restart unless-stopped \
  -v "$MODEL_DIR:/root/.cache/huggingface" \
  -e HF_TOKEN="${HF_TOKEN:-}" \
  -e HUGGING_FACE_HUB_TOKEN="${HF_TOKEN:-}" \
  -e MODEL_PATH="$MODEL" \
  -e DFLASH_DRAFTER="$DFLASH_DRAFTER" \
  -e DFLASH_NUM_SPEC_TOKENS=15 \
  -e MAX_MODEL_LEN="$MAX_MODEL_LEN" \
  -e MAX_NUM_SEQS="$MAX_NUM_SEQS" \
  -e MAX_NUM_BATCHED_TOKENS=32768 \
  -e GPU_MEMORY_UTILIZATION="$GPU_MEMORY_UTILIZATION" \
  -e ATTENTION_BACKEND=flash_attn \
  -e VLLM_PORT="$VLLM_PORT" \
  "$VLLM_IMAGE"

ok "Container '$CONTAINER_NAME' started"

# ── Wait for vLLM to be healthy ───────────────────────────────────────────────
section "Waiting for vLLM to be ready"

info "Waiting for /health endpoint (CUDA graph capture can take 5-10 min on first boot)..."
SECONDS_WAITED=0
MAX_WAIT=600  # 10 minutes

while true; do
  if curl -sf "http://localhost:${VLLM_PORT}/health" >/dev/null 2>&1; then
    ok "vLLM is healthy after ${SECONDS_WAITED}s"
    break
  fi

  if (( SECONDS_WAITED >= MAX_WAIT )); then
    die "vLLM did not become healthy after ${MAX_WAIT}s. Check logs:\n  docker logs $CONTAINER_NAME"
  fi

  if (( SECONDS_WAITED % 30 == 0 && SECONDS_WAITED > 0 )); then
    info "Still waiting... (${SECONDS_WAITED}s elapsed — CUDA graph capture in progress)"
  fi

  sleep 5
  (( SECONDS_WAITED += 5 ))
done

# Send warmup request so first real call doesn't pay the graph-specialisation cost
info "Warming up (sending 2 dummy requests)..."
for i in 1 2; do
  curl -sf "http://localhost:${VLLM_PORT}/v1/completions" \
    -H "Content-Type: application/json" \
    -d "{\"model\":\"$(basename $MODEL)\",\"prompt\":\"hi\",\"max_tokens\":1}" \
    >/dev/null 2>&1 || true
done
ok "Warmup done — server is at full speed"

# ── Start Cloudflare tunnel ───────────────────────────────────────────────────
section "Starting Cloudflare tunnel"

# Kill any existing tunnel for this token
pkill -f "cloudflared tunnel --no-autoupdate run --token" 2>/dev/null || true
sleep 1

# Run tunnel in background, redirect output to log file
CF_LOG="$HOME/.spark-serve/cloudflare-tunnel.log"
mkdir -p "$(dirname "$CF_LOG")"

nohup cloudflared tunnel --no-autoupdate run \
  --token "$CF_TUNNEL_TOKEN" \
  >"$CF_LOG" 2>&1 &
CF_PID=$!
echo "$CF_PID" > "$HOME/.spark-serve/cloudflared.pid"

# Wait for tunnel to connect
info "Waiting for Cloudflare tunnel to connect..."
sleep 5

if ! kill -0 "$CF_PID" 2>/dev/null; then
  die "cloudflared exited unexpectedly. Log:\n$(tail -20 "$CF_LOG")"
fi

# Extract the public URL from logs
CF_URL=""
for _ in $(seq 1 20); do
  CF_URL=$(grep -oE 'https://[a-zA-Z0-9.-]+\.trycloudflare\.com' "$CF_LOG" 2>/dev/null | head -1 || true)
  [[ -n "$CF_URL" ]] && break
  # Also check for named tunnel URL patterns
  CF_URL=$(grep -oE 'https://[a-zA-Z0-9.-]+\.cloudflare\.com' "$CF_LOG" 2>/dev/null | head -1 || true)
  [[ -n "$CF_URL" ]] && break
  sleep 2
done

ok "Cloudflare tunnel running (PID $CF_PID)"

# ── Write helper scripts ───────────────────────────────────────────────────────
section "Writing helper scripts"

HELPER_DIR="$HOME/.spark-serve"
mkdir -p "$HELPER_DIR"

# logs script
cat > "$HELPER_DIR/logs.sh" <<EOF
#!/usr/bin/env bash
# Show vLLM + tunnel logs side by side
echo "=== vLLM logs (last 50 lines) ==="
docker logs --tail 50 ${CONTAINER_NAME}
echo ""
echo "=== Cloudflare tunnel log (last 20 lines) ==="
tail -20 ${CF_LOG}
EOF
chmod +x "$HELPER_DIR/logs.sh"

# stop script
cat > "$HELPER_DIR/stop.sh" <<EOF
#!/usr/bin/env bash
echo "Stopping vLLM container..."
docker stop ${CONTAINER_NAME} 2>/dev/null || true
docker rm ${CONTAINER_NAME} 2>/dev/null || true
echo "Stopping Cloudflare tunnel..."
pkill -f "cloudflared tunnel --no-autoupdate run --token" 2>/dev/null || true
echo "Done."
EOF
chmod +x "$HELPER_DIR/stop.sh"

# status script
cat > "$HELPER_DIR/status.sh" <<EOF
#!/usr/bin/env bash
RED='\033[0;31m'; GREEN='\033[0;32m'; RESET='\033[0m'
echo "=== vLLM container ==="
docker ps --filter name=${CONTAINER_NAME} --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
echo ""
echo "=== Health check ==="
if curl -sf http://localhost:${VLLM_PORT}/health >/dev/null 2>&1; then
  echo -e "\${GREEN}● vLLM healthy on :${VLLM_PORT}\${RESET}"
else
  echo -e "\${RED}✗ vLLM not responding\${RESET}"
fi
echo ""
echo "=== Models available ==="
curl -s http://localhost:${VLLM_PORT}/v1/models | python3 -c "
import sys, json
d = json.load(sys.stdin)
for m in d.get('data', []):
    print(' •', m['id'])
" 2>/dev/null || echo "(server not ready)"
echo ""
echo "=== Cloudflare tunnel ==="
if kill -0 \$(cat ${HELPER_DIR}/cloudflared.pid 2>/dev/null) 2>/dev/null; then
  echo -e "\${GREEN}● Tunnel running\${RESET}"
else
  echo -e "\${RED}✗ Tunnel not running\${RESET}"
fi
EOF
chmod +x "$HELPER_DIR/status.sh"

ok "Helper scripts written to $HELPER_DIR/"

# ── Final summary ─────────────────────────────────────────────────────────────
section "🚀 Server is live"

echo ""
echo -e "  ${BOLD}Local API endpoint:${RESET}"
echo -e "    http://localhost:${VLLM_PORT}/v1"
echo ""
if [[ -n "$CF_URL" ]]; then
  echo -e "  ${BOLD}Public endpoint (Cloudflare):${RESET}"
  echo -e "    ${GREEN}${CF_URL}/v1${RESET}"
else
  echo -e "  ${BOLD}Public endpoint:${RESET}"
  echo -e "    Check your Cloudflare Zero Trust dashboard for the hostname."
  echo -e "    Tunnel log: $CF_LOG"
fi
echo ""
echo -e "  ${BOLD}Model:${RESET}     $MODEL"
echo -e "  ${BOLD}DFlash:${RESET}    $DFLASH_DRAFTER (k=15)"
echo -e "  ${BOLD}Context:${RESET}   $MAX_MODEL_LEN tokens"
echo ""
echo -e "  ${BOLD}Useful commands:${RESET}"
echo -e "    ${HELPER_DIR}/status.sh   — check health + models"
echo -e "    ${HELPER_DIR}/logs.sh     — tail logs"
echo -e "    ${HELPER_DIR}/stop.sh     — stop everything"
echo -e "    docker logs -f $CONTAINER_NAME"
echo ""
echo -e "  ${BOLD}Connect from your coding agent:${RESET}"
echo -e "    Base URL:  http://localhost:${VLLM_PORT}/v1  (local)"
if [[ -n "$CF_URL" ]]; then
  echo -e "               ${CF_URL}/v1  (remote)"
fi
echo -e "    API key:   not-required  (no auth configured)"
echo -e "    Model ID:  $(basename $MODEL)"
echo ""
warn "First real request may still take ~30s for CUDA graph specialisation on novel input shapes."
warn "Run 1-2 warmup requests before benchmarking."
echo ""