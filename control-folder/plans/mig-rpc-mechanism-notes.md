# MIG RPC mechanism notes — how each command crosses to GSP

**Date:** 2026-07-30. Source-level companion to
`mig-command-classification.md` (the machine-generated, driver-measured
size/tier table — regenerate that with `classify_mig.py`, don't hand-edit
it). This doc answers a different question: **not which commands exist and
what size they are, but *how* each one gets from a userspace ioctl to GSP,**
traced directly in `open-gpu-kernel-modules` (tag 555.42.02, matching hulk's
loaded module) with file:line citations. Regenerate the sibling doc as often
as needed; this one only goes stale if the driver's call graph changes.

---

## The finding that matters most for the RPC tracer

There is **no dedicated MIG RPC channel**. Enumerating every `NV_RM_RPC_*`
entry point in the driver (`grep -rohE "NV_RM_RPC_[A-Z0-9_]+" src/nvidia/src/kernel/`
— 50 distinct macros) turns up no `NV_RM_RPC_MIG_*` or `NV_RM_RPC_PARTITION_*`.
Every MIG-related RPC rides the single generic
`NV_RM_RPC_CONTROL` / `NV_VGPU_MSG_FUNCTION_GSP_RM_CONTROL` wrapper
([rpc.c:8994](open-gpu-kernel-modules/src/nvidia/src/kernel/vgpu/rpc.c#L8994)), distinguished only by the `cmd`
field. **One hook point on that path, filtered by the cmd corpus in the
sibling doc's tables, catches all of it.**

## Five forwarding patterns — not all commands translate the same way

**Pattern A — translate to a different, internal-only cmd.** The common case.
`SET_PARTITIONING_MODE` (`0x20800183`) issues
`INTERNAL_MIGMGR_SET_PARTITIONING_MODE` (`0x20800AA3`) —
[kernel_mig_manager.c:7173](open-gpu-kernel-modules/src/nvidia/src/kernel/gpu/mig_mgr/kernel_mig_manager.c#L7173). Same for `SET_PARTITIONS` →
`INTERNAL_MIGMGR_SET_GPU_INSTANCES` (`0x20800AA5`,
[:7233](open-gpu-kernel-modules/src/nvidia/src/kernel/gpu/mig_mgr/kernel_mig_manager.c#L7233)) and `GET_PARTITIONS` →
`INTERNAL_MIGMGR_GET_GPU_INSTANCES` (`0x20800AA6`, [:7456](open-gpu-kernel-modules/src/nvidia/src/kernel/gpu/mig_mgr/kernel_mig_manager.c#L7456)).

**Pattern B — verbatim passthrough, same cmd number.** The trap. `NVC637
EXEC_PARTITIONS_CREATE` (`0xc6370101`) forwards the caller's exact `cmd`
unchanged:
```c
// gpu_instance_subscription.c:421
NV_RM_RPC_CONTROL(pGpu, pRmCtrlParams->hClient,
                  pRmCtrlParams->hObject, pRmCtrlParams->cmd,   // <- same 0xc6370101
                  pRmCtrlParams->pParams, pRmCtrlParams->paramsSize, status);
```
gated at `IS_VIRTUAL(pGpu) || IS_GSP_CLIENT(pGpu)`
([gpu_instance_subscription.c:414](open-gpu-kernel-modules/src/nvidia/src/kernel/gpu/mig_mgr/gpu_instance_subscription.c#L414)). **A tracer that only pattern-matches
`INTERNAL_` names will miss this.** It shows up on the GSP wire under its
public, userspace-facing name.

**Pattern C — one-time setup, not per-call.**
`INTERNAL_MEMSYS_SET_PARTITIONABLE_MEM` (`0x20800A51`) — the command that
carves the actual framebuffer byte range — fires exactly once, the first time
a GPU instance is created after MIG is enabled
([mem_mgr.c:2309](open-gpu-kernel-modules/src/nvidia/src/kernel/gpu/mem_mgr/mem_mgr.c#L2309), call site [kernel_mig_manager.c:3165](open-gpu-kernel-modules/src/nvidia/src/kernel/gpu/mig_mgr/kernel_mig_manager.c#L3165)).
Every later instance's byte range is pure host-side arithmetic
(`kmemsysSwizzIdToVmmuSegmentsRange_GA100`,
[kern_mem_sys_ga100.c:241](open-gpu-kernel-modules/src/nvidia/src/kernel/gpu/mem_sys/arch/ampere/kern_mem_sys_ga100.c#L241) — see
`gpu-virt/motivation/docs/mig-memory-isolation/01-fb-partitioning-and-allocation.md`).
**Don't expect a repeated `SET_PARTITIONABLE_MEM` per instance.**

**Pattern D — bundled burst at enable-time.** Five `INTERNAL_STATIC_*` reads
fire together, once, when MIG mode transitions to enabled
(`kmigmgrLoadStaticInfo_KERNEL`, [kernel_mig_manager.c:1355](open-gpu-kernel-modules/src/nvidia/src/kernel/gpu/mig_mgr/kernel_mig_manager.c#L1355)):
`INTERNAL_STATIC_KMIGMGR_GET_PARTITIONABLE_ENGINES` (`0x20800A65`),
`INTERNAL_STATIC_GRMGR_GET_SKYLINE_INFO` (`0x20800AA2`),
`INTERNAL_STATIC_KMIGMGR_GET_COMPUTE_PROFILES` (`0x20800ABA`),
`INTERNAL_STATIC_KMIGMGR_GET_PROFILES`,
`INTERNAL_STATIC_KMIGMGR_GET_SWIZZ_ID_FB_MEM_PAGE_RANGES` (`0x20800A66`) —
plus `INTERNAL_KMEMSYS_GET_MIG_MEMORY_CONFIG` and
`INTERNAL_MEMSYS_GET_MIG_MEMORY_PARTITION_TABLE` (`0x20800A6B`) from the
memory side. **Expect a 7-RPC block, not independent per-feature signals.**

**Pattern E — answered from cache, zero RPC.**
`GET_ACTIVE_PARTITION_IDS` reads `pKernelMIGManager->swizzIdInUseMask`
locally, no RPC ([kernel_mig_manager.c:6989](open-gpu-kernel-modules/src/nvidia/src/kernel/gpu/mig_mgr/kernel_mig_manager.c#L6989)).
`DESCRIBE_PARTITIONS` likewise — no `pRmApi->Control` anywhere in
`kmigmgrDescribeGPUInstances_IMPL` ([:3839](open-gpu-kernel-modules/src/nvidia/src/kernel/gpu/mig_mgr/kernel_mig_manager.c#L3839)); it serves from the Pattern-D
cache. **These are fine Layer-1 probes and useless as Layer-2 (RPC) probes —
they will never appear on the wire no matter how many times you call them.**

## Gotchas

**One command, two directions.** `INTERNAL_MIGMGR_SET_GPU_INSTANCES` handles
both create and delete. The direction lives in the payload's
`partitionInfo[0].bValid` field, not the cmd ID — same constant at
[kernel_mig_manager.c:7233](open-gpu-kernel-modules/src/nvidia/src/kernel/gpu/mig_mgr/kernel_mig_manager.c#L7233) (create) and [:7268](open-gpu-kernel-modules/src/nvidia/src/kernel/gpu/mig_mgr/kernel_mig_manager.c#L7268) (delete).
**The tracer must decode the payload, not just log the cmd ID**, or create
and delete look identical in the log.

**Dead code, now independently confirmed.** `INTERNAL_MIGMGR_CONFIGURE_GPU_INSTANCE`
(`0x20800AA4`) has zero call sites anywhere in the CPU-side open source at
this driver version (checked across all of
`src/nvidia/src/kernel/gpu/mig_mgr/`, including the Hopper arch override).
**This is now cross-validated two ways**: the source-level check here found
no caller, and the sibling doc's independent, driver-measured probe marks it
`**absent**` in the actual 555.42.02 binary's export table. Two different
methods, same answer — trust it. If it ever shows up on the wire, that's a
real finding, not a search-miss.

**`EXPORT`/`IMPORT` mapping is unverified.** `INTERNAL_MIGMGR_EXPORT_GPU_INSTANCE`
/ `IMPORT_GPU_INSTANCE` (live-migration path) mirror the `NVC637`
`EXPORT`/`IMPORT` names but this pass didn't trace their call sites. Treat as
plausible, not confirmed.

## The lifecycle, in the driver's own words

`_kmigmgrProcessGPUInstanceEntry` (behind `SET_PARTITIONS`) carries this
comment verbatim ([kernel_mig_manager.c:7209](open-gpu-kernel-modules/src/nvidia/src/kernel/gpu/mig_mgr/kernel_mig_manager.c#L7209)):

```
// Mirrored GPU Instance Management:
// 1: CPU enable MIG        2: GSP enable MIG
// 3: GSP create gpu instance   4: CPU create gpu instance
// 5: CPU delete gpu instance   6: GSP delete gpu instance
// 7: GSP disable MIG       8: CPU disable MIG
```

| Step | What fires | Pattern |
|---|---|---|
| 1 | Local: `bMIGEnabled` flips on first/last instance | — |
| 2 | `INTERNAL_MIGMGR_SET_PARTITIONING_MODE`; Pattern-D static-info burst fires from `kmigmgrSetMIGState` | A + D |
| 3+4 | `INTERNAL_MIGMGR_SET_GPU_INSTANCES` (bValid=1); local runlist/handle build; memory carve (RPC only if first instance) | A + C + local |
| 5+6 | Same cmd, bValid=0 | A, reused |
| 7+8 | Mirror of step 2 when `swizzIdInUseMask` returns to 0 | A + D |

This 8-step skeleton is the ordering constraint that makes MIG a genuine
multi-step target for the inverse-search direction discussed for Ouroboros —
a candidate that fires step 3 before step 2 must fail, and a good tracer
should be able to say why.

Compute-instance create/delete (`NVC637 EXEC_PARTITIONS_CREATE`/`DELETE`,
Pattern B) is a separate, shorter lifecycle nested inside an already-valid
GPU instance — subscribe via `NVC637` alloc, then `EXEC_PARTITIONS_CREATE`
forwarded verbatim, confirmed at [gpu_instance_subscription.c:414-428](open-gpu-kernel-modules/src/nvidia/src/kernel/gpu/mig_mgr/gpu_instance_subscription.c#L414-L428).

## Practical instruction for the RPC tracer

Log every `(cmd, payload)` pair on the `NV_RM_RPC_CONTROL` path — not just an
`INTERNAL_` string match, per Pattern B. Decode `bValid` where present, per
the gotcha above. Expect the enable-transition burst as one block (Pattern
D). Expect `SET_PARTITIONABLE_MEM` exactly once per MIG-enable cycle, not
once per instance (Pattern C). Expect `EXEC_PARTITIONS_CREATE` to show its
original `0xc637xxxx` number on the wire, not a translated one (Pattern B).
