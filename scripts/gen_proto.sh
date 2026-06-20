#!/usr/bin/env bash
# Regenerate gRPC code for BOTH the gateway and the microservice from the single
# proto source (proto/routerbench/v1/routerbench.proto). Run after editing the
# .proto:
#     bash scripts/gen_proto.sh
#
# The generated stubs land in an isolated, versioned subpackage on each side:
#     services/routerbench/grpc_api/_proto/routerbench/v1/
#     gateway/gateway/_proto/routerbench/v1/
# matching the proto package (routerbench.v1). protoc emits absolute imports
# between the generated modules; fix_proto_imports.py rewrites them to relative
# imports so each tree is a self-contained package (no sys.path assumptions, no
# perl). Set PYTHON=... to use a specific interpreter.
#
# buf governs the schema (lint + breaking-change detection) but does not generate
# here — see proto/buf.yaml.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROTO_DIR="$ROOT/proto"
PROTO_FILE="routerbench/v1/routerbench.proto"
PY="${PYTHON:-python}"

gen() {
  # $1 = the _proto package root to generate into
  local out="$1"
  rm -rf "$out"
  mkdir -p "$out"
  # -I PROTO_DIR makes the import path package-qualified (routerbench/v1/...), so
  # the output tree mirrors the proto package directory.
  "$PY" -m grpc_tools.protoc -I "$PROTO_DIR" \
    --python_out="$out" --grpc_python_out="$out" \
    "$PROTO_DIR/$PROTO_FILE"
  # protoc doesn't create package markers; add them down the generated tree so
  # the stubs import as grpc_api._proto.routerbench.v1 / gateway._proto....
  find "$out" -type d -exec touch {}/__init__.py \;
  # Absolute cross-file imports -> relative, so the tree is location-independent.
  "$PY" "$ROOT/scripts/fix_proto_imports.py" "$out"
}

gen "$ROOT/services/routerbench/grpc_api/_proto"
gen "$ROOT/gateway/gateway/_proto"

echo "Regenerated:"
echo "  - services/routerbench/grpc_api/_proto/routerbench/v1/"
echo "  - gateway/gateway/_proto/routerbench/v1/"
