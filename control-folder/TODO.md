# TODO — Ouroboros

Ordered by dependency. Status as of 2026-08-06.

## Plan v3 Lane A — ground truth from the driver (current work)

Serves `plans/ouroboros-plan-v3.md`. All jobs are read-only and need no root.
Ordered by hard dependency — A1 must complete before A2 picks a number.

- [ ] **A0 — stamp provenance on every output.** Driver version, GPU model, git
      SHA. Nothing does this today, which is why the 555/610 drift went
      unnoticed for a week. Do it first so A1's output is self-describing.
      (code.md `aaf7d18` Phase 3 item 2)
- [ ] **A1 — re-probe the ABI against 610.43.02.** Re-run steps 1-3 of the
      effect-map pipeline in `CLAUDE.md`. Regenerate `ctrl_table.json`,
      `abi_probe_all.jsonl`, `sweep_cmds_*.txt`. Then regenerate
      `mig-command-classification.md` with `classify_mig.py`.
      **Blocks A2.** The 610 header declares `FB_INFO_MAX_LIST_SIZE = 128`
      (1028 bytes) while the 555 probe measured 444. Which one 610 enforces
      decides A2's safe ceiling.
- [ ] **A2a — fix `load_cmds` before raising `MAX_INDEX`.** `sweep_controls.c`:
      widen `hex[]` to match the `%2048s` parse, or narrow the parse to match
      the buffer. Add a loud error when a template is dropped for exceeding
      `MAX_PREFILL`, instead of silently sending a zeroed buffer.
      (code.md findings E1, E2)
- [ ] **A2b — raise `MAX_INDEX` in `gen_templates.py`.** **55, not 68** — 68
      overflows via `GPU_GET_INFO_V2` (capacity 65). Re-sweep and decode.
      Target indices: `LTC_COUNT` 0x22, `LTS_COUNT` 0x23,
      `PSEUDO_CHANNEL_MODE` 0x25, `LTC_MASK` 0x2b. (code.md finding E3)
- [ ] **A3 — `EXEC_REG_OPS` reachability probe.** New `--exec-reg-ops` path in
      `sweep_controls.c`. One `READ_32` at `0x001404f8`. **Reads only.**
      Cannot go through `gen_sweep_list.py` — `_EXEC` is denied there and that
      denial must stay. (code.md finding E8)
- [ ] **A4 — publish the TU102 memory-geometry table** from A2b's output, into
      `ARCH.md`, replacing the partial table now there.

## Plan v3 — carried corrections

- [ ] **Fix `noise_floor.py` to exit non-zero when the gate fails.** Today it
      prints `GATE: FAIL` and returns 0, so any script proceeds past it. The
      docs treat this gate as a hard stop. (code.md finding E5)
- [ ] **Re-pin `rpc_tracer/` patches** from open-module tag 555.42.02 to
      610.43.02, to match the loaded driver.
- [ ] **CI does not run on this branch.** `optimizer-plan-v2-phase0.yml`
      triggers only on `main` and `coding-agent-dev`; work is on
      `effect-map-experiment-v1`. Either add the branch or merge before
      relying on CI.
- [ ] **No tests exist for `tools/effectmap/`** — 2225 lines, zero coverage.
      The pure-Python parts (`make_template`, `classify`, the noise gate) are
      unit-testable with no GPU and belong in CI.

## Done — effect-map experiment v1 (Experiment A)

- [x] A1 — command table from the SDK headers (2382 commands, 1221 sized)
- [x] A1 — RM object ladder without root or libcuda (client/device/subdevice)
- [x] A1 — size oracle, verified three-way against `control.c:445-456`
- [x] A1 — **full ABI probe of the shipped 555.42.02 driver**: 508 of 1675
      commands absent, 1106 true sizes recovered, 112 of 898 (12%) disagree
      with the 610 headers
- [x] A2 — noise-floor gate: **PASS**, 142 of 144 stable (98.6%)
- [x] A3 — effect map over an 8-rung cumulative CUDA ladder, 5 reps
- [x] A4 — reproducibility, specificity, and the 2 GiB correctness check
      (**PASS** after the request-template fix)
- [x] MIG classification report keyed to the shipped driver

## Next — highest value first

- [ ] **Regenerate `lookup/ioctl_table.json` from `nv_escape.h`.** It is wrong
      today and `CUDA_IOCTL_MAP.md` inherits every error. Cheap, and it
      unblocks trusting any naming downstream. (arch-findings Finding 4)
- [ ] **Make `abi_probe_all.jsonl` the size authority** for `build_schema.py`
      and `replay.py`, instead of the headers. (Finding 5)
- [ ] **Fix `nv_sniff.c` to follow the `params` pointer** for
      `NV_ESC_RM_CONTROL`. Today every trace records that a control fired but
      not what it returned. (Finding 1, code.md F3)
- [ ] **Fix the `nv_sniff.c` out-of-bounds read** — `memcpy` of 4096 bytes when
      `_IOC_SIZE` is 0. This is the real reason UVM ioctls are excluded from
      handle inference. (code.md F1)
- [ ] Wire the rung-delta effect map into `metrics.py` as the Workstream-A1
      oracle, and add coverage as a first-class objective so a truncated
      candidate scores worse. (plan-v1 §4 A4, code.md F5)
- [ ] Replace `build_asi`'s 8000-character stdout tail with the canonical trace
      diff. (plan-v1 §3 "how??", code.md F6)

## Experiment B — GSP RPC tracer (blocked on renting a box)

Everything that can be prepared without a rented box is done, under
`cuda-ioctl-map/tools/effectmap/rpc_tracer/`:

- [x] Patches written and dry-run verified against the exact pinned
      `555.42.02` tag (`0001-kernel_gsp-rpc-trace-log.patch`,
      `0002-nv-procfs-rpc-trace-file.patch`).
- [x] B1/deploy — `setup_experiment_b.sh` automates the clone, patch, build
      (`src/nvidia` first — the gotcha the README calls out), `insmod`, and
      verifies `/proc/driver/nvidia/rpc_trace` exists, failing fast at each
      step so a bad build doesn't burn billed rental time.
- [x] B2 — superseded. Instead of exposing the existing 8-entry
      `pRpc->rpcHistory` ring through debugfs, the patches add a fresh
      65536-entry log read out through `/proc/driver/nvidia/rpc_trace`. More
      headroom, same hook site (`_kgspAddRpcHistoryEntry`).
- [x] B3 — `correlate_rpc_trace.py` joins a captured trace against
      `mig_classification.json` (all tiers, not just Tier 3 — Pattern B
      commands from `mig-rpc-mechanism-notes.md` forward a Tier-1/2 cmd
      verbatim). Verified against synthetic trace data, including a
      size-mismatch case.

- [ ] **Rent a Turing/Ampere box with root.** `hulk` cannot host this: it runs
      the proprietary module (`license: NVIDIA`), and the tracer patches the
      open one. This is the only remaining blocker.
      **Gotcha found 2026-07-30:** on Vast.ai, the *default* instance type is
      a Docker container and blocks `insmod` outright. Rent their **VM**
      instance type (KVM-based, see
      [docs.vast.ai/guides/instances/virtual-machines](https://docs.vast.ai/guides/instances/virtual-machines))
      or another bare-metal/full-VM provider — not a container instance.
- [ ] Run `setup_experiment_b.sh` on the box, then the correlation script,
      per `rpc_tracer/README.md`'s "Running the actual experiment" section.

## Known gaps in the effect map

- [ ] `module` and `launch` produce no observable Layer-1 change. Coverage for
      those rungs must come from the trace diff. (Finding 8)
- [ ] 6 commands have no accepted size at or below 65536; scan wider or accept
      they are variable-length.
- [ ] 55 commands are not size-enforced (the export lookup fails), so their
      recovered size is meaningless. They are excluded, not solved.
- [ ] Request templates cover 6 index-list commands. Extend the detection to
      the full `{count; list[]}` family by struct shape.
