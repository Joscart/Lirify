#!/usr/bin/env bash
# Regenerate every gRPC stub from proto/lirify.proto.
#
#   ./scripts/gen_proto.sh          # generate python + go + typescript
#   ./scripts/gen_proto.sh --check  # generate into a temp dir and fail on drift
#
# Requirements:
#   protoc >= 3.21, grpcio-tools (python fallback), protoc-gen-go,
#   protoc-gen-go-grpc, npm (for @grpc/proto-loader types we only need the .proto)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROTO_DIR="$ROOT/proto"
PROTO="$PROTO_DIR/lirify.proto"
PY_OUT="$ROOT/services/api/app/lirifypb"
GO_OUT="$ROOT/services/go-ui/internal/lirifypb"
TS_OUT="$ROOT/services/web/src/generated"
CHECK="${1:-}"

mkdir -p "$PY_OUT" "$GO_OUT"

if [[ "$CHECK" == "--check" ]]; then
  TMP="$(mktemp -d)"
  trap 'rm -rf "$TMP"' EXIT
  PY_OUT="$TMP/py"
  GO_OUT="$TMP/go"
  TS_OUT="$TMP/ts"
  mkdir -p "$PY_OUT" "$GO_OUT" "$TS_OUT"
fi

PYTHON_BIN="${PYTHON:-python3}"

# Generated headers embed the generator versions. CI pins protoc 36.1,
# grpcio-tools 1.66.2, protoc-gen-go 1.36.6 and protoc-gen-go-grpc 1.5.1; using a
# different protoc locally produces a header-only diff that fails --check.
EXPECTED_PROTOC="36.1"
if command -v protoc >/dev/null 2>&1; then
  ACTUAL_PROTOC="$(protoc --version | awk '{print $2}')"
  echo "protoc: ${ACTUAL_PROTOC}"
  if [[ "$ACTUAL_PROTOC" != "$EXPECTED_PROTOC" ]]; then
    echo "    warning: CI pins protoc ${EXPECTED_PROTOC}; a mismatch only changes" >&2
    echo "    the generated version header, not the stubs themselves." >&2
  fi
fi

echo "==> python stubs"
if "$PYTHON_BIN" -c "import grpc_tools.protoc" >/dev/null 2>&1; then
  "$PYTHON_BIN" -m grpc_tools.protoc \
    -I "$PROTO_DIR" \
    --python_out="$PY_OUT" \
    --pyi_out="$PY_OUT" \
    --grpc_python_out="$PY_OUT" \
    "$PROTO"
else
  protoc -I "$PROTO_DIR" \
    --python_out="$PY_OUT" \
    --pyi_out="$PY_OUT" \
    --grpc_python_out="$PY_OUT" \
    "$PROTO"
fi
touch "$PY_OUT/__init__.py"
# grpc_tools emits `import lirify_pb2`; make the package importable both ways.
sed -i 's/^import lirify_pb2 as/from . import lirify_pb2 as/' "$PY_OUT/lirify_pb2_grpc.py"

echo "==> go stubs"
protoc -I "$PROTO_DIR" \
  --go_out="$GO_OUT" --go_opt=paths=source_relative \
  --go-grpc_out="$GO_OUT" --go-grpc_opt=paths=source_relative \
  "$PROTO"

echo "==> go helper: strip the deep package path protoc creates for go_package"
find "$GO_OUT" -name '*.pb.go' -exec sh -c '
  for f; do
    if [ "$(dirname "$f")" != "'"$GO_OUT"'" ]; then
      mv "$f" "'"$GO_OUT"'/$(basename "$f")"
    fi
  done
' sh {} +

echo "==> typescript types"
TS_GEN="$ROOT/services/web/node_modules/@grpc/proto-loader/build/bin/proto-loader-gen-types.js"
if [ -f "$TS_GEN" ]; then
  # Run from the repository root with a repo-relative proto path: the generator
  # writes "// Original file: <path>" into every file, and an absolute path makes
  # the output differ between machines (which is what broke CI).
  ( cd "$ROOT" && node "$TS_GEN" \
      --longs=String --enums=String --defaults --oneofs \
      --grpcLib=@grpc/grpc-js \
      --outDir="$TS_OUT" proto/lirify.proto )

  # Belt and braces: normalise the header no matter how the generator was run.
  find "$TS_OUT" -name '*.ts' -exec sed -i -E \
    's|^// Original file: .*/proto/lirify\.proto$|// Original file: proto/lirify.proto|' {} +
else
  echo "    skipped: run 'npm install' in services/web first" >&2
fi

if [[ "$CHECK" == "--check" ]]; then
  echo "==> diffing generated stubs"
  diff -ru -x '__pycache__' -x '*.pyc' "$ROOT/services/web/src/generated" "$TS_OUT" || {
    echo "typescript stubs are stale: run ./scripts/gen_proto.sh" >&2
    exit 1
  }
  diff -ru -x '__pycache__' -x '*.pyc' "$ROOT/services/api/app/lirifypb" "$PY_OUT" || {
    echo "python stubs are stale: run ./scripts/gen_proto.sh" >&2
    exit 1
  }
  diff -ru -x '__pycache__' -x '*.pyc' "$ROOT/services/go-ui/internal/lirifypb" "$GO_OUT" || {
    echo "go stubs are stale: run ./scripts/gen_proto.sh" >&2
    exit 1
  }
  echo "stubs up to date"
fi
