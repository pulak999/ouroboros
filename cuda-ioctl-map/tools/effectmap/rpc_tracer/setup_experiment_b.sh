#!/usr/bin/env bash
# setup_experiment_b.sh — automates README.md steps 1-7 on a rented box.
#
# Run this AS ROOT on a rented Turing/Ampere GPU box (no MIG hardware needed).
# It clones 610.43.02, applies both rpc_tracer patches, builds src/nvidia from
# source FIRST (the step README.md calls "the crucial gotcha" — skip it and
# nvidia.Kbuild silently prefers the prebuilt nv-kernel.o_binary blob and your
# edit never takes effect), builds the kernel modules, swaps them in, and
# verifies /proc/driver/nvidia/rpc_trace exists.
#
# Per README.md: if the final check fails, STOP. Do not troubleshoot blind
# against billed rental time — re-read the nm check's output first.
#
# Usage: sudo ./setup_experiment_b.sh [workdir]
set -euo pipefail

WORKDIR="${1:-$HOME/experiment-b}"
PATCH_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Must match the PROPRIETARY driver you install on the rented box in step 5
# (README.md) — not hulk's version by definition, hulk's own version.
# 610.43.02 is what hulk runs as of 2026-08-06; re-verify both patches with
# `patch -p1 --dry-run --verbose` against whatever tag you actually rent
# before trusting this default (README.md's "Re-pinned" note explains why).
TAG="610.43.02"
REPO_URL="https://github.com/NVIDIA/open-gpu-kernel-modules.git"

if [ "$(id -u)" -ne 0 ]; then
    echo "[setup] must run as root (module load/unload needs it)" >&2
    exit 1
fi

echo "[setup] workdir: $WORKDIR"
mkdir -p "$WORKDIR"
cd "$WORKDIR"

if [ ! -d open-gpu-kernel-modules ]; then
    echo "[setup] cloning $TAG"
    git clone --branch "$TAG" --depth 1 "$REPO_URL"
fi
cd open-gpu-kernel-modules

CURRENT_TAG="$(git describe --tags 2>/dev/null || echo unknown)"
if [ "$CURRENT_TAG" != "$TAG" ]; then
    echo "[setup] ERROR: checked-out tag is '$CURRENT_TAG', expected '$TAG'." >&2
    echo "[setup] the patches are only verified against $TAG. Pin it first." >&2
    exit 1
fi

echo "[setup] applying rpc_tracer patches"
patch -p1 < "$PATCH_DIR/0001-kernel_gsp-rpc-trace-log.patch"
patch -p1 < "$PATCH_DIR/0002-nv-procfs-rpc-trace-file.patch"

echo "[setup] building src/nvidia from source FIRST (the crucial gotcha)"
make -C src/nvidia -j"$(nproc)"

NVKERNEL_O="$(find src/nvidia/_out -maxdepth 2 -name 'nv-kernel.o' 2>/dev/null | head -1)"
if [ -z "$NVKERNEL_O" ]; then
    echo "[setup] ERROR: src/nvidia build did not produce nv-kernel.o. Stop here." >&2
    exit 1
fi
if ! nm "$NVKERNEL_O" 2>/dev/null | grep -q g_ouroboros; then
    echo "[setup] ERROR: nv-kernel.o has no g_ouroboros* symbols. The patched" >&2
    echo "[setup] source did not make it into this build. Stop, do not proceed" >&2
    echo "[setup] to insmod — re-check the patch and tag before retrying." >&2
    exit 1
fi
echo "[setup] confirmed patched symbols in $NVKERNEL_O"

echo "[setup] building kernel modules"
make modules -j"$(nproc)"

for m in kernel-open/nvidia.ko kernel-open/nvidia-uvm.ko; do
    if [ ! -f "$m" ]; then
        echo "[setup] ERROR: expected module $m was not built. Stop here." >&2
        exit 1
    fi
done

echo "[setup] unloading any existing nvidia modules"
rmmod nvidia_uvm 2>/dev/null || true
rmmod nvidia_drm 2>/dev/null || true
rmmod nvidia_modeset 2>/dev/null || true
rmmod nvidia 2>/dev/null || true

echo "[setup] loading patched modules"
insmod kernel-open/nvidia.ko
[ -f kernel-open/nvidia-modeset.ko ] && insmod kernel-open/nvidia-modeset.ko
insmod kernel-open/nvidia-uvm.ko

echo "[setup] verifying /proc/driver/nvidia/rpc_trace"
if [ ! -r /proc/driver/nvidia/rpc_trace ]; then
    echo "[setup] ERROR: rpc_trace file missing after insmod." >&2
    echo "[setup] STOP. Do not troubleshoot blind against billed rental time." >&2
    echo "[setup] Re-check the nm output above before spending more time." >&2
    exit 1
fi
cat /proc/driver/nvidia/rpc_trace

cat <<'EOF'

[setup] OK. Experiment B tracer is live.

[setup] Two things this script does NOT do, per README.md step 5:
EOF
echo "  1. Install the matching *userspace* driver (libcuda, nvidia-smi) at" \
     "$TAG, using NVIDIA's .run installer with --no-kernel-module." \
     "Version-mismatched userspace against this kernel module is untested" \
     "territory."
cat <<'EOF'
  2. Run the actual experiment. See README.md "Running the actual experiment,
     once loaded" — snapshot rpc_trace, trigger one operation, snapshot again,
     then:
       python3 correlate_rpc_trace.py --before before.txt --after after.txt \
           --classification ../out/mig_classification.json
EOF
