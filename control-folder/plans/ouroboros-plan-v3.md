# Ouroboros Plan v3 — measure before you infer

**Date:** 2026-08-06
**Status:** execution plan. Serves `ouroboros-arch-v2-contention.md`; does not
replace it. v2 says *what the architecture is*. v3 says *what I do next, in what
order, and what gate stops each step.*
**Companion:** `gsp-firmware-re-assessment.md` (the firmware question, closed).

---

## 0. The one-line summary

v2 plans to **infer** the DRAM channel map from timing. The driver will **tell
you** most of it for free. v3 puts the queryable oracle first, uses it to seed
and to cross-check the timing experiment, and only then runs the search loop.

Reason: v2 already names its own worst failure mode — "*the single most likely
way to get a convincing false positive on the gate*". An independent,
non-timing measurement of the channel count removes that risk instead of
managing it.

---

## 1. New measured facts since v2 was written

All four measured today. All four change the plan.

### 1.1 hulk runs 610.43.02, not 555.42.02

`/proc/driver/nvidia/version` reports **610.43.02**, built 2026-05-19. Already
recorded in v2 §0.0. The consequence for v3: the ABI substrate must be
re-measured before it is cited again.

### 1.2 The GSP firmware question is closed

Measured on `gsp_ga10x.bin` (84 MB, world-readable):

| Region | Entropy | chi² (df=255) | gzip | Verdict |
|---|---|---|---|---|
| front, 4 MB mark | 7.1229 | 9 269 918 | **53.3%** | compressed, analysable |
| back, 40 MB mark | 8.0000 | 274.6 | 100.03% | random-indistinguishable |
| back, 60 MB mark | 7.9999 | 306.5 | 100.01% | random-indistinguishable |
| `/dev/urandom` reference | 8.0000 | 244.7 | 100.03% | — |

The back 64 MB matches `/dev/urandom` on all three statistics. The front of the
**same file** compresses to 53%, so the vendor's own compressor does not produce
8.000 output. The GSP-RM, and AMAPLIB with it, is in the encrypted region.

**Decision: no firmware reverse engineering.** Full reasoning in
`gsp-firmware-re-assessment.md`. This lane is closed, not deferred.

### 1.3 The framebuffer topology is already queryable, and already captured

`NV2080_CTRL_CMD_FB_GET_INFO_V2` (`0x20801303`) is in the existing sweep set and
returns `status 0x0`. Decoding `out/state_vector_run1.jsonl` gives the real
TU102 topology, with no new code and no timing:

| Index | Field | Measured | Cross-check |
|---|---|---|---|
| 0x04 | `PARTITION_COUNT` | **6** | — |
| 0x19 | `FBP_COUNT` | **6** | — |
| 0x14 | `PARTITION_MASK` | **0x3F** | 6 partitions, all enabled |
| 0x1a | `FBP_MASK` | **0x3F** | agrees |
| 0x0b | `BUS_WIDTH` | **384** | TITAN RTX spec ✓ |
| 0x07 | `RAM_SIZE` | 25 165 824 KiB | 24 GiB ✓ |
| 0x1b | `L2CACHE_SIZE` | 6 291 456 | 6 MiB ✓ |
| 0x0d | `RAM_TYPE` | 17 | GDDR6 |
| 0x06 | `BANK_SWIZZLE_ALIGNMENT` | 65 536 | 64 KiB |

Three fields match published TITAN RTX specifications exactly. The decode is
correct.

### 1.4 The four indices that matter most were never requested

`gen_templates.py` sets `MAX_INDEX = 32`. The memory-geometry indices sit
above it:

| Index | Field | Why it decides the experiment |
|---|---|---|
| 0x22 (34) | `LTC_COUNT` | number of L2 controllers |
| 0x23 (35) | `LTS_COUNT` | L2 slices per controller |
| 0x25 (37) | `PSEUDO_CHANNEL_MODE` | GDDR6 pseudo-channel on/off — decides 12 vs 24 channels |
| 0x2b (43) | `LTC_MASK` | which controllers are enabled |

Raising `MAX_INDEX` to 68 is a one-line change. It costs one re-run.

---

## 2. The finding that breaks a v2 assumption

Both `m13-bw-colouring/PLAN.md` and v2 §4 state: *"Expect 12 32-bit channels."*

**The driver reports `PARTITION_COUNT = 6` and `FBP_COUNT = 6`.**

The two are reconcilable — a 384-bit bus over 6 FBPAs is 64 bits each, which is
two 32-bit GDDR6 devices per FBPA, so 12 devices. But **the driver's partition
granularity is 6, and 6 is not a power of two.**

That matters concretely:

- An address-to-partition map over 6 partitions **cannot be a pure bit-slice**.
  It needs a modulo or a hash.
- The colouring rule `(offset / B) % N` therefore needs **N = 6, 12, or 24** —
  not a guessed power of two.
- Colour-set granularity is coarser than a bit-mask scheme would give. A
  two-tenant split over 6 partitions is 3/3, not an arbitrary bit pattern.

**v2's colouring scheme survives this. Its assumed constant does not.** Run
§1.4's query before writing any sweep range, or E1 sweeps for a periodicity of
12 that may be a periodicity of 6.

---

## 3. The principle v3 adds

> **Prefer a queryable oracle over an inferred one. Where both exist, use the
> queryable one to seed and to check the inferred one.**

v2's Plane 1 was "the ABI substrate, retained and unused." v3 promotes it. It is
not the experiment, but it is the experiment's **control**.

This costs almost nothing — the tooling is built, needs no root, and runs in
seconds — and it converts E1 from "did we see a pattern" into "did we see the
pattern the driver says is there."

---

## 4. Three lanes

| Lane | What | Status |
|---|---|---|
| **A — ground truth** | query the driver for topology and registers | new in v3, cheap, blocks B |
| **B — the experiment** | E1 gate, then E2 trade curve, then the loop | v2's plan, unchanged in shape |
| **C — firmware** | reverse engineer GSP | **closed**, see §1.2 |

### Lane A — what I will actually run

**A1. Re-measure the ABI against 610.43.02.** The probe takes about two seconds.
Re-run steps 1–3 of the `CLAUDE.md` effect-map pipeline. Emit a fresh
`abi_probe_all.jsonl`. Re-generate `mig-command-classification.md`. Fix the
stale "hulk runs 555" claim in `CLAUDE.md` decision 2.

**A2. Raise `MAX_INDEX` to 68 and re-sweep.** Gives `LTC_COUNT`, `LTS_COUNT`,
`PSEUDO_CHANNEL_MODE`, `LTC_MASK`, plus `LTC_MASK_1..7` and `PARTITION_MASK_1..3`.
Output: a complete, driver-sourced memory-geometry table for TU102.

**A3. Probe `EXEC_REG_OPS` reachability.** `NV2080_CTRL_CMD_GPU_EXEC_REG_OPS` =
`0x20800122`, present, driver-enforced size 48. Extend `sweep_controls.c` — it
already builds the client/device/subdevice ladder with no root. Issue one
`READ_32` at `0x001404f8`, the single published LTC register
(`NV_PLTCG_LTC0_LTS0_L2_CACHE_ECC_UNCORRECTED_ERR_COUNT`).

Three outcomes, all useful:

| Result | Meaning | Effect on the plan |
|---|---|---|
| returns data | the LTC register file is readable unprivileged | a second, register-level oracle joins Lane B |
| `INSUFFICIENT_PERMISSIONS` | needs admin | retry on the A100, where you have root |
| offset rejected | LTC is off the GSP allowlist | Lane A stops at A2; E1 still has §1.3's table |

**Reads only. Never write an LTC register on hulk — it is shared.**

### Lane B — unchanged in shape, better seeded

Runs exactly as v2 §4 specifies, with two amendments:

- **E1's sweep range comes from A2, not from a guess.** Sweep for the measured
  partition count, and for its 2× and 4× multiples if pseudo-channel mode is on.
- **E1's result is scored against A2.** If the timing periodicity agrees with the
  driver's partition count, the gate passes with a corroborated number. If it
  disagrees, that is a finding in itself and it must be explained before E2 runs.

Everything else in v2 stands: the null run is mandatory, the clock gate is
mandatory, GPU 0 and 1 only, and E3 (read SGDRC) runs before E1.

---

## 5. Tonight, in order

| # | Job | Lane | Gate | Est. |
|---|---|---|---|---|
| 0 | E3 — extract SGDRC's method | B | blocks E1 | 1 h |
| 1 | A1 — re-probe the ABI on 610.43.02 | A | none | 10 min |
| 2 | A2 — `MAX_INDEX` 32 → 68, re-sweep, decode | A | **blocks E1's sweep range** | 20 min |
| 3 | A3 — `EXEC_REG_OPS` reachability probe | A | none; informs scope | 30 min |
| 4 | Build `colour_probe` | B | — | 1 h |
| 5 | **E1 gate** — stride/offset sweep, seeded by job 2 | B | **the gate** | overnight |
| 6 | E1 null run — same config twice, nothing between | B | **mandatory** | overnight |
| 7 | Build `colour_corun`, first E2 points if E1 passes | B | needs E1 | overnight |

**Jobs 1–3 run first because they are minutes, not hours, and job 2 changes what
job 5 sweeps for.** Doing them after E1 means re-running E1.

**Job 6 is not optional.** A number from this harness is not evidence until the
null case is measured.

**Clock gate, carried from v2.** An idle TITAN RTX sits at 405 MHz memory. Warm
up to 7001 MHz, read `clocks.current.memory` *during* the measured window,
record it with every result, and reject any run that did not boost.

---

## 6. Tomorrow, on the rented A100

| Step | What | Why v3 adds it |
|---|---|---|
| A | Re-run A1 + A2 on GA100 | HBM2e topology differs from GDDR6. Get the real numbers before assuming. |
| B | Re-run A3 with root | the permission branch resolves here |
| C | E1 on HBM2e | does the channel signal survive a different memory technology? |
| D | E2 best configurations | does the trade curve hold? |
| E | MIG comparison arm | MIG returns as the **comparison**, not the mechanism |

Step A is new in v3 and it is the cheap one. `driver-source-findings.md` §5.1
already flags "re-run this check on the A100" as an open item. A2 answers it in
twenty minutes for zero risk.

---

## 7. What v3 changes relative to v2

| v2 | v3 | Why |
|---|---|---|
| Plane 1 "retained and unused" | Plane 1 is the **control** for E1 | It is free and it removes the false-positive risk v2 names. |
| "Expect 12 32-bit channels" | `PARTITION_COUNT = 6`, measured; geometry pending A2 | 6 is not a power of two. It changes the colouring arithmetic. |
| E1 sweeps a guessed range | E1 sweeps the measured range | Fewer wasted overnight hours. |
| Firmware not addressed | Firmware lane **closed** with evidence | Stops it being reopened later. |
| ABI table cited as-is | ABI table re-measured on 610 first | The old table is from a driver that is no longer loaded. |

**Unchanged:** the colouring mechanism, the trade-curve framing, MAP-Elites over
`(solo BW, contended BW)`, the anti-hacking argument, no LD_PRELOAD, no root, no
driver writes.

---

## 8. What would falsify v3 specifically

v2 §7 still holds for the experiment. v3 adds three of its own.

| Failure | Likelihood | Response |
|---|---|---|
| A2's extra indices return unsupported | medium | Geometry stays partly unknown. E1 sweeps 6, 12 and 24 and reports which fits. |
| A3 is denied on hulk **and** on the A100 | low-medium | Lane A stops at A2. E1 still has §1.3's table. No loss to Lane B. |
| E1's measured periodicity disagrees with A2's partition count | medium | **The most interesting outcome.** The hash uses bits above the 2 MiB page boundary. Colouring from user space is then impossible, which is a clean negative and closes the row. |

---

## 9. What I do next

1. Job 1 — re-probe the ABI on 610.43.02.
2. Job 2 — raise `MAX_INDEX`, re-sweep, publish the full TU102 memory-geometry
   table.
3. Job 3 — probe `EXEC_REG_OPS` at `0x001404f8`, read only.
4. Report all three, then start Lane B with the measured numbers in hand.

Jobs 1–3 together are under an hour and none of them touches the GPU in a way
another user can observe.
