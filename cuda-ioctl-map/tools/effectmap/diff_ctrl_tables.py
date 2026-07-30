#!/usr/bin/env python3
"""
diff_ctrl_tables.py — compare params_size across two ctrl_table.json extractions
(e.g. driver 555.42.02 vs the vendored 610.43.02 SDK) to find struct-layout
drift that the size oracle (sweep_controls.c) would otherwise have to discover
one live ioctl at a time.

Usage:
    python3 tools/effectmap/diff_ctrl_tables.py ctrl_table_555.json ctrl_table_610.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def load(path: str) -> dict[str, dict]:
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    return {r["cmd_hex"]: r for r in doc["commands"]}


def main() -> None:
    if len(sys.argv) != 3:
        print(f"usage: {sys.argv[0]} table_a.json table_b.json", file=sys.stderr)
        sys.exit(2)

    a = load(sys.argv[1])
    b = load(sys.argv[2])
    a_name, b_name = Path(sys.argv[1]).stem, Path(sys.argv[2]).stem

    common = sorted(set(a) & set(b))
    only_a = sorted(set(a) - set(b))
    only_b = sorted(set(b) - set(a))

    size_diff = []
    newly_sized = []   # size known in b, unknown in a (or vice versa)
    for cmd in common:
        ra, rb = a[cmd], b[cmd]
        sa, sb = ra["params_size"], rb["params_size"]
        if sa is not None and sb is not None and sa != sb:
            size_diff.append((cmd, ra["name"], sa, sb))
        elif (sa is None) != (sb is None):
            newly_sized.append((cmd, ra["name"], sa, sb))

    print(f"[diff] {a_name}: {len(a)} commands, {len(b)} in {b_name}")
    print(f"[diff] common cmd IDs: {len(common)}")
    print(f"[diff] only in {a_name}: {len(only_a)}")
    print(f"[diff] only in {b_name}: {len(only_b)}")
    print()
    print(f"[diff] SIZE MISMATCHES (same cmd ID, different sizeof()): {len(size_diff)}")
    for cmd, name, sa, sb in size_diff:
        print(f"    {cmd}  {name}: {a_name}={sa}  {b_name}={sb}  (delta={sb-sa:+d})")
    print()
    print(f"[diff] struct became sizeable/unsizeable across versions: {len(newly_sized)}")
    for cmd, name, sa, sb in newly_sized[:20]:
        print(f"    {cmd}  {name}: {a_name}={sa}  {b_name}={sb}")
    if len(newly_sized) > 20:
        print(f"    ... and {len(newly_sized) - 20} more")

    print()
    print(f"[diff] commands only in {a_name} (removed by {b_name} or renamed): {len(only_a)}")
    print(f"[diff] commands only in {b_name} (added since {a_name}): {len(only_b)}")


if __name__ == "__main__":
    main()
