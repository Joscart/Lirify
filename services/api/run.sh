#!/usr/bin/env bash
# Container entrypoint: REST + gRPC + the h2c mux in front of both.
set -euo pipefail

export PORT="${PORT:-8080}"
export HTTP_PORT="${HTTP_PORT:-8000}"
export GRPC_PORT="${GRPC_PORT:-50051}"

shutdown() {
  kill "${API_PID:-}" "${GRPC_PID:-}" "${CADDY_PID:-}" 2>/dev/null || true
}
trap shutdown INT TERM

echo "[lirify] starting REST on :${HTTP_PORT}"
uvicorn main:app --host 127.0.0.1 --port "${HTTP_PORT}" --proxy-headers --forwarded-allow-ips='*' &
API_PID=$!

echo "[lirify] starting gRPC (h2c) on :${GRPC_PORT}"
python -m grpc_server &
GRPC_PID=$!

echo "[lirify] starting h2c mux on :${PORT}"
caddy run --config /etc/caddy/Caddyfile --adapter caddyfile &
CADDY_PID=$!

# Exit (and let Cloud Run restart the revision) if any child dies.
set +e
wait -n
STATUS=$?
echo "[lirify] a child process exited with ${STATUS}; shutting down" >&2
shutdown
exit "${STATUS}"
