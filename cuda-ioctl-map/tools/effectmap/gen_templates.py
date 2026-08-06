#!/usr/bin/env python3
"""
gen_templates.py — add request templates to the sweep command list.

Why this exists
---------------
Experiment A3, run with an all-zero params buffer, produced a trivial effect
map: every operation moved the same four commands and none of them was
framebuffer accounting, so the A4 correctness check failed.

The cause is that a large family of NVIDIA GET controls is *request-driven*.
The params buffer is `{ NvU32 count; struct { NvU32 index, data; } list[]; }`,
and the caller writes the indices it wants. Zeroed, `count == 0`, so the driver
either rejects the call or returns nothing. Measured directly on
NV2080_CTRL_CMD_FB_GET_INFO_V2:

    zeroed  -> NV_ERR_INVALID_ARGUMENT, no data at all
    filled  -> HEAP_FREE = 24603456 KiB idle, 22337472 KiB with 2 GiB held,
               matching nvidia-smi

So a zeroed sweep cannot see memory. This module writes the index list into the
head of the buffer, which turns those commands into usable state.

The templates are deliberately mechanical: for each known index-list command,
request indices 1..N. No per-command semantic knowledge is encoded beyond the
shape of the struct, which keeps this consistent with the project's rule of no
hand-authored per-ioctl knowledge.

Usage:
    python3 tools/effectmap/gen_templates.py \
        --cmds tools/effectmap/out/sweep_cmds_555.txt \
        --out  tools/effectmap/out/sweep_cmds_555_tmpl.txt
"""

from __future__ import annotations

import argparse
import struct
from pathlib import Path

# Commands whose params are { NvU32 count; {NvU32 index, NvU32 data}[] }.
# Confirmed by struct shape in the SDK headers, not by guesswork about meaning.
INDEX_LIST_COMMANDS = {
    "0x20801303",  # NV2080_CTRL_CMD_FB_GET_INFO_V2
    "0x20800102",  # NV2080_CTRL_CMD_GPU_GET_INFO_V2
    "0x20801823",  # NV2080_CTRL_CMD_BUS_GET_INFO_V2
    "0x20801201",  # NV2080_CTRL_CMD_GR_GET_INFO
    "0x00801201",  # NV0080_CTRL_CMD_GR_GET_INFO
    "0x00801301",  # NV0080_CTRL_CMD_FB_GET_INFO
    "0x00801801",  # NV0080_CTRL_CMD_BUS_GET_INFO
    "0x20801101",  # NV2080_CTRL_CMD_FIFO_GET_INFO
    "0x00801101",  # NV0080_CTRL_CMD_FIFO_GET_INFO
    "0x20802401",  # NV2080_CTRL_CMD_THERMAL_SYSTEM_GET_INFO
}

# Highest index worth asking for.
#
# MEASURED 2026-08-06 on 610.43.02, GPU 0. The old comment here claimed
# "indices above the driver's range are simply reported as unsupported in their
# own slot; they do not fail the call". **That is false.** The driver validates
# every index in the list, and if any one of them is out of range it returns
# status 0x0 with the whole response zeroed — no data at all, no error.
#
# The cliff is exact:
#     n <= 68  -> 35 populated data fields
#     n >= 69  -> 0 populated data fields, status still 0x00000000
#
# 68 is 0x44, one past NV2080_CTRL_FB_INFO_INDEX_LTC_MASK_7 (0x43), the highest
# index the 610 header defines. So ask for exactly the defined range and no
# more. Raising this "just in case" silently destroys the measurement.
#
# Raised 32 -> 68 on 2026-08-06, after the 610.43.02 re-probe. On 555 the driver
# enforced paramsSize 444 for FB_GET_INFO_V2, so capacity was 55 and anything
# above that was clamped anyway. 610 enforces 1028, so the defined index space
# is now reachable — including LTC_COUNT (0x22), LTS_COUNT (0x23),
# PSEUDO_CHANNEL_MODE (0x25) and LTC_MASK (0x2b), which the old cap never asked
# for.
#
# 68 indices = 4 + 68*8 = 548 bytes = 1096 hex characters. That fits
# sweep_controls.c's MAX_PREFILL (2048) and MAX_HEX_CHARS (4096). Do not raise
# this without re-checking both — test_effectmap.py enforces the relationship
# by reading the C's own #defines.
MAX_INDEX = 68


NORMALISED = {f"0x{int(c, 16):08X}" for c in INDEX_LIST_COMMANDS}


def make_template(size: int) -> str:
    """count = N, then N pairs of (index, 0). Truncated to fit `size`."""
    capacity = (size - 4) // 8
    n = min(MAX_INDEX, capacity)
    if n <= 0:
        return ""
    buf = struct.pack("<I", n)
    for idx in range(1, n + 1):
        buf += struct.pack("<II", idx, 0)
    return buf.hex()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cmds", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    out_lines, n_tmpl = [], 0
    for line in args.cmds.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            out_lines.append(line)
            continue
        parts = s.split()
        cmd, size = parts[0], int(parts[1])
        comment = " ".join(parts[2:]) if len(parts) > 2 else ""
        # Normalise via int, not str.upper(): "0x...".upper() capitalises the
        # x as well and never matches.
        if f"0x{int(cmd, 16):08X}" in NORMALISED:
            tmpl = make_template(size)
            if tmpl:
                out_lines.append(f"{cmd} {size} {tmpl}    {comment}")
                n_tmpl += 1
                continue
        out_lines.append(line)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
    print(f"[templates] added {n_tmpl} request template(s)")
    print(f"[templates] wrote {args.out}")


if __name__ == "__main__":
    main()
