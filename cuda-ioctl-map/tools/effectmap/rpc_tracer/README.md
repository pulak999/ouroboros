# RPC tracer — Experiment B (Layer 2)

Patches the **open** kernel module to log every GSP RPC's `(function, cmd,
paramsSize, timestamp)` to `/proc/driver/nvidia/rpc_trace`. This is the piece
`effect-map-experiment-v1.md` calls Experiment B — it answers "which GSP RPC
did this ioctl actually cause," which Layer 1 (the state-delta sweeper in the
parent directory) cannot see on its own.

**Status: written and verified to apply cleanly (`patch -p1 --dry-run`), but
never compiled or run — there is no rented box yet.** Read the whole file
before applying anything. See the mechanism analysis this is built on:
`control-folder/plans/mig-rpc-mechanism-notes.md`.

**Re-pinned 610.43.02 (2026-08-08).** hulk moved from 555.42.02 to 610.43.02;
both patches were re-verified against `refs/open-gpu-kernel-modules` at the
610.43.02 tag with `patch -p1 --dry-run --verbose`. Both apply — `0001` needs a
32-35 line context offset (the surrounding function moved slightly between
versions, content unchanged where it matters), `0002` needs a 13 line offset on
its second hunk. Neither is a content conflict. If you rent a box running a
different driver version, re-run the dry-run check against that exact tag
before trusting these offsets again — a clean `patch` dry-run costs nothing and
catches drift before it costs rental time.

**Two scripts in this directory automate the manual steps below:**
`setup_experiment_b.sh` runs the whole "Deploy" section (clone, patch, build,
insmod, verify) with a fail-fast check after every step; `correlate_rpc_trace.py`
runs the "Running the actual experiment" decode step and joins it against
`../out/mig_classification.json` instead of a manual cross-reference. Both are
still unrun against real hardware — the manual steps below are the ground
truth if a script and this doc ever disagree.

## Why this needs a different machine than hulk

hulk runs the **proprietary** module (`modinfo nvidia` → `license: NVIDIA`).
These patches touch the **open** module's source
(`open-gpu-kernel-modules`). You cannot patch a binary blob. Swapping hulk's
driver would need root and would disrupt other users' jobs — not viable
there under any circumstance.

**No MIG hardware is required.** Any GSP-offload GPU (Turing or newer) works
— this traces the generic `GSP_RM_CONTROL` RPC path, which every ioctl uses,
not something MIG-specific. Rent whatever's cheapest with root access; a
3090/4090 is plenty. Budget roughly $20 for a few hours.

## What the patches do

- `0001-kernel_gsp-rpc-trace-log.patch` — adds a 65536-entry log
  (`g_ouroborosRpcTraceLog[]`, ~1.5 MiB, plain global, no new locking) fed
  from the RM core's existing `_kgspAddRpcHistoryEntry()` hook in
  `src/nvidia/src/kernel/gpu/gsp/kernel_gsp.c`. That function already
  extracts `cmd`/`paramsSize` into `data0`/`data1` for the
  `GSP_RM_CONTROL` function — see `_kgspGetActiveRpcDebugData` in the same
  file — this patch just also appends them to a log deep enough to survive
  an entire experiment instead of the stock 8-entry ring.
- `0002-nv-procfs-rpc-trace-file.patch` — adds
  `/proc/driver/nvidia/rpc_trace`, a plain-text read-only file
  (`kernel-open/nvidia/nv-procfs.c`), templated directly off the existing
  `suspend_depth`/`suspend` handlers in the same file (same `single_open` /
  `single_release` pattern, nothing novel).

Both are additive only — no existing driver behavior is changed, nothing is
removed, and the existing 8-entry `rpcHistory` ring is untouched. The two
patches must be applied together; the `OuroborosRpcTraceEntry` struct layout
is duplicated (not shared via a header, to keep both patches self-contained)
and must stay in sync — if you edit one, edit the other.

## Why `NV_PRINTF`/dmesg was rejected as the readout path

The obvious alternative — just `NV_PRINTF(LEVEL_INFO, ...)` at the hook site
and read `dmesg` — was considered and rejected. On the Kernel RM,
`NV_PRINTF` routes through the NvLog/libos logging abstraction
(`src/nvidia/inc/libraries/utils/nvprintf.h`), which is gated by
`NV_PRINTF_LEVEL_ENABLED(level)` — a compile-time/build-config gate that
often strips `LEVEL_INFO` entirely in non-debug builds. Verifying that gate's
exact behavior without a compiler was not possible from this box, so a
plain global array + a hand-written procfs reader avoids the dependency on
NVIDIA's internal logging build flags entirely — every path in it is a
standard, well-understood Linux kernel primitive already proven to compile in
this exact file.

## Deploy — the crucial gotcha

**Do not just run the top-level `kernel-open` build.** NVIDIA's open driver
ships a **prebuilt binary fallback** for the RM core
(`kernel-open/nvidia/nv-kernel.o_binary`), and `nvidia.Kbuild` prefers it
unless you explicitly build `src/nvidia` from source first. If you skip that
step, your `kernel_gsp.c` edit is silently ignored and the resulting
`nvidia.ko` is built from the *unpatched* prebuilt blob.

```bash
# 1. Clone the exact tag these patches were verified against.
git clone --branch 610.43.02 https://github.com/NVIDIA/open-gpu-kernel-modules.git
cd open-gpu-kernel-modules

# 2. Apply both patches (from this repo).
patch -p1 < /path/to/ouroboros/cuda-ioctl-map/tools/effectmap/rpc_tracer/0001-kernel_gsp-rpc-trace-log.patch
patch -p1 < /path/to/ouroboros/cuda-ioctl-map/tools/effectmap/rpc_tracer/0002-nv-procfs-rpc-trace-file.patch

# 3. Build src/nvidia FROM SOURCE FIRST. This is the step that's easy to skip.
make -C src/nvidia
ls -la src/nvidia/_out/Linux_x86_64_*/nv-kernel.o   # must exist and be freshly built

# 4. Now build the kernel modules — this picks up the fresh nv-kernel.o
#    over the prebuilt blob because a real file now exists at that path.
make modules -j$(nproc)

# 5. Install the matching *proprietary userspace* components too (libcuda,
#    nvidia-smi, etc. must be the SAME version as the open-source tag you
#    cloned in step 1, whatever that is on the day you run this — 610.43.02
#    is what hulk runs as of 2026-08-06, not a fixed requirement). Get the
#    matching .run installer from NVIDIA, run it with --no-kernel-module
#    (you're supplying your own kernel module from steps 1-4).

# 6. Load it.
sudo rmmod nvidia_uvm nvidia_drm nvidia_modeset nvidia 2>/dev/null
sudo insmod kernel-open/nvidia.ko
sudo insmod kernel-open/nvidia-modeset.ko   # if present/needed
sudo insmod kernel-open/nvidia-uvm.ko

# 7. Confirm the new file exists before doing anything else.
cat /proc/driver/nvidia/rpc_trace
# expect: "# ts function data0 data1" and a "# total_entries_ever_written=N"
# line, N > 0 if anything has touched the GPU since boot (nvidia-smi does).
```

If step 7 fails (file missing, or `insmod` errors): **stop, do not
troubleshoot blind against billed rental time.** Re-check step 3's build log
for the two `OuroborosRpcTraceEntry` symbols
(`nm src/nvidia/_out/Linux_x86_64_*/nv-kernel.o | grep ouroboros`) before
spending more time — if they're not in the object file, the source edit
didn't take (wrong file version, patch applied to the wrong tree, or a
build-cache issue), not a design problem with the patches themselves.

## Running the actual experiment, once loaded

```bash
# Baseline: read the log once before doing anything, note total_entries.
cat /proc/driver/nvidia/rpc_trace > before.txt

# Trigger a specific ioctl sequence — e.g. the userspace MIG commands from
# mig-command-classification.md Tier 1/2, or a plain cuInit() run for the
# non-MIG baseline correlation.
nvidia-smi mig -lgip     # or whatever single operation you're isolating

# Read again immediately after.
cat /proc/driver/nvidia/rpc_trace > after.txt

# The new lines in after.txt beyond before.txt's total_entries_ever_written
# are the GSP RPCs that specific operation caused.
```

Decode `function` against `NV_VGPU_MSG_FUNCTION_*` in
`src/common/sdk/nvidia/inc/vgpu/rpc_headers.h` (or just check whether it's
`GSP_RM_CONTROL` — the overwhelming majority will be). For `GSP_RM_CONTROL`
rows, `data0` is the inner `cmd` (cross-reference against
`mig-command-classification.md`'s tables) and `data1` is `paramsSize`. Per
`mig-rpc-mechanism-notes.md`'s gotcha, this does **not** capture the payload
itself (e.g. the `bValid` create/delete flag) — only which command and how
big. If that turns out to matter, extend `data0`/`data1` capture in
`_kgspGetActiveRpcDebugData` (already does per-function special-casing —
follow its existing pattern) rather than changing the trace log's shape.

## One-shot decode script

```bash
python3 - <<'EOF'
import sys
with open("after.txt") as f:
    lines = [l for l in f if l.strip() and not l.startswith("#")]
for l in lines:
    ts, func, cmd, size = l.split()
    print(f"ts={ts} func={func} cmd={cmd} paramsSize={size}")
EOF
```

## Cleanup

`sudo rmmod nvidia_uvm nvidia_modeset nvidia; reboot` restores the box to
whatever it shipped with, if the rental is ending and you want a clean
handback. The patches are additive-only and don't touch anything the box's
next renter would notice if you don't bother, but rebooting is cheap
insurance.
