#!/usr/bin/env python3
"""
run_effect_map.py — Experiments A3 and A4: build and score the effect map.

Protocol, per operation, repeated N times:

    sweep -> before
    start effect_probe <op>, wait for READY   (the op is now live)
    sweep -> after
    let the probe exit
    diff before/after, masked by the A2 noise mask

A3 output is `{op: [changed commands, with a reproducibility count]}`.
A4 scores it:

  reproducibility  a command counts only if it changed in >= k of N runs.
  specificity      (runs where this op changed it) / (runs where any op did).
                   A command that moves for every operation carries no
                   information about any of them.
  correctness      mem_2g must move framebuffer accounting. If it does not,
                   the pipeline is wrong and no other row can be trusted.

Note on holding state open: the probe stays blocked on stdin while the sweep
runs. Snapshotting after the process exits would measure nothing, because the
driver tears the whole context down at process teardown.

Usage:
    python3 tools/effectmap/run_effect_map.py \
        --cmds tools/effectmap/out/sweep_cmds_555.txt \
        --noise tools/effectmap/out/noise_floor_report.json \
        --reps 5 \
        --out tools/effectmap/out/effect_map.json
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SWEEP = ROOT / "sweep_controls"
PROBE = ROOT / "effect_probe"

# Cumulative rungs. The diff between adjacent rungs attributes new state to
# exactly one new operation, which is the curriculum idea from plan-v1 §6.
OPS = ["baseline", "cuinit", "ctx_create", "mem_1m", "mem_2g",
       "stream", "module", "launch"]

# Framebuffer accounting, for the A4 correctness check.
FB_COMMANDS = {
    "0x20801301",  # NV2080_CTRL_CMD_FB_GET_INFO
    "0x20801303",  # NV2080_CTRL_CMD_FB_GET_INFO_V2
}


def sweep(cmds: Path, out: Path) -> dict[str, dict]:
    r = subprocess.run(
        [str(SWEEP), "--cmds", str(cmds), "--out", str(out)],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        raise SystemExit(f"sweep failed: {r.stderr[-2000:]}")
    rows = {}
    for line in out.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rec = json.loads(line)
            rows[rec["cmd"]] = rec
    return rows


def diff(before: dict[str, dict], after: dict[str, dict],
         mask: set[str]) -> list[str]:
    """Commands whose successful response changed, excluding the noise mask."""
    changed = []
    for cmd, b in before.items():
        if cmd in mask:
            continue
        a = after.get(cmd)
        if a is None:
            continue
        if b["status"] != "0x00000000" or a["status"] != "0x00000000":
            # A status flip is itself an effect, but it is a different kind of
            # signal; record it separately so it cannot be confused with a
            # value change.
            if b["status"] != a["status"]:
                changed.append(cmd + " (status)")
            continue
        if b["resp"] != a["resp"]:
            changed.append(cmd)
    return sorted(changed)


def run_one(op: str, cmds: Path, mask: set[str], tmp: Path
            ) -> tuple[list[str], dict[str, dict]]:
    """Returns (changes vs the pre-op snapshot, the post-op snapshot itself).

    The post-op snapshot is kept so the caller can also diff adjacent rungs.
    The rungs are cumulative, so an op-vs-baseline diff credits every effect of
    cuInit to all seven later rungs and caps specificity at 1/7. Diffing rung i
    against rung i-1 attributes a change to exactly the one operation that was
    added, which is what plan-v1 §6 asks for.
    """
    before = sweep(cmds, tmp / "before.jsonl")

    proc = subprocess.Popen(
        [str(PROBE), op],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True,
    )
    line = proc.stdout.readline() if proc.stdout else ""
    if line.strip() != "READY":
        err = proc.stderr.read() if proc.stderr else ""
        proc.kill()
        raise SystemExit(f"probe '{op}' did not become READY: {line!r} {err[-500:]}")

    after = sweep(cmds, tmp / "after.jsonl")

    try:
        proc.stdin.write("\n")
        proc.stdin.flush()
    except BrokenPipeError:
        pass
    proc.wait(timeout=60)

    return diff(before, after, mask), after


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cmds", type=Path, required=True)
    ap.add_argument("--noise", type=Path, required=True)
    ap.add_argument("--reps", type=int, default=5)
    ap.add_argument("--k", type=int, default=None,
                    help="reproducibility threshold; default ceil(reps/2)")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--table", type=Path,
                    default=ROOT / "out" / "ctrl_table.json")
    args = ap.parse_args()

    if not SWEEP.is_file():
        raise SystemExit(f"missing {SWEEP}; build sweep_controls first")
    if not PROBE.is_file():
        raise SystemExit(f"missing {PROBE}; build effect_probe first")

    noise = json.loads(args.noise.read_text(encoding="utf-8"))
    mask = {n["cmd"] for n in noise["noisy_commands"]}
    print(f"[effect] noise mask excludes {len(mask)} command(s): {sorted(mask)}")

    names: dict[str, str] = {}
    if args.table.is_file():
        for c in json.loads(args.table.read_text(encoding="utf-8"))["commands"]:
            names.setdefault(c["cmd_hex"], c["name"])

    k = args.k if args.k is not None else (args.reps + 1) // 2

    # counts[op][cmd] = number of repetitions in which it changed
    counts: dict[str, dict[str, int]] = {op: {} for op in OPS}
    # rung_counts[op][cmd] = times this cmd differed from the PREVIOUS rung
    rung_counts: dict[str, dict[str, int]] = {op: {} for op in OPS}
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        for rep in range(args.reps):
            prev_after: dict[str, dict] | None = None
            for op in OPS:
                changed, after = run_one(op, args.cmds, mask, tmp)
                for c in changed:
                    counts[op][c] = counts[op].get(c, 0) + 1
                if prev_after is not None:
                    for c in diff(prev_after, after, mask):
                        rung_counts[op][c] = rung_counts[op].get(c, 0) + 1
                prev_after = after
                print(f"[effect] rep {rep+1}/{args.reps}  {op:<12} "
                      f"{len(changed):3d} changed")

    # A4 — reproducibility, then specificity across operations.
    total_hits: dict[str, int] = {}
    for op in OPS:
        for c, n in counts[op].items():
            total_hits[c] = total_hits.get(c, 0) + n

    effect_map: dict[str, list[dict]] = {}
    for op in OPS:
        rows = []
        for c, n in sorted(counts[op].items(), key=lambda kv: -kv[1]):
            if n < k:
                continue
            rows.append({
                "cmd": c,
                "name": names.get(c.split(" ")[0], "?"),
                "changed_in": n,
                "of": args.reps,
                "specificity": round(n / total_hits[c], 3),
            })
        rows.sort(key=lambda r: (-r["specificity"], -r["changed_in"]))
        effect_map[op] = rows

    # A4 correctness check — a 2 GiB allocation must move FB accounting.
    fb_hit = [r for r in effect_map["mem_2g"]
              if r["cmd"].split(" ")[0] in FB_COMMANDS]
    correctness = {
        "check": "cuMemAlloc(2GiB) must change framebuffer accounting",
        "fb_commands_watched": sorted(FB_COMMANDS),
        "fb_commands_changed": [r["cmd"] for r in fb_hit],
        "passed": bool(fb_hit),
    }

    # Adjacent-rung view: credit a change to the one operation that was added.
    rung_total: dict[str, int] = {}
    for op in OPS:
        for c, n in rung_counts[op].items():
            rung_total[c] = rung_total.get(c, 0) + n
    rung_map: dict[str, list[dict]] = {}
    for op in OPS:
        rows = []
        for c, n in rung_counts[op].items():
            if n < k:
                continue
            rows.append({
                "cmd": c,
                "name": names.get(c.split(" ")[0], "?"),
                "changed_in": n,
                "of": args.reps,
                "specificity": round(n / rung_total[c], 3),
            })
        rows.sort(key=lambda r: (-r["specificity"], -r["changed_in"]))
        rung_map[op] = rows

    out = {
        "rung_delta_map": rung_map,
        "reps": args.reps,
        "k": k,
        "noise_mask": sorted(mask),
        "ops": OPS,
        "correctness_check": correctness,
        "effect_map": effect_map,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=1), encoding="utf-8")

    print()
    print(f"[effect] reps={args.reps} k={k}")
    for op in OPS:
        print(f"[effect] {op:<12} {len(effect_map[op]):3d} reproducible changes")
    print()
    print()
    print("[effect] adjacent-rung deltas (change credited to the added op):")
    for op in OPS:
        rows = rung_map[op]
        uniq = sum(1 for r in rows if r["specificity"] >= 0.99)
        print(f"[effect]   {op:<12} {len(rows):3d} changes, {uniq} unique to this rung")
    print()
    print(f"[effect] correctness check (2GiB -> FB accounting): "
          f"{'PASS' if correctness['passed'] else 'FAIL'}")
    print(f"[effect] wrote {args.out}")
    if not correctness["passed"]:
        print("[effect] the correctness check failed; do not trust the other rows",
              file=sys.stderr)


if __name__ == "__main__":
    main()
