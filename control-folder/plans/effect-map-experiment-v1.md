# Effect-Map Experiment v1

**Date:** 2026-07-29
**Status:** tactical experiment plan. Serves `ouroboros-plan-v1.md`. Does **not**
fork or amend the north star.
**Origin:** the MIG memory-isolation question, reduced to the part Ouroboros can
actually answer.

---

## 0. The reframe

The question is not "what is the ABI." The ABI is already open: **2445 control
commands** in `open-gpu-kernel-modules/src/common/sdk/nvidia/inc/ctrl/`, with
exact struct definitions. Recovering it is a solved problem.

The question is **which command causes which configuration change**. Call that
the **effect map**. Nobody has published one.

This changes the deliverable. `spec.json` currently answers *"what does this
ioctl look like."* The effect map answers *"what does this ioctl do."*

---

## 1. Why MIG hardware is not required

MIG configuration has this shape:

```
userspace ioctl → kernel RM arithmetic → GSP RPC → hardware change → readback
```

**Every GPU configuration knob has that same shape.** MIG needs A100 plus root.
Other knobs do not. So build and validate the machine on knobs you have. MIG
then drops in as one row of the corpus when the hardware appears.

This is the whole argument for running now instead of waiting.

---

## 2. Two observables, two layers

### Layer 1 — state delta
- **Needs:** nothing. No root, no MIG. Runs on hulk today.
- The readback surface is **969 `GET_*` control commands**, 324 of them on
  `NV2080` alone.
- Snapshot = sweep every readable control, record status and response bytes.
- `effect(cmd) = diff(S_after, S_before)`

### Layer 2 — RPC fan-out
- **Needs:** root, and the open kernel module. **No MIG.** Any GSP GPU (Turing+).
- Patch the GSP message path in the open module. Log `(function, cmd, params)`.
- `effect_rpc(cmd) = the set of GSP RPCs that fired`

The pair — state delta plus RPC set — **is** "what commands lead to what config."

---

## 3. Experiment A — state-delta effect map

**Where:** hulk. **Privilege:** none. **Hardware:** any NVIDIA GPU.

### A1 — build the sweeper

1. `open("/dev/nvidiactl")`, then `NV_ESC_RM_ALLOC_ROOT` → `hClient`.
2. Allocate `NV01_DEVICE_0` + `NV20_SUBDEVICE_0`. Curriculum rung 1 in
   `ouroboros-plan-v1.md` §6 already covers this ladder.
3. For each of the 324 `NV2080_CTRL_CMD_*GET*` commands: issue
   `NV_ESC_RM_CONTROL` with the header-declared `paramsSize`. Record
   `(cmd, status, response_bytes)`.
4. Output: `state_vector.json`.

**Free self-check — the size oracle.** `control.c:452` rejects
`paramsSize != ctrlParamsSize` **before** object resolution at line 516. So:

| probe | result |
|---|---|
| bogus `hObject`, wrong `paramsSize` | `NV_ERR_INVALID_ARGUMENT` (size check fires first) |
| bogus `hObject`, correct `paramsSize` | passes the size check, fails later with a different code |
| command absent from the driver's export table | size check skipped entirely — third distinct code |

This validates the sweeper's size table against the **shipped binary** with no
valid objects, no privilege, and no GPU features. It also measures the delta
between the open SDK headers and the proprietary module actually loaded. Run it
first; it is cheap and it catches table drift before it corrupts the results.

### A2 — noise floor. **This is the gate.**

Sweep twice with nothing in between. Diff.

Clocks, temperatures, utilization, timestamps and free-FB counters will move on
their own. Build a **noise mask** from the null diff. Report how many of the 324
fields are stable.

> **Stop condition:** if fewer than roughly half the readable fields survive a
> null diff, Layer 1 is too noisy to carry the experiment. Say so and move to
> Layer 2. Do not skip this step and do not soften it later.

Note hulk is a shared box. Other users' jobs move the noise floor. Measure at a
quiet time and record the machine load alongside the mask.

### A3 — command corpus, non-privileged

Use CUDA operations as the commands. All are non-root, and Ouroboros already
traces them:

`cuInit` · `cuCtxCreate` · `cuCtxDestroy` · `cuMemAlloc(size)` · `cuMemFree` ·
`cuStreamCreate` · `cuModuleLoad` · `cuLaunchKernel` · `cuMemcpyHtoD`

Protocol per command: `snapshot → op → snapshot → diff`, N repetitions.

Output: `effect_map.json` — `{op: [changed fields, with a reproducibility count]}`.

### A4 — scoring

- **Reproducibility.** A field counts only if it changes in at least *k* of *N*
  repetitions.
- **Specificity.** A field that changes for every command carries no
  information. Rank by (changes for this command) / (changes for any command).
- **Correctness check.** For a few commands the answer is known —
  `cuMemAlloc(2GiB)` must move FB accounting. Use those to validate the whole
  pipeline before trusting any unknown row.

### A5 — wire it to the loop

This is **Workstream A1** from `ouroboros-plan-v1.md` §4, delivered concretely.
The effect map is a richer and harder-to-fake reward than "replay printed
`0 failed`." A candidate that reproduces the ioctl sequence but not the state
delta must score lower. That closes the truncation reward-hack that §4's A4
worries about, at no extra cost.

**A5 is the part that stands alone.** Even if Layer 2 never happens and MIG
never appears, the oracle upgrade is worth the work by itself.

---

## 4. Experiment B — RPC fan-out tracer

**Where:** *not hulk.* **Privilege:** root. **Hardware:** any GSP GPU, no MIG.

### Constraint, stated plainly

hulk runs the **proprietary** module — `modinfo nvidia` reports
`license: NVIDIA`. The tracer patches the **open** module. Replacing the driver
on hulk needs root and would disrupt other users. It is not viable there.

**This — not the absence of MIG — is the real blocker on Layer 2.**

Cheapest unblock: rent a Turing or Ampere box with root. A 3090 or 4090 is
enough. Roughly $0.20–0.40/hr; budget about $20. Confirm the GPU is on the
open-module support list **before** renting.

### B1 — baseline

Build and `insmod` the **unmodified** open 555.42.02. Run a CUDA program.
If this fails, stop. Everything downstream depends on it.

### B2 — add the trace point

Two options, least invasive first:

1. **Read the existing ring.** `pRpc->rpcHistory` already records function and
   timestamps (`kernel_gsp.c:302`, `RPC_HISTORY_DEPTH` entries). Expose it via
   debugfs. Minimal perturbation. **Start here.**
2. **Full logging.** Hook `message_queue_cpu.c` to dump
   `(function, cmd, params)` per message. More data, more timing perturbation,
   more risk of changing the behaviour you are measuring.

### B3 — correlate

Run the same corpus as A3. Emit `(ioctl cmd) → (GSP RPC set)`.

### B4 — payoff

`spec.json` gains a `downstream_rpc` field per ioctl. A two-layer specification:
what the call looks like, and what it causes on the other side of the GSP
boundary. That artifact does not exist in the literature.

---

## 5. What would falsify this

| Failure | Likelihood | Response |
|---|---|---|
| A2: state vector is all noise | **Highest** | Noise mask + repetition. If that fails, curate a stable subset or drop to Layer 2. |
| Effect map is trivial — every op moves the same 3 fields | Medium | Layer 1 is dead. Layer 2 becomes the whole experiment. |
| B1: open module will not build or load | Medium | Check the support list before renting. Try a different GPU generation. |
| RPC fan-out is uninformative — every ioctl produces one identical wrapper | Medium | You learn this in a day. Cheap to find out. |
| Size oracle does not discriminate (A1) | Low | Verified in source, but confirm empirically before building on it. |

---

## 6. MIG, when the hardware arrives

MIG becomes one row of the A3 corpus. Nothing in the pipeline changes:

- **Command:** `nvidia-smi mig -cgi 19`
- **Expected Layer-1 delta:** `GPU_GET_PARTITIONS`,
  `GPU_GET_ACTIVE_PARTITION_IDS`, `GPU_GET_PARTITION_CAPACITY`, plus FB
  accounting
- **Expected Layer-2 RPCs:** `INTERNAL_MIGMGR_SET_GPU_INSTANCES`,
  `INTERNAL_MEMSYS_SET_PARTITIONABLE_MEM`

### The boundary, accepted going in

Even with both layers working, `INTERNAL_MEMSYS_SET_PARTITIONABLE_MEM` carries a
**start address and an end address**. That is all.

- Layer 1 on MIG hardware tells you **that** the partition changed.
- Layer 2 tells you **which command** changed it.
- Neither tells you **how the GSP decided** the cache and channel assignment,
  because that decision is not on the wire.

Do not plan as though a deeper trace will appear. It will not.

---

## 7. First three moves

1. **A1 + A2 on hulk.** Non-root, days not weeks. The noise-floor gate is the
   real deliverable — a negative result here is a genuine finding and it is
   cheap.
2. **A3 + A4** with the CUDA corpus. This is the Workstream A1 oracle upgrade.
   It stands alone.
3. **Rent a box and run B1 only.** Confirm you can build and load the open
   module before spending anything on the tracer.

Do not start B2 before A2 passes. If Layer 1 has no signal, the correlation in
B3 has nothing to correlate against.
