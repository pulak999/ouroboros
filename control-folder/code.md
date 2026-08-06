# Code Review — commit f0cb9cc3a475e65fd807aee56439bff7d29d5ba5 (2026-05-09)

## Phase 1: Repo Overview

**Purpose:** Capture NVIDIA CUDA driver ioctls as JSONL, infer handle byte offsets from paired runs, replay ioctls without libcuda to validate the protocol.

**Layout (relevant to plan-v1):**

- `cuda-ioctl-map/` — primary pipeline: `run.sh`, `intercept/nv_sniff.c`, `replay/replay.py`, `tools/find_handle_offsets.py`, `programs/`, `sniffed/`.
- `README.md` — user-facing quick start.
- `roadmap.md`, `plan-v1.md` — design and implementation plan.
- `cuda_ioctl_sniffer/`, `open-gpu-kernel-modules/` — submodules / reference, not part of the optimizer harness.

**Entry points:** `bash cuda-ioctl-map/run.sh …`; `python3 cuda-ioctl-map/replay/replay.py …`; `python3 cuda-ioctl-map/tools/find_handle_offsets.py …`.

**Data flow:** CUDA binary → LD_PRELOAD sniffer → JSONL → (optional inference) → `handle_offsets.json` → replay patches → kernel.

**Patterns:** Linear shell-orchestrated pipeline; Python replay is imperative event loop over JSONL.

## Phase 2: Drill-Down (optimizer-relevant)

| File | Role | Notes for harness |
|------|------|-------------------|
| `cuda-ioctl-map/run.sh` | compile/capture/replay | `-c` capture-only; capture always writes `sniffed/<NAME>.jsonl` (same path overwrites). Harness must copy traces between captures. |
| `intercept/nv_sniff.c` | record open/ioctl | `/dev/nvidia*` only; max 4096-byte snapshot. |
| `replay/replay.py` | replay + patch | `replay()` returns `failed` count only; exit 0 if `failed==0` even when `skipped>0`. Evaluator must parse `DONE` line. |
| `replay/handle_map.py` | schemas + maps | `load_schemas(path)`; 4-byte LE handles. |
| `tools/find_handle_offsets.py` | diff two JSONL → offsets | Writes merged JSON; pairs by position; nvidiactl-focused. |

## Phase 3: Cross-Cutting

- **Capture success vs trace quality:** `run.sh` ignores program exit code during capture; empty or stale JSONL must be validated by size/event count.
- **Skip vs fail:** replay exit code does not encode skips; metrics must treat extra skips as regression vs baseline.
- **No CI:** `.github/workflows` absent in this repo; local tests only unless added later.

---

## Plan cross-reference (`plan-v1.md`)

| Plan item | Repo state | Notes |
|-----------|--------------|-------|
| `optimizer/harness.yaml` | Not present → implement | |
| `evaluate.py`, `metrics.py`, `gepa_runner.py` | Not present → implement | |
| Wrap `run.sh`, `find_handle_offsets.py`, `replay.py` | Exists | Subprocess from `cuda-ioctl-map/` cwd |
| Candidate offsets under `optimizer/runs/` | Not present → implement | Do not overwrite `intercept/handle_offsets.json` |
| GEPA `optimize_anything` | External `gepa` package | `optimizer/requirements.txt`; runner fails fast with install hint |
| Branch `coding-agent-dev` | Not in remote list | Create at implementation time |

**Conflicts / preconditions:** Live NVIDIA + privileged replay required for full evaluator; unit tests cover metrics parsing only.

---

## Plan cross-reference (`plan-v2.md`) — operational E2E

| plan-v2 phase | In repo / automated | Operator-only |
|----------------|---------------------|---------------|
| 0 | `optimizer/scripts/smoke_plan_v2.sh` with `SKIP_LIVE=1` | — |
| 1 | — | Fresh clone under `$HOME/ioctl-agent-scratch`, `uv venv` |
| 2 | Script curls `/v1/models` when `VLLM_API_BASE` set | Start vLLM, pick GPU |
| 3 | Script runs `gepa_runner` when `GEPA_REFLECTION_MODEL` + `VLLM_API_BASE` set | Model id from server |
| 4 | Script runs `evaluate.py` unless `SKIP_LIVE=1` | GPU + `/dev/nvidia*` access |
| 5 | Append [VALIDATION.md](VALIDATION.md) | Host notes, vLLM version |
| 6 | — | `rm -rf` scratch clone |

**Note:** Phases 2–3 require a running OpenAI-compatible server (e.g. vLLM on a
Titan); the repo cannot start that server for you from CI without GPU runners.

---

## Code Review — commit ecfc683271c7c8e13b5ee55777cb9cdfa9cf6ab2 (2026-05-09)

### Phase 1: Repo Overview

**Purpose:** Same as prior review — CUDA ioctl JSONL capture, handle-offset inference, replay without libcuda; **plus** an optimizer layer (`evaluate.py`, `metrics.py`, `gepa_runner.py`) that scores harness YAML by running the real pipeline.

**Layout:** `cuda-ioctl-map/` owns `run.sh`, `intercept/`, `replay/`, `tools/`, `programs/`, `sniffed/`, `optimizer/` (harness YAML, evaluator, GEPA driver, tests, `scripts/smoke_plan_v2.sh`). Repo root holds plans (`plan-v1.md`, `plan-v2.md`), `AGENT_SERVER_SETUP.md`, `VALIDATION.md`, `CLAUDE.md`, `ARCH.md`, `TODO.md`.

**Entry points:** `bash run.sh …`; `python3 replay/replay.py …`; `python3 optimizer/evaluate.py`; optional `optimizer/gepa_runner.py`; automation `optimizer/scripts/smoke_plan_v2.sh` (must `cd cuda-ioctl-map` or rely on script self-`cd`).

**Data flow:** Harness lists `.cu` programs → evaluator orchestrates capture/pair/infer/replay → JSON metrics; GEPA treats harness YAML as text and calls evaluator as metric.

**Patterns:** Subprocess-heavy evaluator; GEPA loads `evaluate.py` via `importlib` to avoid circular imports.

**Structural note:** `.github/workflows` is **absent** — no CI in-tree; validation is local + `VALIDATION.md`.

### Phase 2: File-by-File (plan-v2–relevant)

| File | Responsibility | Inputs / outputs | Risks / notes |
|------|----------------|------------------|---------------|
| `optimizer/scripts/smoke_plan_v2.sh` | Single entry for plan-v2 Phase 0, 4, optional 2–3 | `OPT_PY` / `OPT_VENV_PY`, `SKIP_LIVE`, `VLLM_API_BASE`, `GEPA_*` | Phase 4 uses `OPT_PY` (default `python3`), not necessarily `.venv` — matches plan manual which uses `.venv` for evaluate; operators should set `OPT_PY=optimizer/.venv/bin/python` if system Python lacks deps. |
| `optimizer/evaluate.py` | Full harness evaluation + `--dry-run` | harness path → JSON stdout | Long timeouts; needs CUDA + device access for live path. |
| `optimizer/gepa_runner.py` | `optimize_anything` over harness text | `--reflection-model`, `--api-base`, `--api-key` set `OPENAI_API_*` | If `--reflection-model` omitted, default GEPA model may hit `AuthenticationError` without cloud keys (documented in VALIDATION). |
| `optimizer/metrics.py` | Parse replay `DONE`, diff offsets | strings / dicts | Unit-tested. |
| `optimizer/tests/test_*.py` | Metrics gates | — | Fast; no GPU. |

**Name vs behavior:** `smoke_plan_v2.sh` is accurate; `curl` uses `$BASE/models` while plan text says `/v1/models` — with `VLLM_API_BASE=http://127.0.0.1:8000/v1`, `$BASE/models` resolves to `/v1/models` (correct).

### Phase 3: Cross-Cutting

1. **Python split:** Smoke script uses `python3` for unittest/evaluate but `optimizer/.venv/bin/python` for GEPA when `.venv` exists — consistent with plan Phase 3 vs Phase 0; **inconsistent** if someone creates `.venv` only for GEPA deps but `evaluate.py` needs the same venv on a minimal host — document `OPT_PY` (already in script comments / plan table).
2. **Missing CI:** No automated regression on PRs; `SKIP_LIVE=1` is the only portable gate.
3. **Likeliest failure:** Live replay permissions or nvcc path; second: LiteLLM + local OpenAI base + exact model id string.
4. **New engineer warning:** Run everything from `cuda-ioctl-map/`; replay failures do not always non-zero exit — always parse metrics JSON and `DONE` line semantics per `metrics.py`.

**Terminal summary (critical):**

- No GitHub Actions in this repo; rely on local `SKIP_LIVE=1` smoke.
- `smoke_plan_v2.sh` implements plan-v2 Phases 0, 4, and optional 2–3; Phases 1–2, 5–6 remain operator procedures.
- Set `OPT_PY` to the optimizer venv interpreter on hosts where system `python3` lacks PyYAML / deps for `evaluate.py`.
- GEPA reflection requires either cloud credentials for the default model or explicit `--reflection-model` + `--api-base` (local vLLM).
- `code.md` updated through Phase 3 for commit `ecfc683271c7c8e13b5ee55777cb9cdfa9cf6ab2`.

### Plan cross-reference (`plan-v2.md`) at this commit

| plan-v2 item | Status in repo | Notes |
|--------------|-----------------|-------|
| Automation `smoke_plan_v2.sh` | **Done** | Env: `SKIP_LIVE`, `VLLM_API_BASE`, `GEPA_REFLECTION_MODEL`, `GEPA_MAX_METRIC_CALLS`, `GEPA_API_KEY`, `OPT_VENV_PY`, `OPT_PY`. |
| Phase 0 unittest + dry-run | Script + verified PASS (agent run 2026-05-09) | `SKIP_LIVE=1`. |
| Phase 1 throwaway clone + uv venv | Operator | Not automatable in-repo. |
| Phase 2 vLLM | Operator + optional curl in script | Server not started by repo. |
| Phase 3 GEPA ≥1 reflection | Operator when env set | Script wires flags; needs live LLM. |
| Phase 4 live `evaluate.py` both harnesses | In script when not `SKIP_LIVE=1` | Needs GPU + `/dev/nvidia*`. |
| Phase 5 VALIDATION.md | Partial | plan-v2 section documents automation + Phase 0; full E2E row awaits server run. |
| Phase 6 cleanup | Operator | — |

**Conflicts / preconditions:** Plan assumes no sudo for routine steps; replay may still require group membership on `/dev/nvidia*` (not always “rootless”). Plan `GEPA_MAX_METRIC_CALLS` example uses `12`; script default `12`; README snippet showed `8` as optional — all consistent.

**Tests / CI survey:** `python3 -m unittest discover -s optimizer/tests -p 'test_*.py' -v` (6 tests). No `.github/workflows/`.

---

## Code Review — commit 5438bb477e3e089b3247fd82fa281f5f51c6b9db (2026-05-09)

### Delta since `ecfc683` (doc + validation only)

**Changed files:** `VALIDATION.md` (Phase 4 live evidence), `LOG.md`, `TODO.md`, `code.md` (prior section), `ARCH.md` (minor), `CLAUDE.md` (env table for Gemini).

### Phase 1–3 (delta)

- **No executable code changes** in this commit range; optimizer behavior unchanged.
- **VALIDATION.md** now records a successful full `smoke_plan_v2.sh` (Phase 0+4) on shared dev host with commit SHA and replay counts — aligns with plan-v2 Phase 5 partial completion.
- **Risk:** None introduced; documentation only.

### Plan cross-reference (`plan-v2.md`) at this commit

| Item | Update |
|------|--------|
| Phase 4 live on dev clone | **Logged** in VALIDATION.md (`ecfc683` at time of run; narrative still valid). |
| Phases 1–3, full Phase 5 row, Phase 6 | Unchanged — operator. |
| Optional CI (unittest + Phase 0 headless) | `.github/workflows/optimizer-plan-v2-phase0.yml` runs `SKIP_LIVE=1` smoke on `main` / `coding-agent-dev`. |

**Terminal summary:** HEAD advanced to `5438bb4` with validation/docs only; no code path changes. CI workflow for `SKIP_LIVE=1` smoke was the next repo-side follow-up from plan-v2 optional §3 — implemented in commit `183b6d3` (`.github/workflows/optimizer-plan-v2-phase0.yml`).

---

## Code Review — commit 81d1353f0abf133342c937ac44109661834aa099 (2026-05-09)

### Delta since `5438bb4` (3 commits: CI workflow + Gemini docs + SESSION-LOG)

**Changed files:** `.github/workflows/optimizer-plan-v2-phase0.yml` (added), `VALIDATION.md` (Gemini 429 section), `TODO.md` (Gemini attempt checked off), `SESSION-LOG.md` (new).

### Phase 1–3 (delta)

- **No executable code changes** — optimizer, evaluator, GEPA runner, metrics, and smoke script are all unchanged.
- **CI workflow confirmed green** on commit `933f3f3` (run against `pulak999/gopher`); `SKIP_LIVE=1` smoke (unittest + dry-run) passes on Ubuntu without GPU.
- **VALIDATION.md** now records Gemini GEPA attempt with HTTP 429 (`RESOURCE_EXHAUSTED`); no reflection step succeeded; `best_candidate` stayed seed YAML; milestone 3 still unmet per plan-v2.
- **SESSION-LOG.md** added as pick-up-later index; points to VALIDATION.md and TODO.md for canonical detail.
- **Risk:** None. All changes are additive documentation.

### Plan cross-reference (`plan-v2.md`) at HEAD

| plan-v2 milestone | Status at HEAD | Gap |
|-------------------|----------------|-----|
| 1. Throwaway clone + venv | Operator-only | No repo change possible — script, docs, and uv install instructions exist |
| 2. vLLM serves `/v1` | Operator-only | Script wires curl check when `VLLM_API_BASE` set; cannot start server from in-repo |
| 3. ≥1 GEPA reflection via local `--api-base` | **Not met** | Gemini path tried, hit 429; vLLM path not attempted yet |
| 4. `evaluate.py` both harnesses PASS | **Done + logged** | VALIDATION.md Phase 4 row at `ecfc683` |
| 5. Results in VALIDATION.md | **Partial** | Phase 4 + Gemini logged; vLLM reflection row outstanding |
| 6. Scratch clone cleanup | Operator-only | — |

**Conclusion:** All in-repo automation for plan-v2 is complete (smoke script, CI workflow, wiring for both vLLM and Gemini paths). The only remaining plan milestones require operator action: running a vLLM server (or equivalent) and then appending the final VALIDATION.md row. Optional follow-up: merge `coding-agent-dev` → `main` once milestone 3 is satisfied.

### Cross-reference: what can be implemented in this session

| Item | Can implement now? | Notes |
|------|--------------------|-------|
| Start vLLM server | **No** — needs GPU shell | Titan RTX available on host; operator must run `vllm serve …` |
| Run GEPA reflection via vLLM | **No** — needs server | Once `VLLM_API_BASE` is set, `smoke_plan_v2.sh` handles it |
| Append VALIDATION.md vLLM row | **No** — needs live data | Write after reflection run completes |
| Merge `coding-agent-dev` → `main` | **Yes** — git only | Only if user confirms live validation is acceptable |
| Phase 1 / Phase 6 (scratch clone) | **No** — operator-only | No in-repo change needed |
| Improve error handling / robustness in scripts | **Possible** | Only if user identifies specific gaps |

---

## Code Review — commit 5a418e1a6dafa9435514f9842ca9438f8065eae1 (2026-07-30)

Scope: review in service of `control-folder/plans/effect-map-experiment-v1.md`
(Experiment A — state-delta effect map). Written in ADS-STE100 Simplified
Technical English.

### Phase 1 — Repo overview

The repo has three layers:

| Layer | Path | Owns |
|---|---|---|
| Control | `control-folder/` | Plans, docs, logs. No code. |
| Engine (`gopher`) | `cuda-ioctl-map/` | Capture, inference, replay, optimizer. ~2.7 kLOC. |
| Vendored refs | `refs/` | 5 git submodules. Read-only. |

Execution starts in three places: `run.sh` (capture and replay),
`optimizer/evaluate.py` (the fitness function), `optimizer/gepa_runner.py`
(the evolutionary driver).

The data object that flows through the system is a JSONL trace record:
`{type, seq, fd, dev, req, sz, before, after, ret}`. Every downstream stage
reads this record.

The architecture is a pipeline inside an evolutionary loop. This agrees with
the plan.

**Structural flag 1 — version skew in the vendored SDK.**
`refs/open-gpu-kernel-modules` is at tag **610.43.02**. The host `hulk` runs
driver **555.42.02** (`modinfo nvidia`). The plan (§4 B1) assumes the open
module is 555.42.02. It is not. All command tables taken from these headers
are 610 tables. This makes the plan's size oracle (§3 A1) more necessary, not
less: the oracle measures precisely this drift.

**Structural flag 2 — command counts in the plan do not match the headers.**

| Quantity | Plan §0/§2 | Measured in `refs/open-gpu-kernel-modules` |
|---|---|---|
| Total `*_CTRL_CMD_*` | 2445 | **2899** |
| `GET_*` readable | 969 | **1178** |
| NV2080 `GET` | 324 | **428** |
| NV2080 total | — | 936 |

The plan's numbers are low by about 20%. The likely cause is the version skew
plus a different grep. Use the measured numbers.

### Phase 2 — File-by-file

**`intercept/nv_sniff.c` (271 lines) — LD_PRELOAD tracer.**
Responsibility: log every `open`/`openat`/`close`/`ioctl` on `/dev/nvidia*`.
Correct in the main path. Three defects:

- **F1 (high) — out-of-bounds read.** Line 219: `sz = _NV_IOC_SIZE(request)`;
  line 220 sets `sz = MAX_CAPTURE_SZ` (4096) when the encoded size is 0. Line
  237 then does `memcpy(before_buf, arg, sz)`. For every UVM ioctl the encoded
  size is 0, so the tracer reads 4096 bytes from a buffer that is usually much
  smaller. This reads adjacent stack or heap. It has not crashed yet, but it is
  undefined behaviour, and it is the direct cause of the "stack noise" that
  makes `find_handle_offsets.py` exclude all UVM ioctls (that file, line 17).
  The exclusion is a workaround for this bug, not a property of UVM.
- **F2 (medium) — `errno` is not recorded.** The record has `ret` but no
  `errno`. The plan's size oracle (§3 A1) discriminates three outcomes by
  error code. For NVIDIA RM the status is in the params struct, so the oracle
  still works, but the general trace loses information that cannot be
  recovered later.
- **F3 (low) — the tracer does not follow the `params` pointer.** For
  `NV_ESC_RM_CONTROL` the 32-byte struct holds `NvP64 params` — a *pointer* to
  the real payload. The tracer logs the pointer value, never the payload. So
  every trace in `sniffed/` records that a control fired and with which `cmd`,
  but **not what the control returned**. This is the single largest gap
  between the current tracer and Experiment A.

**`lookup/ioctl_table.json` and `CUDA_IOCTL_MAP.md` — the naming layer.**

- **F4 (critical) — the escape-code names are wrong.** The table was written
  from model recall, not from the header, although each row claims
  `"source":"nv-ioctl-numbers.h"`. The escape number is the low byte of the
  ioctl `nr` field, with magic `'F'` (0x46, from
  `kernel-open/common/inc/nv-ioctl-numbers.h`). Compare the table against
  `src/nvidia/arch/nvalloc/unix/include/nv_escape.h`:

  | Code | `ioctl_table.json` says | `nr` | `nv_escape.h` says | Verdict |
  |---|---|---|---|---|
  | `0xC020462A` | `NV_ESC_RM_ALLOC` | 0x2A | **`NV_ESC_RM_CONTROL`** | WRONG |
  | `0xC0104629` | `NV_ESC_RM_CONTROL` | 0x29 | **`NV_ESC_RM_FREE`** | WRONG |
  | `0xC020462B` | `NV_ESC_RM_ALLOC_MEMORY` | 0x2B | **`NV_ESC_RM_ALLOC`** | WRONG |
  | `0xC030462B` | `NV_ESC_RM_ALLOC (large)` | 0x2B | `NV_ESC_RM_ALLOC` | right by luck |
  | `0xC038464E` | `NV_ESC_RM_VID_HEAP_CONTROL` | 0x4E | **`NV_ESC_RM_MAP_MEMORY`** | WRONG |
  | `0xC018462D` | `NV_ESC_RM_FREE` | 0x2D | *no such escape* | WRONG |

  The mislabelled `0xC020462A` is the **most frequent ioctl in the whole
  corpus** — 178 of 230 calls in `cu_init`. The project has been calling its
  busiest call by the wrong name.

  Proof by decode: reading the 32-byte `before` buffer of `0xC020462A` as
  `NVOS54_PARAMETERS {hClient, hObject, cmd, flags, params, paramsSize,
  status}` gives consistent handles (`0xc1d00e25`/`0xc1d00e26`), valid class
  prefixes in `cmd` (`0x0000xxxx` root, `0x0080xxxx` device, `0x2080xxxx`
  subdevice), `status = 0`, and `ret = 0` on all 178 records. No other layout
  decodes this cleanly.

  `CUDA_IOCTL_MAP.md` inherits every one of these errors, and that file is
  cited as the project's ioctl reference.

**`tools/find_handle_offsets.py` (287 lines) — handle inference.**
Diffs `before` buffers of two runs; a 4-byte window that varies is a candidate
handle. The pointer filter (upper half in `0x00007f00–0x00007fff`) is a sound
heuristic. Two flags: the UVM exclusion is a symptom of F1; and
`MIN_VARY_FRACTION = 0.05` is unjustified — no experiment fixed that value.

**`replay/replay.py` (213 lines) — replay engine.** Reads a trace, re-opens
devices, re-issues each ioctl with patched handles. Prints
`DONE — n/m succeeded, f failed, s skipped`. Sound. Note it replays the
32-byte control struct with a **stale userspace `params` pointer** — a
consequence of F3. The pointer is meaningless in the replay process, so every
control replay writes its output to whatever that address maps to, or fails.
Replay "success" for controls is therefore weaker evidence than it appears.

**`optimizer/evaluate.py` (336 lines) and `optimizer/metrics.py` (153 lines) —
the fitness oracle.** This is the plan's target. `score_gate` returns
pass/fail on `failed > 0` plus a skip-regression check; the score is
`handle_offset_agreement_ratio`. Confirmed weaknesses, exactly as plan-v1 §4
states:

- **F5 (high) — the oracle is gameable by truncation.** Nothing counts
  coverage. A candidate that emits fewer ioctls and fails none scores the same
  as, or better than, the golden trace. plan-v1 §4 A4 predicts this; it is
  real and present in `score_gate`.
- **F6 (medium) — `build_asi` is a firehose, not a summary.** It ships
  `replay_stdout[-8000:]` plus `replay_stderr[-4000:]` to the reflection
  model. This is the "token-efficient — how??" box that plan-v1 §3 marks
  **Weak**. It is raw tail text, not a canonical diff.
- **F7 (low) — silent negative scoring.** Line 193 adds `-1.0` and calls
  `continue` without appending a row. That program then vanishes from
  `rows` while still moving the aggregate. A failed program is invisible in
  the report.

**`tools/snapshot_driver_state.sh` + `tools/compare_snapshots.py` — the
ancestor of Experiment A.** These already do "snapshot, act, snapshot, diff".
But the snapshot is scraped text from `nvidia-smi -q` and procfs, not the
ioctl-level control sweep the plan wants, and the noise mask
(`SKIP_LINE_PATS`) is **hand-written from guesswork**, not measured. The plan's
A2 replaces this guessed mask with an empirical one. Keep the shape; replace
the mechanism.

**`optimizer/tests/test_metrics.py`** is the only test. It covers `metrics.py`
only. There is no test for the tracer, the inference, or the replay engine.

**CI:** one workflow, `.github/workflows/optimizer-plan-v2-phase0.yml`. It runs
`SKIP_LIVE=1 ./optimizer/scripts/smoke_plan_v2.sh` on `ubuntu-latest`. The CI
runner has **no GPU**, so CI can only ever check unit tests, imports and dry
runs. All GPU work is local-only. This division is correct and must stay.

### Phase 3 — Cross-cutting

1. **Inconsistency.** `nv_sniff.c` guarantees only that `before`/`after` hold
   `_IOC_SIZE(req)` bytes of the *top-level* struct.
   `find_handle_offsets.py` and `replay.py` both assume that is the whole
   argument. For `NV_ESC_RM_CONTROL` it is not (F3). Every conclusion the
   project draws about control commands rests on this unstated assumption.
2. **Missing piece.** There is no `cmd` decoder. The traces hold 49 distinct
   `NV2080/NV0080/NV0000` control commands in `cu_init` alone, and nothing in
   the repo maps a `cmd` word to a name or a struct. The SDK headers in
   `refs/` supply this for free and are unused.
3. **Most likely bug site.** `nv_sniff.c` lines 218–240 (F1). It is undefined
   behaviour on every UVM ioctl, and it silently poisons the inference input.
4. **Warn a new engineer first:** do not trust `lookup/ioctl_table.json` or
   `CUDA_IOCTL_MAP.md` (F4). Verify every escape name against
   `nv_escape.h` + magic `'F'`. Then check the driver version against the
   vendored SDK tag before quoting any struct.

### Step 0.3 — Cross-reference: plan vs codebase

| Plan step | State in repo | Action |
|---|---|---|
| A1 — RM object ladder (client/device/subdevice) | **Not present as code.** But `sniffed/cu_init.jsonl` contains the exact `NV_ESC_RM_ALLOC` sequence that builds it. | Write a new C sweeper. Use the trace as the reference sequence. |
| A1 — `NV2080_CTRL_CMD_*GET*` table | **Absent.** Headers in `refs/` are unused. | Write a header extractor. Version-skew caveat applies. |
| A1 — size oracle | **Absent.** | New. Cheap. Run first. |
| A2 — noise floor | **Partial ancestor** in `compare_snapshots.py`, but the mask is guessed, not measured. | Replace the mechanism; keep the snapshot/diff shape. |
| A3 — CUDA corpus | **Already built.** `programs/` holds `cu_init`, `cu_ctx_create`, `cu_ctx_destroy`, `cu_mem_alloc`, `cu_memcpy`, `cu_module_load`, `cu_launch_null`, `cu_device_get`. This is 8 of the plan's 9 rows. | Reuse as-is. `cuStreamCreate` is the only gap. |
| A4 — scoring | **Absent.** | New. |
| A5 — wire to the loop | Hooks exist (`metrics.py:score_gate`), and F5 confirms the reward hack the plan wants to close. | New scorer feeds `score_gate`. |
| B — RPC tracer | Blocked. hulk runs the proprietary module (F-flag: `license: NVIDIA`). Confirmed. | Out of scope tonight, as the plan says. |

**Conflicts between the plan and the code:** two, both listed above — the
command counts (§0/§2) and the open-module version (§4 B1). Neither blocks
Experiment A. Both are recorded here so the plan can be amended.

---

## Code Review — commit aaf7d185e0d10e933925f5f3647957047c2f3a09 (2026-08-06)

Scope: `cuda-ioctl-map/tools/effectmap/` (2225 lines, added in the three commits
since the `5a418e1` review and never reviewed). Run for `ouroboros-plan-v3.md`.
Findings are numbered `E*` so they do not collide with the `F*` series above.

### Phase 1 — repo overview

`tools/effectmap/` is a second, independent path to the specification. It does
not use the capture/replay loop. It interrogates the loaded driver directly.

Pipeline, in dependency order:

```
extract_ctrl_table.py  (headers -> ctrl_table.json, sizes by compiled probe)
        |
sweep_controls.c --size-scan  (shipped driver -> abi_probe_all.jsonl)
        |
gen_sweep_list.py  (safety filter; driver sizes override header sizes)
        |
gen_templates.py   (adds request templates for index-list commands)
        |
sweep_controls.c   (state_vector_run*.jsonl)
        |
noise_floor.py (A2 gate)  ->  run_effect_map.py (A3/A4)  ->  effect_map.json
                                classify_mig.py -> mig-command-classification.md
```

`sweep_controls.c` is the only component that opens `/dev/nvidiactl`. Everything
else is offline data processing. That is a clean separation and it is the main
reason the subsystem is safe on a shared box.

One record shape throughout: `{cmd,size,ret,errno,status,resp}` for a sweep,
`{cmd,present,found_size,probe_status,accept_status}` for a probe.

**Structurally odd:** `out/` holds 106k lines of committed run artifacts,
including a 33k-line `sweep_filter_report.json`. These are measurement outputs
committed as source. They are the evidence base, so this is defensible, but they
are also now **stale** — every one was measured against driver 555.42.02 and the
box runs 610.43.02.

### Phase 2 — file by file

**`sweep_controls.c` (568 lines) — the only driver-facing component.**
Builds `hClient -> hDevice -> hSubDevice` by hand, replaying the exact
`GET_PROBED_IDS -> ATTACH_IDS -> open(/dev/nvidiaN)` order that libcuda uses.
The ladder is read from a real trace, not guessed. Good.

The size-oracle logic is correct and well justified in the comments: presence
uses a real object (so `0x56` is reachable), size uses a bogus handle (so the
size check answers before object resolution). Both are safe on write commands.

- **E1 — stack buffer overflow in `load_cmds`. Blocks v3 §4 A2 as written.**
  `char hex[2 * MAX_PREFILL + 2]` is **1026 bytes**. The parse is
  `sscanf(p, "%lx %lu %2048s", &cmd, &sz, hex)`, which permits **2049 bytes**.
  A template field longer than 1025 characters smashes the stack.
  Template length is `8 + 16n` characters for `n` requested indices, so the
  overflow starts at **n >= 64**.
  Not reachable today: `gen_templates.py` uses `MAX_INDEX = 32`, and the longest
  live template is 520 characters.
  **Reachable the moment `MAX_INDEX` is raised past 63.** The trigger is
  `NV2080_CTRL_CMD_GPU_GET_INFO_V2` (`0x20800102`), driver size 524, capacity
  **65** — it does not get clamped by its own `paramsSize` the way FB does.
- **E6 — `--probe-mode` is parsed and then ignored on the size-scan path.**
  `run_size_scan()` does not take the mode. Harmless today; misleading later.
- **E7 — the size scan steps `s += 1` from 0 to `max_size`.** Cost is linear in
  the accepted size, per command. Fine at the current sizes. A wider `--size-scan`
  than 65536 gets expensive fast.

**`gen_templates.py` (108 lines) — request templates.**
Exists because a zeroed params buffer reads almost nothing from this ABI
(`arch-findings` Finding 6). `make_template` writes `count = n`, then `n` pairs
of `(index, 0)`.

- **E2 — `MAX_PREFILL = 512` silently drops an oversized template.** In
  `load_cmds`, the guard is `hl / 2 <= MAX_PREFILL`. On failure `prefill_len`
  stays 0 and the sweep sends a **zeroed buffer**, which reads nothing. There is
  no warning. A silent revert to the known-bad case is worse than an error.
- **E3 — `make_template` can only request indices `1..n`, contiguously.** It
  cannot request an arbitrary set. So reaching a high index means requesting
  every index below it too, and paying for them in `paramsSize`.

**`gen_sweep_list.py` (156 lines) — the safety filter.**
Conservative and correct: a command is admitted only if it is positively a read,
and any write-ish token rejects it. `_INTERNAL_` is denied. The probe file
overrides header sizes with driver-measured sizes. This is the right precedence.

- **E8 — `_EXEC` is in `DENY_TOKENS`.** So `NV2080_CTRL_CMD_GPU_EXEC_REG_OPS`
  can never reach the sweeper through this path. v3 §4 A3 must add an explicit,
  separate code path in `sweep_controls.c`. It cannot be done by editing a
  command list. **This is correct behaviour and must not be relaxed** — widening
  the filter to admit `_EXEC` would admit every other exec-class command too.

**`extract_ctrl_table.py` (218 lines) — the static command table.**
Measures `sizeof()` by compiling a probe and pruning what gcc rejects, rather
than parsing C. That is the right call and it is unusually honest tooling.
Skips `*_PARAMS_MESSAGE_ID` correctly — those are FINN tags whose small ordinals
would otherwise collide with real low-numbered commands.

**`noise_floor.py` (97 lines) — the A2 gate.**
Compares two runs and reports the byte-stable fraction.

- **E5 — the gate does not fail the process.** `total_ok == 0` exits 1, but
  `stable_ratio < 0.5` only **prints** `GATE: FAIL`. A script or CI step that
  checks the exit code will proceed past a failed gate. The documentation treats
  this gate as a hard stop; the code treats it as advice.

**`run_effect_map.py`, `classify_mig.py`, `effect_probe.cu`, `diff_ctrl_tables.py`**
— read at survey level. No new findings beyond what `arch-findings-20260730.md`
already records (Findings 6, 7, 8). `run_effect_map.py` emits both the
op-vs-baseline and the adjacent-rung views; the rung-delta view is the usable one.

### Phase 3 — cross-cutting

1. **Every committed artifact under `out/` is stale.** All were measured against
   555.42.02. `/proc/driver/nvidia/version` now reports **610.43.02**. Nothing in
   the subsystem records the driver version it measured against, so nothing
   detects this automatically. **This is the single most dangerous property of
   the subsystem right now** — the files look authoritative and are not.
2. **Missing piece: no provenance stamp.** No output file records driver version,
   GPU model, or git SHA. Every other measurement discipline in the sibling
   `gpu-virt/motivation` repo requires this. Add it.
3. **Most likely bug site:** `load_cmds` (E1), and it is reachable by the very
   next planned change.
4. **Warn a new engineer first:** the three size caps that govern any template
   change are independent and only one of them errors. In order of tightness for
   `FB_GET_INFO_V2`: `paramsSize` 444 (55 indices), `MAX_PREFILL` 512 (63),
   `hex[]` 1026 (63). Exceed the first and `make_template` silently clamps.
   Exceed the second and the template is silently dropped. Exceed the third and
   the process smashes its stack.

### Step 0.3 — cross-reference: `ouroboros-plan-v3.md` vs the codebase

| Plan step | State in repo | Verdict |
|---|---|---|
| A1 — re-probe ABI on 610.43.02 | Tooling exists and is unchanged. Re-run is a pure re-execution. | **Ready.** No code change. |
| A2 — raise `MAX_INDEX` 32 -> 68 | `gen_templates.py:58`. | **CONFLICT — the plan is wrong.** See below. |
| A3 — `EXEC_REG_OPS` probe | Not present. `_EXEC` is denied by the filter (E8). | **New code required** in `sweep_controls.c`. Cannot be a list edit. |
| Lane B — colouring | Lives in `gpu-virt/motivation`, a different repo. | Out of scope for this repo's chunks. |
| Lane C — firmware | Closed by `gsp-firmware-re-assessment.md`. | No work. |

**The conflict, stated precisely.** Plan v3 §1.4 and §4 A2 say to raise
`MAX_INDEX` from 32 to **68**, to reach `LTC_COUNT` (0x22=34), `LTS_COUNT`
(0x23=35), `PSEUDO_CHANNEL_MODE` (0x25=37) and `LTC_MASK` (0x2b=43).

Measured against the current code, 68 is both **unsafe and unnecessary**:

| `MAX_INDEX` | FB_GET_INFO_V2 | GPU_GET_INFO_V2 | Result |
|---|---|---|---|
| 32 (today) | n=32, 520 chars | n=32, 520 chars | safe |
| **55** | n=55, 888 chars | n=55, 888 chars | **safe, and reaches index 43** |
| 63 | n=55, 888 chars | n=63, 1016 chars | safe, at the edge |
| **68 (plan)** | n=55, 888 chars | **n=65, 1048 chars** | **stack overflow (E1)** |

`FB_GET_INFO_V2` self-clamps at 55 because its driver `paramsSize` is 444
(`4 + 55*8`). `GPU_GET_INFO_V2` does not — its size is 524, giving capacity 65.

**`MAX_INDEX = 55` reaches all four target indices and overflows nothing.**

**One open dependency.** The 610 SDK header declares
`NV2080_CTRL_FB_INFO_MAX_LIST_SIZE = 0x80` (128 entries, 1028 bytes), but the
555 probe measured an enforced `paramsSize` of 444 (55 entries). Now that the box
runs 610, A1 may measure 1028. If it does, capacity rises to 128 and the E1
overflow becomes reachable at a lower `MAX_INDEX` than the table above shows.
**A1 must therefore run before A2 picks a number.** The plan already orders them
that way; this review confirms the ordering is load-bearing, not cosmetic.
