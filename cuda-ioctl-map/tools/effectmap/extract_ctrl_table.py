#!/usr/bin/env python3
"""
extract_ctrl_table.py — build the canonical NVIDIA RM control-command table.

Reads the vendored SDK headers in refs/open-gpu-kernel-modules and emits one
row per NVxxxx_CTRL_CMD_* define:

    {name, cmd, class_hex, family, header, params_struct, params_size,
     is_get, is_set, is_internal}

`params_size` is not parsed out of the C source. It is measured by compiling a
generated probe against the real headers and printing sizeof(). That makes the
size exact, including padding and alignment, and it removes a whole class of
hand-parser bugs.

Structs that do not exist (the derived name is a convention, not a rule) are
pruned by iteratively compiling and reading gcc's own error output, then
recompiling. `params_size` is null for those rows.

Usage:
    python3 tools/effectmap/extract_ctrl_table.py \
        --sdk  refs/open-gpu-kernel-modules/src/common/sdk/nvidia/inc \
        --out  tools/effectmap/out/ctrl_table.json

Caveat recorded in every output file: the vendored SDK is tagged 610.43.02
while hulk runs driver 555.42.02. These are 610 tables. The size oracle
(sweep_controls.c) measures the drift against the shipped binary.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

# #define NV2080_CTRL_CMD_GPU_GET_INFO_V2 (0x20800102U) /* finn: ... */
CMD_RE = re.compile(
    r"^#define\s+(NV[0-9A-Fa-f]{2,4}_CTRL_CMD_[A-Z0-9_]+)\s+\(?(0x[0-9A-Fa-f]+)U?\)?",
    re.MULTILINE,
)

# Typedef declaration sites, used to pre-filter candidates before compiling.
# Both forms occur:  "} NAME;"   and   "typedef OTHER NAME;"
TYPEDEF_CLOSE_RE = re.compile(r"^\s*\}\s*([A-Z][A-Z0-9_]+)\s*;", re.MULTILINE)
TYPEDEF_ALIAS_RE = re.compile(
    r"^\s*typedef\s+(?:struct\s+|union\s+)?[A-Za-z_][A-Za-z0-9_]*\s+([A-Z][A-Z0-9_]+)\s*;",
    re.MULTILINE,
)

# gcc tells us which typedefs do not exist. Read its output rather than guess.
# sizeof() on a name that is not a type gives "undeclared", not "unknown type name".
UNKNOWN_RE = re.compile(r"unknown type name ['‘]([A-Za-z0-9_]+)['’]")
UNDECLARED_RE = re.compile(r"['‘]([A-Za-z0-9_]+)['’] undeclared")
INCOMPLETE_RE = re.compile(r"invalid application of 'sizeof' to incomplete type ['‘]([A-Za-z0-9_ ]+)['’]")

MAX_PRUNE_ROUNDS = 12


def derive_params_struct(cmd_name: str) -> str:
    """NV2080_CTRL_CMD_GPU_GET_INFO_V2 -> NV2080_CTRL_GPU_GET_INFO_V2_PARAMS."""
    return cmd_name.replace("_CTRL_CMD_", "_CTRL_", 1) + "_PARAMS"


def scan_headers(ctrl_dir: Path) -> tuple[list[dict], list[str], set[str]]:
    """
    Collect every control-command define under ctrl/.
    Returns (rows, headers, declared_typedefs).
    """
    headers = sorted(p for p in ctrl_dir.rglob("*.h"))
    seen: dict[str, dict] = {}
    declared: set[str] = set()

    for hdr in headers:
        text = hdr.read_text(encoding="utf-8", errors="replace")
        rel = str(hdr.relative_to(ctrl_dir.parent))
        declared.update(TYPEDEF_CLOSE_RE.findall(text))
        declared.update(TYPEDEF_ALIAS_RE.findall(text))
        for m in CMD_RE.finditer(text):
            name, cmd_hex = m.group(1), m.group(2)
            # *_PARAMS_MESSAGE_ID is the FINN message tag, not a command. It
            # matches the same pattern and its value is a small ordinal, so it
            # collides with real low-numbered commands if left in.
            if name.endswith("_MESSAGE_ID"):
                continue
            cmd = int(cmd_hex, 16)
            if name in seen:
                continue  # first definition wins; duplicates are re-exports
            family = name.split("_CTRL_CMD_", 1)[0]
            seen[name] = {
                "name": name,
                "cmd": cmd,
                "cmd_hex": f"0x{cmd:08X}",
                # RM routes a control by the high 16 bits = the object class.
                "class_hex": f"0x{(cmd >> 16) & 0xFFFF:04X}",
                "family": family,
                "header": rel,
                "params_struct": derive_params_struct(name),
                "params_size": None,
                "is_get": "_GET" in name,
                "is_set": "_SET" in name,
                "is_internal": "_INTERNAL_" in name,
            }

    rel_headers = [str(h.relative_to(ctrl_dir.parent)) for h in headers]
    return sorted(seen.values(), key=lambda r: r["cmd"]), rel_headers, declared


def measure_sizes(
    rows: list[dict], sdk: Path, headers: list[str], declared: set[str]
) -> dict[str, int]:
    """
    Compile a probe that prints sizeof() for every candidate params struct.
    Prune the structs gcc rejects, recompile, repeat. Returns {struct: size}.

    The `declared` pre-filter keeps the compile loop to one or two rounds; each
    round costs about 40 s because the probe includes all 203 ctrl headers.
    """
    candidates = sorted({r["params_struct"] for r in rows} & declared)
    dropped: set[str] = set()

    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        src, exe = tdp / "probe.c", tdp / "probe"

        for round_no in range(1, MAX_PRUNE_ROUNDS + 1):
            live = [c for c in candidates if c not in dropped]
            if not live:
                return {}

            lines = ["#include <stdio.h>"]
            lines += [f'#include "{h}"' for h in headers]
            lines.append("int main(void){")
            for c in live:
                lines.append(f'    printf("{c},%zu\\n", sizeof({c}));')
            lines.append("    return 0;\n}")
            src.write_text("\n".join(lines), encoding="utf-8")

            proc = subprocess.run(
                ["gcc", f"-I{sdk}", "-fmax-errors=0", "-w", "-o", str(exe), str(src)],
                capture_output=True,
                text=True,
            )
            if proc.returncode == 0:
                out = subprocess.run([str(exe)], capture_output=True, text=True, check=True)
                sizes: dict[str, int] = {}
                for ln in out.stdout.splitlines():
                    if "," in ln:
                        k, v = ln.rsplit(",", 1)
                        sizes[k] = int(v)
                print(
                    f"[extract] sizeof measured for {len(sizes)}/{len(candidates)} structs "
                    f"after {round_no} round(s); {len(dropped)} pruned",
                    file=sys.stderr,
                )
                return sizes

            bad = set(UNKNOWN_RE.findall(proc.stderr)) | set(UNDECLARED_RE.findall(proc.stderr))
            for frag in INCOMPLETE_RE.findall(proc.stderr):
                bad.add(frag.replace("struct ", "").strip())
            bad &= set(candidates)
            if not bad:
                print("[extract] gcc failed but named no prunable type:", file=sys.stderr)
                print(proc.stderr[-3000:], file=sys.stderr)
                raise SystemExit(1)
            dropped |= bad
            print(f"[extract] round {round_no}: pruned {len(bad)} missing structs", file=sys.stderr)

    raise SystemExit(f"[extract] did not converge in {MAX_PRUNE_ROUNDS} rounds")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sdk", type=Path, required=True, help="…/sdk/nvidia/inc")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    sdk = args.sdk.resolve()
    ctrl_dir = sdk / "ctrl"
    if not ctrl_dir.is_dir():
        raise SystemExit(f"no ctrl/ under {sdk}")

    rows, headers, declared = scan_headers(ctrl_dir)
    print(
        f"[extract] {len(rows)} control commands in {len(headers)} headers; "
        f"{len(declared)} typedefs declared",
        file=sys.stderr,
    )

    sizes = measure_sizes(rows, sdk, headers, declared)
    for r in rows:
        r["params_size"] = sizes.get(r["params_struct"])

    sized = sum(1 for r in rows if r["params_size"] is not None)
    doc = {
        "_provenance": {
            "sdk_path": str(sdk),
            "sdk_version": "610.43.02 (vendored submodule tag)",
            "warning": (
                "Sizes come from the 610.43.02 open SDK headers. hulk runs the "
                "proprietary 555.42.02 module. Validate with the size oracle "
                "before trusting any row."
            ),
            "commands_total": len(rows),
            "commands_with_size": sized,
        },
        "commands": rows,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(doc, indent=1), encoding="utf-8")
    print(f"[extract] wrote {args.out}  ({sized}/{len(rows)} sized)", file=sys.stderr)


if __name__ == "__main__":
    main()
