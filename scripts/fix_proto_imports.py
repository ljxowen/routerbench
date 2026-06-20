"""Rewrite protoc's cross-file imports to relative imports.

The Python protoc plugin emits *absolute* imports between generated modules based
on the proto package path, e.g. in routerbench_pb2_grpc.py:

    from routerbench.v1 import routerbench_pb2 as ...

That only resolves if the generated root is on sys.path — which is brittle across
run contexts (local cwd vs. the Docker WORKDIR). Rewriting the import to relative:

    from . import routerbench_pb2 as ...

makes the generated tree a self-contained package that imports correctly no
matter where it's mounted (grpc_api._proto.routerbench.v1, gateway._proto....).

This is the job the `protoletariat` tool does; it's inlined here so codegen needs
no extra dependency and works offline. Unlike the old `perl -i` one-liner it is
cross-platform and generalizes to multiple protos/packages.

Usage:
    python scripts/fix_proto_imports.py <generated_root_dir>
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

# Matches a generated cross-file import, e.g.
#   from routerbench.v1 import routerbench_pb2 as routerbench_dot_v1_dot...__pb2
# Captures: (dotted package) (module) (optional " as alias").
_IMPORT_RE = re.compile(
    r"^from (?P<pkg>[\w.]+) import (?P<mod>\w+_pb2(?:_grpc)?)(?P<alias> as \S+)?\s*$"
)


def _relative_import(from_parts: tuple[str, ...], to_parts: tuple[str, ...]) -> str:
    """Build a relative import prefix from one package to another.

    from_parts/to_parts are the package paths (relative to the generated root) of
    the importing file's directory and the target module's directory.
    """
    common = 0
    while (
        common < len(from_parts)
        and common < len(to_parts)
        and from_parts[common] == to_parts[common]
    ):
        common += 1
    # One leading dot for "current package", plus one per level we walk up.
    dots = "." * (len(from_parts) - common + 1)
    tail = ".".join(to_parts[common:])
    return dots + tail if tail else dots


def fix_tree(root: Path) -> int:
    gen_files = sorted(root.rglob("*_pb2.py")) + sorted(root.rglob("*_pb2_grpc.py"))
    # Dotted package path -> set is implicit; we just need membership: which
    # packages were generated, so we know which imports are intra-tree.
    gen_pkgs = {".".join(f.parent.relative_to(root).parts) for f in gen_files}

    changed = 0
    for f in gen_files:
        from_parts = f.parent.relative_to(root).parts
        lines = f.read_text().splitlines()
        touched = False
        for i, line in enumerate(lines):
            m = _IMPORT_RE.match(line)
            if not m or m["pkg"] not in gen_pkgs:
                # Not a generated cross-file import (e.g. google.protobuf.*): leave it.
                continue
            rel = _relative_import(from_parts, tuple(m["pkg"].split(".")))
            lines[i] = f"from {rel} import {m['mod']}{m['alias'] or ''}"
            touched = True
        if touched:
            f.write_text("\n".join(lines) + "\n")
            changed += 1
    return changed


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: python scripts/fix_proto_imports.py <generated_root_dir>")
    n = fix_tree(Path(sys.argv[1]))
    print(f"  rewrote imports in {n} file(s) under {sys.argv[1]}")
