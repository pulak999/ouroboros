#!/usr/bin/env python3
"""
correlate_rpc_trace.py — Experiment B3: join a captured rpc_trace against the
MIG command classification, so real RPC firings turn into named findings
instead of raw (function, cmd, size) tuples.

Input is the raw text of /proc/driver/nvidia/rpc_trace, produced by the two
patches in this directory (see README.md). Each data row is:

    ts function data0 data1

where function is the NV_VGPU_MSG_FUNCTION_* id (decimal), data0 is the inner
RM control cmd (hex, only meaningful when function == GSP_RM_CONTROL) and
data1 is paramsSize (decimal). GSP_RM_CONTROL == 76 in both 555.42.02 and
610.43.02 (rpc_global_enums.h — RPC ids are append-only, never reused).

Per mig-rpc-mechanism-notes.md, MIG commands cross to GSP two ways:
  - Pattern A: translated to an INTERNAL_* cmd (Tier 3 in the classification).
  - Pattern B: forwarded verbatim under the caller's own cmd (Tier 1/2 name
    shows up unchanged on the wire — NVC637 EXEC_PARTITIONS_CREATE is the
    example named in the notes).
A cmd hit under either tier is a real finding; this script does not privilege
Tier 3 over Tier 1/2 for that reason.

Usage:
    # single dump (matches everything in it)
    python3 correlate_rpc_trace.py --trace after.txt \
        --classification ../out/mig_classification.json

    # before/after diff (matches only rows written during the window)
    python3 correlate_rpc_trace.py --before before.txt --after after.txt \
        --classification ../out/mig_classification.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

GSP_RM_CONTROL_FUNCTION = 76

HEADER_RE_PREFIX = "#"


def parse_trace(text: str) -> tuple[int, list[dict]]:
    """Returns (total_entries_ever_written, rows). Ignores comment lines."""
    total = 0
    rows: list[dict] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith(HEADER_RE_PREFIX):
            if "total_entries_ever_written" in line:
                for tok in line.split():
                    if tok.startswith("total_entries_ever_written="):
                        total = int(tok.split("=", 1)[1])
            continue
        parts = line.split()
        if len(parts) != 4:
            print(f"warning: skipping malformed line: {line!r}", file=sys.stderr)
            continue
        ts, function, data0, data1 = parts
        rows.append({
            "ts": int(ts),
            "function": int(function),
            "data0": int(data0, 16),
            "data1": int(data1),
        })
    return total, rows


def load_classification(path: Path) -> dict[int, dict]:
    d = json.loads(path.read_text())
    by_cmd: dict[int, dict] = {}
    for c in d["commands"]:
        by_cmd[int(c["cmd_hex"], 16)] = c
    return by_cmd


def correlate(rows: list[dict], by_cmd: dict[int, dict]) -> list[dict]:
    findings = []
    for r in rows:
        if r["function"] != GSP_RM_CONTROL_FUNCTION:
            continue
        cmd = r["data0"]
        entry = by_cmd.get(cmd)
        finding = {
            "ts": r["ts"],
            "cmd_hex": f"0x{cmd:08X}",
            "observed_params_size": r["data1"],
        }
        if entry is None:
            finding["match"] = "not in MIG classification (other RM_CONTROL traffic)"
        else:
            finding["match"] = entry["name"]
            finding["tier"] = entry["tier"]
            finding["expected_params_size"] = entry["driver_params_size"]
            if entry["driver_params_size"] is not None and entry["driver_params_size"] != r["data1"]:
                finding["size_mismatch"] = True
        findings.append(finding)
    return findings


def render_report(findings: list[dict]) -> str:
    mig_hits = [f for f in findings if f.get("tier")]
    other = [f for f in findings if not f.get("tier")]
    lines = [
        "# Experiment B3 — RPC trace correlation",
        "",
        f"GSP_RM_CONTROL rows in this window: {len(findings)}.",
        f"Rows that match a MIG command: {len(mig_hits)}.",
        f"Rows that are other RM_CONTROL traffic: {len(other)}.",
        "",
    ]
    if mig_hits:
        lines.append("| ts | cmd | tier | name | observed size | expected size |")
        lines.append("|---|---|---|---|---|---|")
        for f in mig_hits:
            flag = " ⚠" if f.get("size_mismatch") else ""
            lines.append(
                f"| {f['ts']} | {f['cmd_hex']} | {f['tier']} | {f['match']} | "
                f"{f['observed_params_size']}{flag} | {f.get('expected_params_size')} |"
            )
        lines.append("")
    tiers_seen = sorted({f["tier"] for f in mig_hits})
    if "internal" in tiers_seen:
        lines.append(
            "Tier-3 (internal) hits confirm Pattern A: the RPC fired under a "
            "translated cmd, not the userspace-facing one."
        )
    if any(t in tiers_seen for t in ("config", "runtime")):
        lines.append(
            "Tier-1/2 hits on the wire confirm Pattern B: the userspace cmd "
            "crossed to GSP unchanged. Cross-check the payload's bValid field "
            "(mig-rpc-mechanism-notes.md) before concluding create vs delete."
        )
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--trace", type=Path, help="single rpc_trace dump to correlate in full")
    ap.add_argument("--before", type=Path, help="rpc_trace dump taken before the operation")
    ap.add_argument("--after", type=Path, help="rpc_trace dump taken after the operation")
    ap.add_argument("--classification", type=Path, required=True,
                     help="path to mig_classification.json")
    ap.add_argument("--out", type=Path, help="write markdown report here (default: stdout)")
    args = ap.parse_args()

    by_cmd = load_classification(args.classification)

    if args.trace:
        _total, rows = parse_trace(args.trace.read_text())
    elif args.before and args.after:
        before_total, _ = parse_trace(args.before.read_text())
        after_total, after_rows = parse_trace(args.after.read_text())
        depth = 1 << 16
        if after_total - before_total > depth:
            print(
                f"warning: window is {after_total - before_total} entries, "
                f"wider than the {depth}-entry log depth — earlier rows already "
                "overwritten, results are incomplete",
                file=sys.stderr,
            )
        # after_rows already only contains the surviving window (start clamps
        # to depth in the kernel reader); keep rows whose position in the
        # written stream is >= before_total.
        skip = max(0, before_total - max(0, after_total - depth))
        rows = after_rows[skip:]
    else:
        ap.error("pass either --trace, or both --before and --after")

    findings = correlate(rows, by_cmd)
    report = render_report(findings)
    if args.out:
        args.out.write_text(report)
        print(f"wrote {args.out}", file=sys.stderr)
    else:
        print(report)


if __name__ == "__main__":
    main()
