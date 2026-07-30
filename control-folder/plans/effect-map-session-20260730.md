# Effect-map / MIG-RE session — 2026-07-30, morning summary

Overnight session on `effect-map-experiment-v1.md`. Two threads ran
concurrently — mine (source-level MIG mechanism tracing, arch review, the
Experiment B RPC tracer) and a parallel process working the Layer-1
sweeper/classification pipeline in `tools/effectmap/`. This doc is the single
entry point tying both together. Read this first.

## Start here: one real open problem

**The effect map's own correctness self-check failed.**
`tools/effectmap/out/effect_map.json` → `correctness_check`:

```json
"check": "cuMemAlloc(2GiB) must change framebuffer accounting",
"fb_commands_watched": ["0x20801301", "0x20801303"],
"fb_commands_changed": [],
"passed": false
```

This is `NV2080_CTRL_CMD_FB_GET_INFO` / `FB_GET_INFO_V2` — both genuinely in
the admitted read-only sweep set (confirmed, not a filter-coverage gap;
`grep 0x20801301 out/sweep_cmds.txt` finds it). A 2 GiB `cuMemAlloc` produced
**no observable change** in either. This is exactly the kind of check
`effect-map-experiment-v1.md` §A4 asked for ("a candidate that reproduces the
ioctl sequence but not the state delta must score lower") and it's failing
against the *golden* trace, not a candidate — meaning either:

1. `FB_GET_INFO`/`V2` report static/reserved FB size, not live per-allocation
   usage — wrong command for this check, a different one is needed (heap
   query, or a per-client accounting field).
2. The `mem_2g` op frees the allocation before the post-snapshot runs.
3. FB accounting doesn't update synchronously with the ioctl return.
4. Something more basic — worth first checking `run_effect_map.py`'s
   `mem_2g` op definition and confirming the allocation is actually held
   live across both snapshots.

**Do this first.** Everything downstream (A5 — wiring the effect map in as
GEPA's fitness oracle) depends on this actually measuring something real.
Also worth noting, lower priority: `FB_GET_INFO`'s param size is inconsistent
between `out/sweep_cmds.txt` (16) and `out/sweep_cmds_555.txt` (1) — the same
555-vs-610-header drift documented below, check it isn't contributing.

## What's real and validated (safe to build on)

- **A2 noise-floor gate: PASS, 98.0% stable** (102 commands returned status 0
  across two back-to-back runs with nothing in between; only 2 differed, and
  both are literal timer/timestamp reads — `NV2080_CTRL_CMD_TIMER_GET_TIME`
  and `NV0000_CTRL_CMD_NVD_GET_TIMESTAMP`. The methodology correctly finds
  *only* genuinely time-varying fields noisy — a clean sanity check that the
  approach works.) `tools/effectmap/out/noise_floor_report.json`.
- **The three-way size-oracle split, empirically confirmed on real hardware**
  (`effect-map-experiment-v1.md` §A1's free validation): `normal` vs
  `badsize` vs `badobject` probe modes produce three distinguishable status
  patterns — `badobject` alone introduces `NV_ERR_OBJECT_NOT_FOUND` (0x57),
  which never appears in `normal`/`badsize`. Confirms
  `control.c:452`'s size check really does fire before object resolution, on
  the actual shipped 555.42.02 binary, not just in source reading.
- **Header/binary version drift is real and large, and now precisely
  measured**: the vendored SDK (`refs/open-gpu-kernel-modules`, tag
  610.43.02) disagrees with the loaded 555.42.02 binary on struct sizes for
  several MIG commands — worst case `DESCRIBE_PARTITIONS`: header says 5768
  bytes, driver actually enforces 1288. Full measured table:
  `control-folder/plans/mig-command-classification.md`. **Trust the
  `driver size` column over `hdr size,`** everywhere, for this hardware.
- **Full MIG command classification**, tiered by userspace-reachability, with
  every size driver-measured (not just header-derived):
  `control-folder/plans/mig-command-classification.md` (machine-generated —
  regenerate with `classify_mig.py`, don't hand-edit) plus
  `control-folder/plans/mig-rpc-mechanism-notes.md` (source-traced companion
  — how each command crosses to GSP, the 5 forwarding patterns, the 8-step
  create/delete lifecycle, gotchas).

## What's built but genuinely untested — Experiment B, the RPC tracer

`tools/effectmap/rpc_tracer/` — two patches against `open-gpu-kernel-modules`
tag 555.42.02, both verified to apply cleanly with `patch -p1 --dry-run`
against the real tree, **never compiled, never run** (needs root + a rented
GSP-class GPU; hulk can't run this — proprietary driver, can't patch a
blob). Full deploy instructions, including a build gotcha that will silently
no-op the patch if missed (`kernel-open` prefers a prebuilt `nv-kernel.o`
blob unless `src/nvidia` is built from source first), are in
`tools/effectmap/rpc_tracer/README.md`.

This is the actual next step for "reverse engineer the RPCs" — it exposes
`/proc/driver/nvidia/rpc_trace` with every GSP RPC's
`(function, cmd, paramsSize, timestamp)`, sourced directly from the driver's
own existing (but only 8-entry-deep) `_kgspAddRpcHistoryEntry` hook. No MIG
hardware needed — any GSP-offload GPU works, since this traces the generic
control-forwarding path every ioctl rides, confirmed to have no dedicated
MIG-specific RPC channel (`mig-rpc-mechanism-notes.md` §1).

## File map

```
control-folder/plans/
  effect-map-experiment-v1.md       — the original experiment design (A1-A5, B1-B4)
  mig-command-classification.md     — machine-generated, driver-measured MIG command table
  mig-rpc-mechanism-notes.md        — source-traced: how each command reaches GSP
  arch-findings-20260730.md         — Ouroboros codebase findings (sniffer, GEPA scope, oracle)
  effect-map-session-20260730.md    — this file

cuda-ioctl-map/tools/effectmap/
  extract_ctrl_table.py             — header -> ctrl_table.json (sizeof-probe compiled)
  classify_mig.py                   — ctrl_table.json + driver probe -> mig-command-classification.md
  gen_sweep_list.py                 — ctrl_table.json -> read-only sweep_cmds.txt (safety filter)
  sweep_controls.c                  — Experiment A1: state-vector sweeper + probe-mode self-check
  noise_floor.py                    — Experiment A2: gate on two-run diff
  diff_ctrl_tables.py               — static 555-vs-610 header size diff (no hardware needed)
  run_effect_map.py, effect_probe.cu, gen_templates.py
                                     — Experiment A3/A4: real CUDA op corpus -> effect_map.json
  rpc_tracer/                       — Experiment B: kernel patches + deploy README (untested)
  out/                              — all run artifacts (ctrl_table*.json, sweep results, effect_map.json)
```

## Ranked next actions

1. **Debug the FB accounting correctness-check failure.** Highest priority —
   it's the thing that decides whether `effect_map.json` can be trusted for
   anything.
2. Once (1) is resolved, wire the effect map into `optimizer/metrics.py`'s
   `score_gate` as a second scoring axis, per `arch-findings-20260730.md`
   Finding 3 — this is Workstream A1 from `ouroboros-plan-v1.md` §4, and it
   stands alone regardless of MIG or Experiment B.
3. Fix `arch-findings-20260730.md` Finding 1 (the sniffer's pointer-
   indirection blindness on `NV_ESC_RM_CONTROL`) before extending A3's corpus
   further — it silently undercounts every RM_CONTROL trace captured through
   `nv_sniff.c` today.
4. Rent a box, deploy `rpc_tracer/`, confirm step 7 of its README (the
   `/proc/driver/nvidia/rpc_trace` file actually appears) before spending
   further time — that's the fast, cheap check that the patches actually
   worked.
5. Correlate: run the Tier 1/2 MIG userspace commands from
   `mig-command-classification.md` against the RPC tracer (once deployed) and
   confirm the Pattern A/B/C/D/E predictions in `mig-rpc-mechanism-notes.md`
   against real GSP traffic — this is the actual "reverse engineer the RPCs"
   deliverable.
