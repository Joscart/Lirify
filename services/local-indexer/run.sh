#!/usr/bin/env bash
# local-indexer entrypoint: gRPC only (the local dashboard is the HTTP surface).
set -euo pipefail

export SERVE_ONLY="${SERVE_ONLY:-0}"
export GRPC_INPROCESS="${GRPC_INPROCESS:-0}"
export GRPC_PORT="${GRPC_PORT:-50051}"

exec python local_server.py
