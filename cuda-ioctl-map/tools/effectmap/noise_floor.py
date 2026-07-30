#!/usr/bin/env python3
"""
noise_floor.py — Experiment A2: diff two state_vector.jsonl runs with nothing
in between and report how many successful commands are byte-stable.

This is the gate from effect-map-experiment-v1.md: if fewer than roughly half
of the 200-status commands survive a null diff, Layer 1 (state-delta) is too
noisy to carry the effect-map experiment on its own.

Usage:
    python3 tools/effectmap/noise_floor.py run1.jsonl run2.jsonl [--report out.json]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def load(path: Path) -> dict[str, dict]:
    rows = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            rows[r["cmd"]] = r
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("run1", type=Path)
    ap.add_argument("run2", type=Path)
    ap.add_argument("--report", type=Path, default=None)
    args = ap.parse_args()

    r1 = load(args.run1)
    r2 = load(args.run2)

    cmds = sorted(set(r1) & set(r2))
    both_ok = [c for c in cmds if r1[c]["status"] == "0x00000000" and r2[c]["status"] == "0x00000000"]

    stable, noisy = [], []
    for c in both_ok:
        if r1[c]["resp"] == r2[c]["resp"]:
            stable.append(c)
        else:
            # byte-level diff position count, for the report
            a, b = r1[c]["resp"], r2[c]["resp"]
            n = min(len(a), len(b))
            diff_bytes = sum(1 for i in range(0, n, 2) if a[i:i+2] != b[i:i+2])
            noisy.append({"cmd": c, "size": r1[c]["size"], "diff_bytes": diff_bytes,
                          "total_bytes": r1[c]["size"]})

    total_ok = len(both_ok)
    n_stable = len(stable)
    n_noisy = len(noisy)
    stable_ratio = n_stable / total_ok if total_ok else 0.0

    print(f"[noise-floor] commands with status=0 in both runs: {total_ok}")
    print(f"[noise-floor] byte-identical (stable):             {n_stable}  ({stable_ratio:.1%})")
    print(f"[noise-floor] changed with nothing in between:      {n_noisy}")
    print()
    if total_ok == 0:
        print("[noise-floor] GATE: FAIL — no commands returned status 0, nothing to measure")
        sys.exit(1)
    if stable_ratio < 0.5:
        print(f"[noise-floor] GATE: FAIL — only {stable_ratio:.1%} of fields are stable (need >=50%)")
        print("[noise-floor]   Layer 1 is too noisy to carry the effect map alone per")
        print("[noise-floor]   effect-map-experiment-v1.md's stop condition. Fall back to")
        print("[noise-floor]   a curated stable subset, or lean on Layer 2 (RPC tracer).")
    else:
        print(f"[noise-floor] GATE: PASS — {stable_ratio:.1%} of fields are stable")

    print()
    print("[noise-floor] noisy commands (changed with nothing in between):")
    for n in sorted(noisy, key=lambda x: -x["diff_bytes"])[:30]:
        print(f"    {n['cmd']}  {n['diff_bytes']}/{n['total_bytes']} bytes differ")

    if args.report:
        args.report.write_text(json.dumps({
            "total_ok": total_ok,
            "stable": n_stable,
            "noisy": n_noisy,
            "stable_ratio": stable_ratio,
            "gate": "pass" if stable_ratio >= 0.5 else "fail",
            "noisy_commands": noisy,
            "stable_commands": stable,
        }, indent=2), encoding="utf-8")
        print(f"\n[noise-floor] wrote {args.report}")


if __name__ == "__main__":
    main()
