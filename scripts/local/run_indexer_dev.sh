#!/usr/bin/env bash
# Run the local indexer from source (CPU torch image) with the gRPC and admin
# ports published on loopback only. Source files are mounted over /app, so edits
# to core.py/pipeline.py/db_admin.py take effect on the next container restart.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
IMAGE="${IMAGE:-lirify-local-indexer}"
NAME="${NAME:-lirify-local-indexer-dev}"
PORT_GRPC="${PORT_GRPC:-50052}"
PORT_ADMIN="${PORT_ADMIN:-8082}"
VOLUME="${VOLUME:-lirify_hf_cache}"

docker image inspect "$IMAGE" >/dev/null 2>&1 || {
  echo "image $IMAGE is missing; build it first:" >&2
  echo "  docker compose -f docker-compose.yml -f docker-compose.local-indexer.yml build local-indexer" >&2
  exit 1
}

docker volume inspect "$VOLUME" >/dev/null 2>&1 || docker volume create "$VOLUME" >/dev/null
docker rm -f "$NAME" >/dev/null 2>&1 || true

docker run -d --name "$NAME" \
  --env-file "$ROOT/.env" \
  -e GRPC_PORT=50051 \
  -e ADMIN_PORT=8080 \
  -e EMBEDDING_MODEL="${EMBEDDING_MODEL:-Qwen/Qwen3-Embedding-0.6B}" \
  -e EMBEDDING_DIM=1024 \
  -e QDRANT_COLLECTION="${QDRANT_COLLECTION:-lirify_lyrics_qwen3}" \
  -e PUBLISH_ON_INDEX="${PUBLISH_ON_INDEX:-1}" \
  -e LOAD_ON_START="${LOAD_ON_START:-0}" \
  -p "127.0.0.1:${PORT_GRPC}:50051" \
  -p "127.0.0.1:${PORT_ADMIN}:8080" \
  -v "$ROOT/services/local-indexer:/app" \
  -v "$ROOT/services/api/app/lirifypb:/app/lirifypb:ro" \
  -v "$VOLUME:/root/.cache/huggingface" \
  --restart unless-stopped \
  "$IMAGE" >/dev/null

echo "container: $NAME"
echo "gRPC:      127.0.0.1:${PORT_GRPC}"
echo "admin:     127.0.0.1:${PORT_ADMIN} (/db/health, /db/overview)"
echo "logs:      docker logs -f $NAME"
