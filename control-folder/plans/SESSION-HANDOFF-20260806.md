# Session handoff — 2026-08-06, plan v3 Lane A

Feed this file to a new session to resume. It is self-contained.

**Repo:** `/home/pm3371/gitrepos/ouroboros`
**Branch:** `effect-map-experiment-v1`
**Last pushed commit:** `63632dd` — "[plan: v3 Lane A] harden the request-template
parser; add effectmap tests + CI"
**Plan being implemented:** `control-folder/plans/ouroboros-plan-v3.md`
**Skill in use:** `/implement-from-plan`. User pre-approved all chunks and went
to sleep. Instruction: **use GPU 0 exclusively** (a concurrent session measures
bandwidth on GPU 1; GPU 2 is untouched).

---

## 0. STATUS AT HANDOFF (updated 2026-08-08 — Lane A is COMPLETE)

All of `ouroboros-plan-v3.md` Lane A is done, tested, and pushed. Six commits,
`63632dd`..`0efe3de` on `effect-map-experiment-v1`.

| Job | State |
|---|---|
| A0 provenance | **done** — every sweep output opens with a `_meta` record |
| A1 re-probe on 610 | **done** — full ABI diff in §4.2 |
| A2 geometry | **done** — LTC_COUNT 12, LTS_COUNT 48, LTC_MASK 0xFFF, published to ARCH.md |
| MIG classification regen | **done** — now self-labels its driver version from provenance |
| A3 EXEC_REG_OPS | **done, CLOSED** — root cause fully traced (§4.6): the CPU-side gate is open source, but its allowlist *data* comes from an internal-only control call to the Physical RM. Path A does not open unprivileged on 610.43.02. |
| rpc_tracer re-pin | **done** — 610.43.02, patches re-verified with `patch --dry-run --verbose`, `setup_experiment_b.sh`/`correlate_rpc_trace.py` committed (were tested but never git-added) |
| Lane B (bandwidth colouring) | **not started — this is what's next** |

Commits: `63632dd` (parser hardening + tests + CI), `6eb9e19` (A1 re-probe + A2
geometry), `4cd91b1` (MIG regen), `66d526a` + `a02b729` (A3, implementation
then root-cause close), `0efe3de` (rpc_tracer re-pin + B3 script).

**Lane B — DO NOT START IT. It is already being driven live by a separate
session.** Checked 2026-08-08 23:50: a distinct Claude Code process (PID
37403) is running inside a **locked git worktree**
(`gpu-virt/motivation/.claude/worktrees/m13-bw-colouring/`, branch
`worktree-m13-bw-colouring`) with an active `colour_probe` process on **GPU
1** (confirmed via `nvidia-smi --query-compute-apps`). This is not something
I started — it is a second, independent, long-running session (118+ CPU
minutes) that set up its own worktree specifically to isolate this work.

**Both sides independently built the same ownership split** — I never
coordinated this with them, it fell out of the user's separate instructions to
each session: I own `ouroboros/` + GPU 0; they own
`gpu-virt/motivation/experiments/m13-bw-colouring/` + GPU 1.
`ouroboros-arch-v2-contention.md` even carries their own note: *"File
ownership. `ouroboros/control-folder/` belongs to the other session... do not
write into that directory from this plan."* Respect the same boundary in
reverse: **do not write into `gpu-virt/motivation`, worktree or main tree,
from an Ouroboros session.** Reading is fine and useful (see below); writing
risks corrupting a live run or conflicting with a live commit.

**What they've already found (read from their `RESULTS.md`, worktree commit
`efe4b87`, read-only):**
- E1 gate: signal PASS, SNR 28.2x (need ≥3). But **page-independence FAILS** —
  same 2 MiB page correlates at r=+0.954 across independent runs; different
  pages correlate at r≈0.1–0.35. The channel hash reads physical bits
  [10:34]; a 2 MiB page only pins [20:0], so 14 of 25 relevant bits change per
  allocation.
- **Their `PLAN.md` E2 (offset-only colouring) is dead by measurement, not
  argument.** What survives: *self-calibrating, per-allocation* colouring —
  measure the mapping you were actually given, no root, no physical
  addresses, no kernel module (unlike SGDRC's actual approach).
- Their periodicity gate (Gate 2) separately **failed** — best autocorrelation
  0.21–0.35, disagreeing periods per page. This **confirms** Lane A's own A2
  finding: LTC_COUNT=12, LTS_COUNT=48, neither a power of two, so SGDRC §3.2
  predicts a genuinely non-linear hash with no clean period at all — two
  independent instruments (driver topology query, empirical stride sweep)
  converged on the same structural fact. Written up in `ARCH.md`'s "Superseded
  2026-08-08" note (commit after `0efe3de`) — my own earlier instruction there
  ("sweep for periodicity at 12 and 48") was wrong in exactly this informative
  way, and I corrected it.
- Chunk 4 (their latest commit, `efe4b87`, minutes before this check): a
  co-tenant guard for `colour_probe` — polls `nvidia-smi --query-compute-apps`
  before/during/after each run, rejects if any other PID is on the assigned
  GPU. Honestly documents its own gap: a run under ~0.64s can complete inside
  one 2s poll tick and a same-length intruder was confirmed (empirically, not
  assumed) to slip past undetected.
- At the moment I checked, they were running a footprint-cost sweep (`for FP
  in 8388608 33554432 134217728`) — almost certainly characterizing the
  `O(slots)` per-page calibration cost their RESULTS.md flags as the one open
  question on the self-calibrating approach.

**If you want Lane B to move faster:** either wait for that session to finish
(check `git -C gpu-virt/motivation/.claude/worktrees/m13-bw-colouring log` and
whether the worktree lock is still held), or explicitly tell a *fresh* session
to take over that specific worktree — do not have an Ouroboros-repo session
(this one) touch it.

---

## 1. Where to pick up — do this first

**Read §0 above, not §2 and §3 below.** Sections 2 and 3 were written mid-run,
when chunk 2 was still uncommitted. Everything they describe is now committed
and pushed. They are kept only as a record of what landed in which commit.

Resume at **A3's next step, §4.6** — read `embedded_param_copy.c` and check
`NVOS54_PARAMETERS.flags`. Then the rpc_tracer re-pin, then Lane B.

<details>
<summary>Superseded: the decode command that was pending when Bash was blocked
(it has since been run; the result is in §4.7 and in ARCH.md)</summary>

```bash
cd /home/pm3371/gitrepos/ouroboros/cuda-ioctl-map
python3 - <<'PY'
import json, re, struct, pathlib
hdr = pathlib.Path("../refs/open-gpu-kernel-modules/src/common/sdk/nvidia/inc/ctrl/ctrl2080/ctrl2080fb.h").read_text()
NAMES={}
for m in re.finditer(r"^#define NV2080_CTRL_FB_INFO_INDEX_([A-Z0-9_]+)\s+\(0x000000([0-9A-Fa-f]{2})U\)", hdr, re.M):
    NAMES.setdefault(int(m.group(2),16), m.group(1))
for ln in open("tools/effectmap/out/state_vector_610_run1.jsonl"):
    r=json.loads(ln)
    if r.get("cmd","").lower()=="0x20801303": break
b=bytes.fromhex(r["resp"]); n=struct.unpack_from("<I",b,0)[0]
rows=[struct.unpack_from("<II",b,4+8*i) for i in range(min(n,(len(b)-4)//8))]
print(f"{n} indices requested, {sum(1 for _,d in rows if d)} populated")
for idx,dat in rows:
    if dat: print(f" 0x{idx:02x}  {NAMES.get(idx,'(undefined)'):34} {dat:>14}")
PY
```
</details>

## 4.7 A2 result — the TU102 L2 geometry (published to ARCH.md)

```
PARTITION_COUNT  6      FBP_COUNT   6      PARTITION_MASK/FBP_MASK  0x3F
LTC_COUNT       12      LTS_COUNT  48      LTC_MASK                 0xFFF
PSEUDO_CHANNEL_MODE 0   L2CACHE_ONLY_MODE 0
BUS_WIDTH      384      L2CACHE_SIZE 6 MiB (128 KiB per slice)
RAM_TYPE        17 (GDDR6)   RAM_SIZE 24 GiB
```

Resolves the "6 or 12 channels" question: 6 FBP → 12 LTC (2 per FBP) → 48 LTS
(4 per LTC); 384-bit / 12 LTC = 32 bits each, so **12 × 32-bit channels**.
`m13-bw-colouring/PLAN.md`'s assumption is confirmed by measurement.

**Neither 12 nor 48 is a power of two** — both carry a factor of 3. So the
address-to-channel map cannot be a bit-slice; it needs a modulo or a hash. Lane
B's E1 must sweep for periodicity **at 12 and 48**, not at powers of two.

**Old text follows, superseded:**

```bash
cd /home/pm3371/gitrepos/ouroboros/cuda-ioctl-map
python3 - <<'PY'
import json, re, struct, pathlib
hdr = pathlib.Path("../refs/open-gpu-kernel-modules/src/common/sdk/nvidia/inc/ctrl/ctrl2080/ctrl2080fb.h").read_text()
NAMES={}
for m in re.finditer(r"^#define NV2080_CTRL_FB_INFO_INDEX_([A-Z0-9_]+)\s+\(0x000000([0-9A-Fa-f]{2})U\)", hdr, re.M):
    NAMES.setdefault(int(m.group(2),16), m.group(1))
for ln in open("tools/effectmap/out/state_vector_610_run1.jsonl"):
    r=json.loads(ln)
    if r.get("cmd","").lower()=="0x20801303": break
b=bytes.fromhex(r["resp"]); n=struct.unpack_from("<I",b,0)[0]
rows=[struct.unpack_from("<II",b,4+8*i) for i in range(min(n,(len(b)-4)//8))]
print(f"{n} indices requested, {sum(1 for _,d in rows if d)} populated")
for idx,dat in rows:
    if dat: print(f" 0x{idx:02x}  {NAMES.get(idx,'(undefined)'):34} {dat:>14}")
PY
```

The sweep that produced `state_vector_610_run1.jsonl` already ran with
`MAX_INDEX = 68`, so the file on disk should hold the full geometry. Only the
decode is missing.

**Then:** publish that table into `control-folder/ARCH.md`, replacing the
partial one under "Framebuffer topology (measured, TU102…)" which is 555-era and
stops at index 32.

---

## 2. What is committed and pushed

`63632dd` — Chunk 1, all tests green, pushed to
`origin/effect-map-experiment-v1`.

- `tools/effectmap/sweep_controls.c` — fixed the parser (details in §4)
- `optimizer/tests/test_effectmap.py` — **new**, 13 unit tests
- `tools/effectmap/test_load_cmds.sh` — **new**, 5 C rejection cases
- `.github/workflows/optimizer-plan-v2-phase0.yml` — added
  `effect-map-experiment-v1` to the trigger branches
- `control-folder/{CLAUDE,ARCH,TODO,code}.md`, `plans/ouroboros-plan-v3.md`,
  `plans/gsp-firmware-re-assessment.md`
- `.gitignore` — `__pycache__/`

**CI status is UNVERIFIED.** `gh run list` was blocked by the classifier after
the push. Check it: `gh run list --limit 3`.

---

## 3. What is NOT committed (working tree, all tested and working)

This is Chunk 2. It needs a commit.

| File | Change |
|---|---|
| `tools/effectmap/sweep_controls.c` | provenance `_meta` record (`emit_meta`, `sanitise_json`, `<time.h>`, `run_size_scan` signature gained `gpu`/`cmds_path`) |
| `tools/effectmap/gen_scan_list.py` | **new** — emits `all_scan.txt`; replaces the "one-liner in LOG.md" that was never written down |
| `tools/effectmap/gen_templates.py` | `MAX_INDEX` 32 → **68**, with the measured cliff documented |
| `tools/effectmap/noise_floor.py` | gate now `sys.exit(2)` on FAIL (code.md E5) |
| `tools/effectmap/{noise_floor,gen_sweep_list,classify_mig,run_effect_map}.py` | skip records without a `cmd` key, so the `_meta` line does not break them |

Regenerated artifacts under `tools/effectmap/out/`:

- `abi_probe_all.jsonl` — **re-measured on 610.43.02**
- `abi_probe_all.555.jsonl` — the old 555 probe, kept as a baseline for diffing
- `all_scan.txt`, `sweep_cmds_610.txt`, `sweep_cmds_610_tmpl.txt`
- `state_vector_610_run1.jsonl`, `state_vector_610_run2.jsonl`
- `noise_floor_610.json`

Suggested commit message:

```
[plan: v3 Lane A] re-probe the ABI on 610.43.02; stamp provenance; MAX_INDEX 68

- sweep_controls.c: every output now opens with a _meta record naming the
  driver, GPU and time, so a stale artifact is self-identifying
- gen_scan_list.py: the missing first pipeline stage, now a script
- gen_templates.py: MAX_INDEX 32 -> 68, the measured ceiling on 610
- noise_floor.py: the gate now fails the process (code.md E5)
- consumers skip the _meta record
- out/: full re-measurement against 610.43.02
```

---

## 4. Measured results — the substance of this session

### 4.1 hulk moved 555.42.02 → 610.43.02

`/proc/driver/nvidia/version` and `nvidia-smi` both report **610.43.02**, built
2026-05-19. The vendored SDK is also 610.43.02, so headers and binary now agree.
Every artifact under `out/` predating today was measured on 555 and was stale.

Corroborating signal: `GET_PROBED_IDS` now accepts **384** bytes (3 arrays,
the 610 header shape). On 555 it accepted 256 (2 arrays). The sweeper's
"ask the driver which size it wants" loop handled this without a code change.

The ladder also reports **4 GPUs probed**, while `nvidia-smi` lists 3. Not
investigated. Low priority, but do not assume 3.

### 4.2 ABI re-probe, 610 vs 555

| Metric | 555 | 610 |
|---|---|---|
| commands probed | 1675 | 1675 |
| present | 1167 | **1353** |
| absent | 508 | **322** |
| appeared in 610 | — | **201** |
| removed in 610 | — | **15** |
| comparable sizes | — | 1152 |
| sizes changed | — | **124 (10.8%)** |

Key commands:

| cmd | name | 555 | 610 |
|---|---|---|---|
| `0x20801303` | `FB_GET_INFO_V2` | 444 | **1028** |
| `0x20800102` | `GPU_GET_INFO_V2` | 524 | **580** |
| `0x20801823` | `BUS_GET_INFO_V2` | 420 | 420 |
| `0x20800122` | `GPU_EXEC_REG_OPS` | 48 | 48 |
| `0x20800174` | `GPU_SET_PARTITIONS` | 392 | 392 |
| `0x20800AA5` | `INTERNAL_MIGMGR_SET_GPU_INSTANCES` | 392 | 392 |

`0x20800A22` regressed to "no accepted size at or below 65536" (was 23072).

**`FB_GET_INFO_V2` 444 → 1028 is the load-bearing one.** 1028 = `4 + 128*8`,
exactly the header's `NV2080_CTRL_FB_INFO_MAX_LIST_SIZE = 0x80`. Capacity rose
from 55 entries to 128.

### 4.3 The index cliff — a new silent-failure trap

**Measured on 610, GPU 0.** `gen_templates.py` used to claim that indices above
the driver's range "are simply reported as unsupported in their own slot; they
do not fail the call". **That is false.**

| indices requested | populated data fields | status |
|---|---|---|
| 32 | 25 | `0x0` |
| 55 | 33 | `0x0` |
| 64 | 35 | `0x0` |
| 67 | 35 | `0x0` |
| **68** | **35** | `0x0` |
| **69** | **0** | `0x0` |
| 70, 71, 72, 96, 128 | 0 | `0x0` |

The driver validates every index in the list. If any one is out of range it
returns **status 0 with the entire response zeroed** — no data, no error. The
cliff is exact at 68 (`0x44`), one past `LTC_MASK_7` (`0x43`), the highest index
the 610 header defines.

**Consequence:** raising `MAX_INDEX` "to be safe" silently destroys the
measurement. This is now documented at the constant.

### 4.4 Noise-floor gate on 610: PASS

153 of 155 byte-stable (**98.7%**), matching the 555 result of 98.6%. Two noisy
commands, same timer character as before. Report:
`out/noise_floor_610.json`.

Sweep coverage: **158 of 327** admitted commands returned status 0.
`gen_sweep_list.py` admitted 327 of 2382 on 610 (was 275 on 555).

### 4.5 The plan's number was right; the old code could not survive it

`ouroboros-plan-v3.md` §4 A2 said `MAX_INDEX = 68`. The code review (code.md,
finding E1) showed 68 would smash the stack: 68 indices is 1096 hex characters
against a 1026-byte buffer parsed with `%2048s`. Chunk 1 fixed that first. The
610 re-probe then made 68 both reachable and correct. Both steps were needed.

---

## 5. Code review findings, and their status

Full text in `control-folder/code.md`, section "Code Review — commit `aaf7d18`".

| ID | Finding | Status |
|---|---|---|
| E1 | `load_cmds` stack overflow: `%2048s` into `hex[1026]` | **fixed** in `63632dd` |
| E2 | oversized template silently dropped → zeroed buffer sweep | **fixed** in `63632dd` |
| E3 | plan's `MAX_INDEX` unsafe against old code | **resolved** — 68 measured, parser hardened |
| E5 | `noise_floor.py` prints `GATE: FAIL` but exits 0 | **fixed**, uncommitted |
| E6 | `--probe-mode` ignored on the size-scan path | open, cosmetic |
| E7 | size scan is linear per command | open, acceptable |
| E8 | `_EXEC` denied by the sweep filter | **correct as-is**; pinned by a unit test. A3 must add its own path. |

Phase 3 item 2 (no provenance stamp) is **fixed**, uncommitted.

---

## 6. Remaining work, in order

Task list IDs are from this session's `TaskList`.

1. **Finish A2 (task #3).** Decode the geometry (§1), publish to `ARCH.md`,
   commit Chunk 2.
2. **Regenerate the MIG classification on 610.** The current
   `plans/mig-command-classification.md` header says "driver 555.42.02" and every
   `driver size` column is stale. Command is in `control-folder/CLAUDE.md`
   step 5; point `--probe` at the new `abi_probe_all.jsonl`.
3. **A3 — `EXEC_REG_OPS` probe (task #4).** Not started. Add a read-only
   `--exec-reg-ops` path to `sweep_controls.c`. One `READ_32` at `0x001404f8`
   (`NV_PLTCG_LTC0_LTS0_L2_CACHE_ECC_UNCORRECTED_ERR_COUNT`, the single LTC
   register the 610 hwref publishes, in
   `src/common/inc/swref/published/turing/tu102/dev_ltc.h`). Struct is
   `NV2080_CTRL_GPU_REG_OP`, driver size 48, `regType = TYPE_GLOBAL (0x00)`.
   **Reads only. Never write an LTC register — hulk is shared.**
   Three outcomes, all informative: data returned (register plane is open),
   `INSUFFICIENT_PERMISSIONS` (retry with root on the A100), offset rejected
   (LTC is off the GSP allowlist).
4. **Carried corrections (task #5).** Re-pin `rpc_tracer/` patches from
   open-module tag 555.42.02 to 610.43.02.
5. **Lane B — bandwidth colouring.** User approved "Lane A, then Lane B in the
   same run". Lives in a **different repo**: `gpu-virt/motivation`, with its own
   `CLAUDE.md`, conventions and git remote. Plan:
   `gpu-virt/motivation/experiments/m13-bw-colouring/PLAN.md` (E1/E2/E3), plus
   `ARCH-v2.md` there. **Lane B must use GPU 0 only** — a concurrent session
   owns GPU 1.

---

## 7. Environment facts, verified today

- Driver **610.43.02**; vendored SDK matches.
- `nvcc` is `/usr/bin/nvcc`, **CUDA 12.0**. `/usr/local/cuda-12.5` is **gone** —
  do not reference it. `sweep_controls.c` is pure C and needs only gcc 13.3.
- 3× TITAN RTX visible to `nvidia-smi`, idle. **Use GPU 0.**
- No root. `/dev/nvidia*` is world-accessible, so the sweeper needs no
  privilege.
- Tests: `python3 -m unittest discover -s optimizer/tests -p 'test_*.py'` —
  **19 pass**. Plus `bash tools/effectmap/test_load_cmds.sh` — **5 pass**,
  touches no GPU.
- CI workflow: `.github/workflows/optimizer-plan-v2-phase0.yml`, runs
  `SKIP_LIVE=1 ./optimizer/scripts/smoke_plan_v2.sh` on ubuntu-latest, no GPU.
- Git remote has **moved** to `git@github.com:pulak999/ouroboros.git`. Pushes
  still work via redirect; `git remote set-url` was blocked by the classifier
  and is still pending.

---

## 8. Concurrency warning

A **second session** is working in the same tree. It owns:

- `control-folder/plans/ouroboros-arch-v2-contention.md` (it rewrote this into
  "the bandwidth-colouring loop" mid-session)
- `cuda-ioctl-map/tools/effectmap/rpc_tracer/` (untracked
  `correlate_rpc_trace.py`, `setup_experiment_b.sh`, modified `README.md`)
- GPU 1

Those were deliberately left out of `63632dd`. Do not commit them without
checking whether that session has finished. Re-read any file before editing it —
several changed on disk mid-edit during this session.

---

## 4.6 A3 — EXEC_REG_OPS: present, but rejecting

**Implemented.** `sweep_controls.c` gained a `--exec-reg-ops <offset>` flag
(repeatable, up to 64 offsets). It is **read-only by construction**: `regOp` is
hard-coded to `READ_32` and no flag changes it. Two `_Static_assert`s pin
`NV2080_CTRL_GPU_REG_OP` at 32 bytes and the params struct at 48, the measured
driver size.

Run on GPU 0, driver 610.43.02:

```
reg 0x00000000: status=0x0000001F regStatus=0x00 value=0x00000000   <- PMC_BOOT_0
reg 0x001404F8: status=0x0000001F regStatus=0x00 value=0x00000000   <- LTC anchor
reg 0x00140000: status=0x0000001F regStatus=0x00 value=0x00000000
reg 0x00142000: status=0x0000001F regStatus=0x00 value=0x00000000
```

`0x1F` is `NV_ERR_INVALID_ARGUMENT`, **uniform across every offset including
PMC_BOOT_0**, a register that certainly exists. So the call is failing *before*
offset validation. This is **not** `NV_ERR_INSUFFICIENT_PERMISSIONS` (0x1B), so
it is not a clean permission denial either.

**The NOPTRS bypass is closed.** `NV2080_CTRL_CMD_GPU_EXEC_REG_OPS_NOPTRS`
(`0x2080019D`), which embeds the ops array inline and avoids the embedded-pointer
copy entirely, probes as **absent** on 610 (`0x56 NOT_SUPPORTED`).

**RESOLVED 2026-08-08.** Both hypotheses from the previous session are closed:

1. **Params-bug hypothesis: closed, ruled out.** Compiled a probe directly
   against the vendored header and confirmed the hand-rolled struct in
   `sweep_controls.c` is byte-exact: `sizeof(PARAMS) == 48`, `regOpCount` at
   offset 20, `regOps` at offset 24, `grRouteInfo` (16 B) at offset 32,
   `sizeof(REG_OP) == 32`. The request is correctly formed.
2. **NVOC dispatch-level rejection: closed, ruled out.** The command's export
   entry (`g_subdevice_nvoc.c:4081-4095`) carries
   `flags = 0x10118 = NON_PRIVILEGED | GPU_LOCK_DEVICE_ONLY | API_LOCK_READONLY
   | GSP_PLUGIN_FOR_VGPU_GSP`. `NON_PRIVILEGED` is explicitly set — non-admin
   callers are permitted to reach the handler.

**The actual gate:** `gpuValidateRegOffset_IMPL` (`gpu_access.c:1212`) checks
`gpuGetUserRegisterAccessPermissions(pGpu, offset)`
(`gpu_register_access_map.c:137`) — a real bitmap test, fully in the open
driver. But the bitmap's *contents* are populated once, at GPU init, from an
**internal-only** control call
(`NV2080_CTRL_CMD_INTERNAL_GPU_GET_USER_REGISTER_ACCESS_MAP`, routed to the
Physical RM) — the same shape as the MIG Tier-3 commands already catalogued.
So the mechanism is open-source; the data that decides allow/deny is not.

A test with a wildly out-of-range offset (`0xFFFFFFF0`) produced the identical
`0x1F` as `PMC_BOOT_0`, confirming this is a uniform permission wall, not
per-offset validation.

**Conclusion: Path A does not open from an unprivileged client on 610.43.02.**
Not yet tested with root — worth trying on the rented A100, but
`gpuValidateRegOffset_IMPL`'s permission branch is skipped only by
`osIsAdministrator()`, so it may not help if the underlying map is genuinely
restrictive rather than merely permission-gated.

Full writeup with exact citations: `gsp-firmware-re-assessment.md` §6.4.
Artifact: `tools/effectmap/out/reg_probe_610.jsonl`.

**A3 is now closed** — no further action unless the A100 root test is wanted.
