#!/usr/bin/env bash
# Regenerate gRPC code for BOTH the gateway and the microservice from the single
# proto source (proto/routerbench.proto). Run after editing the .proto:
#     bash scripts/gen_proto.sh
#
# It hides the long protoc paths and the post-generation import fixups so you
# never have to remember them. Set PYTHON=... to use a specific interpreter.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROTO_DIR="$ROOT/proto"
PROTO_FILE="routerbench.proto"
PY="${PYTHON:-python}"

gen() {
  # $1 = output dir, $2 = package path used in the import fixup
  local out="$1" pkg="$2"
  "$PY" -m grpc_tools.protoc -I "$PROTO_DIR" \
    --python_out="$out" --grpc_python_out="$out" \
    "$PROTO_DIR/$PROTO_FILE"
  # protoc emits a flat `import routerbench_pb2`; rewrite it to a package import
  # so the module works when imported as part of its package. perl -i is portable
  # across macOS and Linux (BSD vs GNU sed differ on -i).
  perl -i -pe "s/^import routerbench_pb2/from ${pkg} import routerbench_pb2/" \
    "$out/routerbench_pb2_grpc.py"
}

gen "$ROOT/gateway/gateway/_proto" "gateway._proto"
gen "$ROOT/services/routerbench/grpc_api" "grpc_api"

echo "Regenerated:"
echo "  - gateway/gateway/_proto/"
echo "  - services/routerbench/grpc_api/"
