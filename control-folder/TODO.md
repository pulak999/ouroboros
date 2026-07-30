# TODO — Ouroboros

Ordered by dependency. Status as of 2026-07-30.

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

## Experiment B — GSP RPC tracer (blocked)

- [ ] Rent a Turing/Ampere box with root. **hulk cannot host this**: it runs
      the proprietary module (`license: NVIDIA`), and the tracer patches the
      open one. This, not the absence of MIG, is the blocker.
- [ ] B1 — build and `insmod` the unmodified open module, run a CUDA program.
      Note the plan says 555.42.02; the vendored submodule is **610.43.02**.
      Pick one and pin it.
- [ ] B2 — expose `pRpc->rpcHistory` through debugfs before attempting full
      message logging.
- [ ] B3 — correlate against the 24 Tier-3 MIG RPCs listed in
      `mig-command-classification.md`, whose paramsSize values are already
      recovered.

## Known gaps in the effect map

- [ ] `module` and `launch` produce no observable Layer-1 change. Coverage for
      those rungs must come from the trace diff. (Finding 8)
- [ ] 6 commands have no accepted size at or below 65536; scan wider or accept
      they are variable-length.
- [ ] 55 commands are not size-enforced (the export lookup fails), so their
      recovered size is meaningless. They are excluded, not solved.
- [ ] Request templates cover 6 index-list commands. Extend the detection to
      the full `{count; list[]}` family by struct shape.
