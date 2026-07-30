#!/usr/bin/env python3
"""
classify_mig.py — decide which RM control commands belong to the MIG path.

Three independent sources of evidence are combined, so that no single one has
to be trusted on its own:

 1. STATIC   — name, class and header, from the vendored 610 SDK.
 2. DYNAMIC  — presence and true paramsSize in the *shipped* 555 driver,
               measured by tools/effectmap/sweep_controls (abi_probe_all.jsonl).
 3. OBSERVED — whether the command actually appears in a captured trace under
               sniffed/, that is, whether real CUDA code issues it.

Output tiers:

  config      MIG configuration. Creates, destroys or reshapes instances.
              This is what `nvidia-smi mig -cgi` drives. Userspace-reachable.
  runtime     MIG-aware query issued during ordinary execution, including on
              hardware that has no MIG. Userspace-reachable.
  internal    RM -> GSP internal. NOT reachable through ioctl from userspace.
              These are the RPCs, not the ioctls.
  unrelated   Name matched a MIG keyword but the command is not MIG. Mostly VM
              live migration (MIGRATE/MIGRATION/MIGRATABLE) and TPC partition
              mode, which predates MIG and is a different mechanism.

Usage:
    python3 tools/effectmap/classify_mig.py \
        --table tools/effectmap/out/ctrl_table.json \
        --probe tools/effectmap/out/abi_probe_all.jsonl \
        --sniffed sniffed/ \
        --out-json tools/effectmap/out/mig_classification.json \
        --out-md   ../control-folder/plans/mig-command-classification.md
"""

from __future__ import annotations

import argparse
import json
import struct
from pathlib import Path

# NV_ESC_RM_CONTROL: _IOWR('F', 0x2A, NVOS54_PARAMETERS) — see nv_escape.h.
RM_CONTROL_REQ = "0xC020462A"
NVOS54_CMD_OFF = 8
NVOS54_PSZ_OFF = 24

# Classes whose whole purpose is MIG.
MIG_CLASSES = {
    "0xC637": "AMPERE_SMC_PARTITION_REF (GPU instance)",
    "0xC638": "AMPERE_SMC_EXEC_PARTITION_REF (compute instance)",
    "0xC639": "AMPERE_SMC_CONFIG_SESSION",
    "0xC640": "AMPERE_SMC_MONITOR_SESSION",
}

# Tokens that genuinely indicate MIG.
MIG_TOKENS = ("_MIGMGR", "_SMC_", "_SWIZZ", "GPU_INSTANCE", "COMPUTE_INSTANCE",
              "EXEC_PARTITION", "PARTITIONABLE", "_SKYLINE", "COMPUTE_PROFILE")

# PARTITION on its own is ambiguous: it is MIG on NV2080_CTRL_CMD_GPU_*, but
# TPC partition mode is an older, unrelated mechanism.
PARTITION_TOKEN = "PARTITION"
TPC_TOKENS = ("TPC_PARTITION",)

# Live migration of a VM. Nothing to do with Multi-Instance GPU.
VM_MIGRATION_TOKENS = ("MIGRATABLE", "MIGRATION", "MIGRATE", "_MIGRAT")

STATUS_NOT_SUPPORTED = "0x00000056"
STATUS_INVALID_ARG = "0x0000001F"
STATUS_OBJECT_NOT_FOUND = "0x00000057"


def looks_mig(name: str) -> bool:
    if any(t in name for t in MIG_TOKENS):
        return True
    if PARTITION_TOKEN in name and not any(t in name for t in TPC_TOKENS):
        return True
    return False


def tier_of(name: str, class_hex: str) -> str:
    """Assign a tier from the name and class alone (static evidence)."""
    if class_hex in MIG_CLASSES:
        # NULL is the generic RM ping present on every class.
        return "config" if not name.endswith("_CTRL_CMD_NULL") else "unrelated"

    if "_INTERNAL_" in name:
        return "internal"

    if any(t in name for t in TPC_TOKENS):
        return "unrelated"

    # VM live migration, unless a real MIG token also appears.
    if any(t in name for t in VM_MIGRATION_TOKENS) and not any(
        t in name for t in MIG_TOKENS
    ):
        return "unrelated"

    if not looks_mig(name):
        return "unrelated"

    # Remaining true-MIG userspace commands: writes reshape, reads observe.
    reshaping = ("_SET_", "_CONFIGURE", "_CREATE", "_DELETE", "_IMPORT",
                 "_EXPORT", "_INVALIDATE", "_UPDATE")
    if any(t in name for t in reshaping):
        return "config"
    return "runtime"


def observed_commands(sniffed_dir: Path) -> dict[int, dict]:
    """Which control cmds actually appear in captured traces, and at what size."""
    seen: dict[int, dict] = {}
    for path in sorted(sniffed_dir.glob("*.jsonl")):
        for line in path.open():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("type") != "ioctl" or rec.get("req") != RM_CONTROL_REQ:
                continue
            buf = bytes.fromhex(rec["before"])
            if len(buf) < NVOS54_PSZ_OFF + 4:
                continue
            cmd, = struct.unpack_from("<I", buf, NVOS54_CMD_OFF)
            psz, = struct.unpack_from("<I", buf, NVOS54_PSZ_OFF)
            e = seen.setdefault(cmd, {"count": 0, "sizes": set(), "programs": set()})
            e["count"] += 1
            e["sizes"].add(psz)
            e["programs"].add(path.stem)
    return seen


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--table", type=Path, required=True)
    ap.add_argument("--probe", type=Path, required=True)
    ap.add_argument("--sniffed", type=Path, required=True)
    ap.add_argument("--out-json", type=Path, required=True)
    ap.add_argument("--out-md", type=Path, required=True)
    args = ap.parse_args()

    table = json.loads(args.table.read_text(encoding="utf-8"))["commands"]

    probe: dict[int, dict] = {}
    for line in args.probe.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        probe[int(r["cmd"], 16)] = r

    observed = observed_commands(args.sniffed)

    rows = []
    for row in table:
        name, cls = row["name"], row["class_hex"]
        if not (looks_mig(name) or cls in MIG_CLASSES
                or any(t in name for t in VM_MIGRATION_TOKENS)
                or any(t in name for t in TPC_TOKENS)):
            continue

        p = probe.get(row["cmd"], {})
        obs = observed.get(row["cmd"])

        # Present in the shipped driver? The presence probe uses a real object
        # and an impossible size, so 0x1F means "in the export table".
        if not p:
            present = None
        elif p.get("present") is False:
            present = False
        else:
            present = p.get("probe_status") == STATUS_INVALID_ARG or bool(p.get("present"))

        rows.append({
            "name": name,
            "cmd_hex": row["cmd_hex"],
            "class_hex": cls,
            "class_note": MIG_CLASSES.get(cls),
            "header": row["header"],
            "tier": tier_of(name, cls),
            "header_params_size": row["params_size"],
            "driver_present": present,
            "driver_params_size": p.get("found_size"),
            "probe_status": p.get("probe_status"),
            "accept_status": p.get("accept_status"),
            "observed_in_traces": bool(obs),
            "observed_count": obs["count"] if obs else 0,
            "observed_sizes": sorted(obs["sizes"]) if obs else [],
            "observed_programs": sorted(obs["programs"]) if obs else [],
        })

    rows.sort(key=lambda r: (r["tier"], r["cmd_hex"]))

    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps({"commands": rows}, indent=1), encoding="utf-8")

    write_markdown(rows, args.out_md)

    by_tier: dict[str, int] = {}
    for r in rows:
        by_tier[r["tier"]] = by_tier.get(r["tier"], 0) + 1
    print(f"[mig] {len(rows)} candidate commands")
    for t in ("config", "runtime", "internal", "unrelated"):
        print(f"[mig]   {t:10s} {by_tier.get(t, 0)}")
    print(f"[mig] wrote {args.out_json}")
    print(f"[mig] wrote {args.out_md}")


def _present_cell(r: dict) -> str:
    if r["driver_present"] is None:
        return "not probed"
    if not r["driver_present"]:
        return "**absent**"
    if r["accept_status"] == STATUS_NOT_SUPPORTED:
        return "present, hw n/a"
    return "present"


def write_markdown(rows: list[dict], out: Path) -> None:
    L: list[str] = []
    A = L.append
    A("# MIG command classification — driver 555.42.02 on hulk (TITAN RTX)")
    A("")
    A("Generated by `cuda-ioctl-map/tools/effectmap/classify_mig.py`. Do not")
    A("edit by hand; re-run the tool.")
    A("")
    A("## How to read this")
    A("")
    A("Three independent sources are combined:")
    A("")
    A("- **static** — name, class and header in the vendored 610.43.02 SDK.")
    A("- **driver** — measured against the loaded 555.42.02 binary with")
    A("  `sweep_controls --size-scan`. `present` means the command is in the")
    A("  driver's NVOC export table. `present, hw n/a` means the driver has it")
    A("  but the handler answers `NV_ERR_NOT_SUPPORTED` on this GPU, which is")
    A("  what a non-MIG card does. `absent` means this driver does not have it.")
    A("- **observed** — the command appears in a real capture under `sniffed/`.")
    A("")
    A("`driver size` is the paramsSize the shipped driver actually enforces,")
    A("recovered by scan. Where it differs from `hdr size`, **trust the driver**")
    A("column: the 610 headers do not describe the 555 binary.")
    A("")

    tiers = [
        ("config", "Tier 1 — MIG configuration (userspace ioctl)",
         "These reshape the GPU. `nvidia-smi mig -cgi` drives this set. They are "
         "reachable over `NV_ESC_RM_CONTROL` from userspace, so they are in "
         "scope for ioctl-level reverse engineering."),
        ("runtime", "Tier 2 — MIG-aware runtime queries (userspace ioctl)",
         "Reads that ordinary CUDA issues, including on hardware with no MIG. "
         "Anything marked observed is on the plain `cuInit` path."),
        ("internal", "Tier 3 — RM to GSP internal (NOT ioctl-reachable)",
         "These never cross the userspace boundary. RM calls them on itself and "
         "forwards them to the GSP as RPCs. An ioctl tracer cannot see them; "
         "Experiment B (the RPC fan-out tracer) is the only way to observe them."),
        ("unrelated", "Tier 4 — matched a keyword but is NOT MIG",
         "Kept deliberately, so the exclusion is auditable. Mostly VM live "
         "migration (`MIGRATE`/`MIGRATION`/`MIGRATABLE`) and TPC partition mode, "
         "which predates MIG and is a different mechanism."),
    ]

    for tier, title, blurb in tiers:
        sel = [r for r in rows if r["tier"] == tier]
        A(f"## {title}")
        A("")
        A(blurb)
        A("")
        if not sel:
            A("_None._")
            A("")
            continue
        A("| cmd | name | driver | hdr size | driver size | observed |")
        A("|---|---|---|---|---|---|")
        for r in sel:
            obs = f"yes ({r['observed_count']}x)" if r["observed_in_traces"] else "no"
            ds = r["driver_params_size"]
            ds = "—" if ds is None or ds < 0 else str(ds)
            hs = r["header_params_size"]
            hs = "—" if hs is None else str(hs)
            mark = " ⚠" if (hs != "—" and ds != "—" and hs != ds) else ""
            A(f"| `{r['cmd_hex']}` | {r['name']} | {_present_cell(r)} | "
              f"{hs} | {ds}{mark} | {obs} |")
        A("")

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(L) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
