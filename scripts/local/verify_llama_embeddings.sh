#!/usr/bin/env bash
# Verify the local Qwen3-Embedding-0.6B server end to end.
#
#   scripts/local/verify_llama_embeddings.sh [base_url]
#
# Defaults to http://localhost:8081 (compose maps host 8081 -> llama 8080).
# Checks:
#   1. /health answers;
#   2. /v1/embeddings returns one 1024-dim vector per input;
#   3. the returned vectors are L2-normalised (Qwen3 embedding contract);
#   4. peak GPU memory used during a batch stays below the RTX 2050's 4096 MiB.
#
# This script never downloads anything and never needs root. Run it while the
# local compose stack is up.
set -euo pipefail

BASE="${1:-http://localhost:8081}"
BASE="${BASE%/}"
PYTHON="${PYTHON:-python3}"

command -v "$PYTHON" >/dev/null 2>&1 || {
  echo "python3 is required" >&2
  exit 1
}

echo "==> health: $BASE/health"
curl -fsS "$BASE/health" >/dev/null
echo "    ok"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
SAMPLES="$TMP/samples.txt"
PEAK_LOG="$TMP/vram.log"
: >"$PEAK_LOG"

# Eight realistic lyric chunks: enough to exercise the client's default batch
# (LLAMA_EMBED_BATCH=8) without turning this check into an indexing run.
cat >"$SAMPLES" <<'EOF'
I walked the long way home tonight to clear my head
Las calles de la ciudad me recuerdan a ti
Je cherche encore les mots que je n'ai jamais dits
Die Sterne stehen still und warten auf den Morgen
Cammino da solo sotto questo cielo grigio
Eu guardo o mar e lembro de tudo que ficou
夜の風が街の灯りを揺らしている
I keep the radio on just to hear your voice again
EOF

sampler_pid=""
if command -v nvidia-smi >/dev/null 2>&1; then
  (
    while :; do
      nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits 2>/dev/null || true
      sleep 0.2
    done
  ) >"$PEAK_LOG" &
  sampler_pid=$!
fi

echo "==> POST $BASE/v1/embeddings (8 inputs)"
"$PYTHON" - "$BASE" "$SAMPLES" <<'PY'
import json
import sys
import urllib.request

base, samples_path = sys.argv[1], sys.argv[2]
texts = [line.rstrip("\n") for line in open(samples_path, encoding="utf-8") if line.strip()]
request = urllib.request.Request(
    f"{base}/v1/embeddings",
    data=json.dumps({"model": "qwen3-embedding-0.6b", "input": texts}).encode("utf-8"),
    headers={"Content-Type": "application/json"},
    method="POST",
)
with urllib.request.urlopen(request, timeout=300) as response:
    payload = json.load(response)

rows = payload.get("data") or []
if len(rows) != len(texts):
    raise SystemExit(f"expected {len(texts)} embeddings, got {len(rows)}")
dims = {len(row.get("embedding") or []) for row in rows}
if dims != {1024}:
    raise SystemExit(f"expected 1024-dim embeddings, got {sorted(dims)}")
norms = [
    sum(float(value) * float(value) for value in row["embedding"]) ** 0.5
    for row in rows
]
if any(abs(norm - 1.0) > 1e-3 for norm in norms):
    raise SystemExit(f"vectors are not L2-normalised: {norms}")
print(f"    ok: {len(rows)} vectors x {dims.pop()} dims, norms {min(norms):.4f}..{max(norms):.4f}")
PY

if [[ -n "$sampler_pid" ]]; then
  kill "$sampler_pid" 2>/dev/null || true
  wait "$sampler_pid" 2>/dev/null || true
  peak="$(awk 'NF && $1 ~ /^[0-9]+$/ { if ($1 > m) m = $1 } END { print m + 0 }' "$PEAK_LOG")"
  total="$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits | head -n1 | tr -d ' ')"
  used_before="$(head -n1 "$PEAK_LOG" | tr -d ' ')"
  echo "==> VRAM: total=${total} MiB, idle=${used_before:-?} MiB, peak=${peak} MiB"
  echo "    (if llama-server runs on CPU, this is the idle host baseline; start the cuda image for a real sample)"
  if [[ "$total" =~ ^[0-9]+$ ]] && (( peak > total - 512 )); then
    echo "    WARNING: peak leaves less than 512 MiB headroom for the compositor" >&2
    echo "    lower --ctx-size/--ubatch-size or switch to Q4_K_M" >&2
    exit 1
  fi
  echo "    ok: at least 512 MiB headroom"
else
  echo "==> nvidia-smi not found: skipping the VRAM sample"
fi

echo "==> all checks passed"
