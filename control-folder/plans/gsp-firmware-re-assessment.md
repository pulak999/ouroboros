# Can we reverse engineer cache and bandwidth from the GSP firmware?

**Date:** 2026-08-06
**Question:** the cache and bandwidth decision lives in closed GSP firmware.
Can we recover it by reverse engineering that firmware?
**Answer in one line:** the part that decides is encrypted, but you do not need
it — read the registers the firmware programmed instead.

All numbers below are measured on hulk today. Nothing here is inferred.

---

## 1. The firmware is on this box and it is readable

```
/lib/firmware/nvidia/610.43.02/gsp_ga10x.bin    84 277 400 bytes   mode 644
/lib/firmware/nvidia/610.43.02/gsp_tu10x.bin    29 352 832 bytes   mode 644
/lib/firmware/nvidia/610.43.02/ucodes_ga10x.bin     31 744 bytes
/lib/firmware/nvidia/610.43.02/ucodes_tu10x.bin     12 032 bytes
```

No root is needed to read them. The version matches the loaded driver.

`gsp_ga10x.bin` is the multi-chip container. Its plaintext strings name the
per-chip payloads it holds: `kernel_ga10x.elf`, `kernel_gh100.elf`,
`kernel_gb10x.elf`, `kernel_gb20x.elf`, `kernel_gr10x.elf`, plus
`rm.bindata.bin`. So Ampere through Rubin ship in one file.

## 2. The container structure

`file` reports a RISC-V 64-bit ELF, "not stripped". That label is misleading.
The symbol table holds **4 symbols**. It describes the container, not the code.

```
[ 1] .fwimage         PROGBITS   size 0x5053000   (84 MB — the real payload)
[ 3] .fwversion       PROGBITS   size 0xa
[ 4..15] .fwsignature*  PROGBITS  size 0x1000 each  (12 signatures, one per chip)
[16] .symtab          SYMTAB     size 0x60         (4 symbols)
```

Twelve 4 KB signature sections confirm the image is signed per chip.

## 3. The entropy map — this is the decisive measurement

Shannon entropy per 4 MB chunk of `gsp_ga10x.bin`:

| Offset | Entropy (bits/byte) | Reading |
|---|---|---|
| 0 MB | 5.649 | code and data, **not encrypted** |
| 4 MB | 7.123 | compressed, **not encrypted** |
| 8 MB | 7.102 | compressed, **not encrypted** |
| 12 MB | 6.257 | compressed, **not encrypted** |
| 16 MB | 6.220 | compressed, **not encrypted** |
| 20 MB → 76 MB | **8.000** (flat) | **encrypted** |
| 80 MB | 7.436 | trailer |

The image splits cleanly in two.

**Front, about 18 MB, analysable.** It holds 14 nested RISC-V ELF executables,
the first at offset `0x6e040`. Extracting one gives a valid statically linked
RISC-V executable. Plaintext source paths survive, for example
`/gpu_drv/uproc/os/libos-v3.1.0/src/common/nvriscv-2.0/sbi.c`.

**Back, about 64 MB, encrypted.** Entropy is exactly 8.000 across 14 consecutive
chunks. That is 76% of the image and it is indistinguishable from random.

## 4. What each region actually contains

| Region | Contents | Does it decide cache and bandwidth? |
|---|---|---|
| Front 18 MB | LIBOS v3.1.0 microkernel, RISC-V SBI layer, per-chip bootloaders, the RPC message transport | **No.** This is the OS the RM runs on, not the RM. |
| Back 64 MB | GSP-RM proper — including AMAPLIB | **Yes, and it is encrypted.** |

The booter ucode decrypts the back region into WPR (Write Protected Region) at
boot, with keys fused into the chip. WPR is hardware-protected against host
reads. That protection exists to stop precisely the dump you would need.

## 5. Verdict on firmware reverse engineering

**Path B — reverse engineer the plaintext 18 MB.** Feasible today, no root, no
special tools. You recover LIBOS, the boot chain, and the RPC transport. You do
**not** recover the cache or bandwidth policy. Useful background. Wrong target.

**Path C — break into the encrypted 64 MB.** You would need to extract keys from
signed Falcon booter ucode, or dump WPR from a running GPU. Both are hardened
against exactly that. Months of work, a real chance of zero, and it is not the
thesis.

**One more honest limit.** Even a full decompile may not answer the question.
`mig-memory-isolation/03-hardware-enforcement-l2-mc.md` Part F already places the
final gate in **silicon**. AMAPLIB gives you the address-to-slice swizzle. The
bandwidth arbitration between partitions is hardware. Firmware gives you the
mapping, not the arbitration.

---

## 6. Path A — the route that actually works

Do not read what the firmware *says*. Read what the firmware *did*.

### 6.1 The mechanism exists and is in this driver

`NV2080_CTRL_CMD_GPU_EXEC_REG_OPS` = **`0x20800122`**. It performs register read
and write operations. Your own probe already found it:

```json
{"cmd":"0x20800122","present":true,"found_size":48,
 "accept_status":"0x00000057","probe_status":"0x0000001F"}
```

Present. Driver-enforced `paramsSize` 48. Reachable over `NV_ESC_RM_CONTROL`.

The request element:

```c
typedef struct NV2080_CTRL_GPU_REG_OP {
    NvU8  regOp;      NvU8  regType;   NvU8 regStatus;  NvU8 regQuad;
    NvU32 regGroupMask;  NvU32 regSubGroupMask;
    NvU32 regOffset;                          // <- the register you want
    NvU32 regValueHi;    NvU32 regValueLo;
    NvU32 regAndNMaskHi; NvU32 regAndNMaskLo;
} NV2080_CTRL_GPU_REG_OP;
```

`regType` includes `TYPE_GLOBAL` (0x00) and `TYPE_FB` (0x20).

Related commands, also worth probing: `NV2080_CTRL_CMD_GPU_EXEC_REG_OPS_NOPTRS`,
`NV83DE_CTRL_CMD_DEBUG_EXEC_REG_OPS`, `NVB0CC_CTRL_CMD_EXEC_REG_OPS`.

### 6.2 The anchor register

The published hwref set gives exactly one LTC register, for Turing:

```c
// src/common/inc/swref/published/turing/tu102/dev_ltc.h
#define NV_PLTCG_LTC0_LTS0_L2_CACHE_ECC_UNCORRECTED_ERR_COUNT  0x001404f8 /* RW-4R */
```

GA100 ships **no** `dev_ltc.h` in the published set. But one register is enough
to anchor the aperture. `NV_PLTCG` sits at about `0x140000`. From that anchor you
enumerate the LTC and LTS register file by scanning offsets and watching which
ones respond.

### 6.3 The method — the effect map, one layer lower

```
snapshot LTC register file
   -> create MIG instance (profile P, placement S)
      -> snapshot LTC register file
         -> diff
```

This is exactly the Ouroboros differential method you already validated in
Experiment A. Same shape, different state vector. The A2 noise-floor gate
applies unchanged.

The output answers the real question: **which physical L2 slices and memory
channels did the GSP assign to this (profile, placement) pair.** You get the
firmware's decision without decrypting one byte of it.

### 6.4 The open risk

Register-op validation is **not** in the open source. The Kernel RM forwards the
ops to the GSP, and the GSP checks them against an allowlist that ships inside
the encrypted region. So whether an unprivileged client may read LTC offsets is
an **empirical** question, not a source question.

Three outcomes, all informative:

| Result | Meaning | Next move |
|---|---|---|
| returns data | Path A is fully open | run the diff on the A100 |
| `INSUFFICIENT_PERMISSIONS` | needs admin | you have root on the rented A100 anyway |
| offset rejected | LTC is off the allowlist | fall back to the contention probe alone |

### 6.5 Why this is the better result for the paper

"We measured what the firmware decided across the (profile, placement) space" is
stronger than "we read the firmware's code". It is empirical, it is
reproducible, and it does not depend on one blob version or on a decryption that
may not survive the next driver release.

---

## 7. Job 0 — run this tonight, before anything else

Cheap, decisive, and it fits the tooling you already have.

1. Re-run the ABI probe against 610.43.02. The old table is stale (see the
   version alert in `ouroboros-arch-v2-contention.md`).
2. Extend `tools/effectmap/sweep_controls.c`. It already builds the client,
   device and subdevice ladder with no root. Add one `EXEC_REG_OPS` call.
3. Issue `regOp = READ_32`, `regType = TYPE_GLOBAL`,
   `regOffset = 0x001404f8`.
4. Record `regStatus` and the returned value.

Runtime is minutes. The answer decides whether the register plane joins the
architecture or drops out of it.

**Safety.** Reads only. Never issue a register **write** on hulk — it is shared,
and an LTC write can affect every user on the box.
