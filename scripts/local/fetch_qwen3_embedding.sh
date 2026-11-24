#!/usr/bin/env bash
# Download the exact Qwen3-Embedding-0.6B assets the laptop indexer needs:
#
#   models/qwen3-embedding/Qwen3-Embedding-0.6B-Q8_0.gguf   llama.cpp weights
#   models/qwen3-embedding/tokenizer.json                    exact tokenizer
#
# Q8_0 (~0.65 GB) is the sweet spot for an RTX 2050 with 4 GB of VRAM: it keeps
# embedding quality while leaving room for KV/compute buffers plus the desktop
# compositor. Use Q4_K_M only if another workload already occupies VRAM.
#
# Usage:
#   scripts/local/fetch_qwen3_embedding.sh [destination]
#   HF_ENDPOINT=https://hf-mirror.com scripts/local/fetch_qwen3_embedding.sh
#
# Requires `huggingface-cli` (pip install huggingface_hub) and network access.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DEST="${1:-$ROOT/models/qwen3-embedding}"
GGUF="Qwen3-Embedding-0.6B-Q8_0.gguf"
REPO_GGUF="Qwen/Qwen3-Embedding-0.6B-GGUF"
REPO_TOKENIZER="Qwen/Qwen3-Embedding-0.6B"

command -v huggingface-cli >/dev/null 2>&1 || {
  echo "huggingface-cli not found. Install it with:" >&2
  echo "  python -m pip install --user huggingface_hub" >&2
  exit 1
}

mkdir -p "$DEST"

echo "==> GGUF: $REPO_GGUF/$GGUF"
huggingface-cli download "$REPO_GGUF" "$GGUF" --local-dir "$DEST"

echo "==> tokenizer: $REPO_TOKENIZER/tokenizer.json"
huggingface-cli download "$REPO_TOKENIZER" tokenizer.json --local-dir "$DEST"

for file in "$DEST/$GGUF" "$DEST/tokenizer.json"; do
  if [[ ! -s "$file" ]]; then
    echo "missing or empty: $file" >&2
    exit 1
  fi
done

cat <<EOF

Ready:
  model:     $DEST/$GGUF
  tokenizer: $DEST/tokenizer.json

Start the local stack:
  docker compose -f docker-compose.yml -f docker-compose.local-indexer.yml \\
    up -d --build llama local-indexer local-ui

Dashboard: http://localhost:8090
EOF
