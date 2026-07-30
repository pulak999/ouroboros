## [2026-07-30] Effect-Map Experiment v1 — Experiment A, end to end

Plan: `control-folder/plans/effect-map-experiment-v1.md`.
Branch: `effect-map-experiment-v1`. Host: hulk, 3x TITAN RTX, driver 555.42.02,
no root used at any point.

### Features Implemented

- **A1 — control-command table.** 2382 commands extracted from the vendored
  610.43.02 SDK. Struct sizes are measured by generating a C probe that
  `#include`s all 203 `ctrl/` headers and prints `sizeof()`, so padding and
  alignment are exact and no C parser is involved. 1221 sized.
- **A1 — RM object ladder with no root and no libcuda.** `sweep_controls.c`
  opens `/dev/nvidiactl` and allocates `NV01_ROOT` -> `NV01_DEVICE_0` ->
  `NV20_SUBDEVICE_0`. The device allocation returns
  `NV_ERR_INSUFFICIENT_PERMISSIONS` until the GPU is attached, so the tool
  reproduces libcuda's `GET_PROBED_IDS` -> `ATTACH_IDS` -> `open /dev/nvidiaN`
  order, read out of `sniffed/cu_init.jsonl` seq 19-27.
- **A1 — two ABI oracles**, both justified against `control.c:445-456`, where
  the `paramsSize` check runs before object resolution at line 516.
  Presence: real object + impossible size, `0x56` absent / `0x1F` present.
  Size: bogus `hObject` + size scan, `0x57 OBJECT_NOT_FOUND` marks the accepted
  size. The bogus-handle form never runs the handler, so it is safe on writes.
- **A1 — full ABI probe of the shipped driver.** 1675 unique commands in ~2 s.
- **A2 — noise-floor gate.** Null diff over the state vector.
- **A3/A4 — effect map.** 8 cumulative rungs, 5 repetitions, reproducibility
  threshold k=3, plus specificity and the 2 GiB correctness check.
- **MIG classification.** Static, driver and trace evidence joined per command.

### Results

| Measurement | Value |
|---|---|
| Commands probed against 555.42.02 | 1675 |
| Absent from this driver | **508** |
| True `paramsSize` recovered | **1106** |
| Comparable against headers | 898 |
| Header/driver size disagreement | **112 (12%)** |
| Sizes recovered that headers cannot give | 208 |
| A2 stable fields | **142 of 144 (98.6%)** — gate PASS |
| A4 2 GiB correctness check | **PASS** (24603456 -> 22337472 KiB) |

MIG surface, of 64 keyword candidates: 12 configuration (ioctl-reachable),
12 runtime queries (ioctl-reachable), 24 RM-to-GSP internal (**not** ioctls),
16 false positives (VM live migration, TPC partition mode).
51 of the 64 are compiled into 555.42.02.

`NV2080_CTRL_CMD_GPU_GET_ACTIVE_PARTITION_IDS` (`0x2080018B`) is issued **36
times** across the existing corpus — plain `cuInit` probes MIG partition state
on a GPU that cannot do MIG.

Adjacent-rung effect map (the informative view):

| rung | attributed change | specificity |
|---|---|---|
| `ctx_create` | `GR_GET_CURRENT_RESIDENT_CHANNEL` | **1.0** |
| `mem_1m`, `mem_2g` | `FB_GET_INFO_V2` | 0.2 |
| `module`, `launch` | nothing observable | — |

### Files Changed

| File | What changed |
|---|---|
| `control-folder/code.md` | New review section for commit `5a418e1`, 3 phases + the plan cross-reference. |
| `control-folder/CLAUDE.md` | Effect-map build/run recipe and six design decisions. |
| `control-folder/ARCH.md` | Effect-map subsystem, component table, data flow. |
| `control-folder/TODO.md` | Rewritten and ordered by dependency. |
| `control-folder/plans/arch-findings-20260730.md` | Findings 4-8 appended from the experiment. |
| `control-folder/plans/mig-command-classification.md` | New. Generated report. |
| `cuda-ioctl-map/tools/effectmap/*` | New subsystem, 8 files. |

### Functions Written

| Function | File | Description |
|---|---|---|
| `scan_headers` | `extract_ctrl_table.py` | Collects command defines and declared typedefs; drops `*_MESSAGE_ID`. |
| `measure_sizes` | `extract_ctrl_table.py` | Compiles a `sizeof()` probe, prunes rejected types from gcc's own output. |
| `classify` | `gen_sweep_list.py` | Read-only safety filter for a shared machine. |
| `make_template` | `gen_templates.py` | Builds a `{count; (index,0)[]}` request template. |
| `build_ladder` | `sweep_controls.c` | Client/device/subdevice, including the attach sequence. |
| `rm_control` | `sweep_controls.c` | One `NV_ESC_RM_CONTROL`; returns the RM status. |
| `run_size_scan` | `sweep_controls.c` | Presence probe then size scan against a bogus handle. |
| `load_cmds` | `sweep_controls.c` | Parses `cmd size [hex-template]`. |
| `run_one` | `run_effect_map.py` | snapshot/op/snapshot; returns changes and the post snapshot. |
| `diff` | `run_effect_map.py` | Masked response diff; separates status flips from value changes. |
| `tier_of` | `classify_mig.py` | config / runtime / internal / unrelated. |
| `observed_commands` | `classify_mig.py` | Decodes `NVOS54_PARAMETERS` out of captured traces. |

### Data Structures Created

| Name | File | Description |
|---|---|---|
| `NVOS21/64/54_PARAMETERS` | `sweep_controls.c` | RM alloc and control UAPI structs, from `nvos.h`. |
| `struct cmd_entry` | `sweep_controls.c` | `{cmd, size, prefill_len, prefill[512]}`. |
| `ctrl_table.json` | out/ | `{name, cmd, class_hex, family, header, params_struct, params_size, is_get, is_set, is_internal}`. |
| `abi_probe_all.jsonl` | out/ | `{cmd, present, found_size, probe_status, accept_status}` — the size authority. |
| `state_vector_run*.jsonl` | out/ | `{cmd, size, ret, errno, status, resp}` — one snapshot. |
| `effect_map.json` | out/ | `effect_map` (op vs baseline) and `rung_delta_map` (vs previous rung). |

### Notes / caveats

- **Three defects were found and fixed while running A3**, each of which
  silently produced a wrong answer first: snapshotting after process exit
  measures nothing; a zeroed params buffer asks request-driven commands for
  nothing; and a 256-byte line buffer in `load_cmds` truncated a 520-character
  request template and re-parsed the tail as a bogus command.
- **The A2 pass is weaker than it looks.** Much of the 98.6% stability is
  constant capability data. Stability is necessary, not sufficient.
- **The plan's counts are off.** It says 2445 commands / 969 GET / 324 NV2080
  GET. Measured on the vendored SDK: 2382 / 1178 / 428.
- **The plan assumes the open module is 555.42.02** (§4 B1). The vendored
  submodule is **610.43.02**. Pin one before starting Experiment B.
- The user's standing note that `NV_ESC_CARD_INFO = 0xC00846D6` with a size-8
  sentinel is wrong: `0xC00846D6` is `NV_ESC_SYS_PARAMS` (nr 214) and its
  8-byte payload is `memblock_size`. `NV_ESC_CARD_INFO` is `0xC90046C8`
  (nr 200, 2304 bytes = 32 card records).
- Experiment B was not started, as the plan directs. hulk runs the proprietary
  module, so it cannot host the tracer.
