## [2026-05-10] GEPA + Qwen2.5-7B-Instruct — first useful YAML proposal

### What ran

- vLLM 0.6.1.post1 + `Qwen/Qwen2.5-7B-Instruct` on GPU 0 (`--enforce-eager --max-model-len 16384
  --dtype half`, `HF_HOME=/tmp/hf_pm3371`).
- `gepa_runner.py --seed optimizer/harness.gepa_seed.yaml --max-metric-calls 10
  --reflection-model openai/Qwen/Qwen2.5-7B-Instruct`.
- Iteration 0: seed scored 0.8889 (cu_init + cu_mem_alloc).
- Iteration 1: Qwen proposed `cu_ctx_create.cu` → score improved to **0.8926** (accepted).
- Iterations 2–9: `ContextWindowExceededError` (~19-20 k tokens > 16384 limit) — GEPA
  history grows per iteration; vLLM also died at iteration 8 (connection refused).
- `best_candidate`: seed + `cu_ctx_create.cu`; updated `harness.gepa_seed.yaml`.

### Files changed

| File | What changed |
|------|-------------|
| [cuda-ioctl-map/optimizer/harness.gepa_seed.yaml](cuda-ioctl-map/optimizer/harness.gepa_seed.yaml) | Added `cu_ctx_create.cu` (Qwen-proposed improvement; score 0.8889 → 0.8926). |
| [AGENT_SERVER_SETUP.md](AGENT_SERVER_SETUP.md) | §4a-hulk: Qwen2.5-7B-Instruct startup command with `--enforce-eager`, `HF_HOME=/tmp/hf_pm3371`; context-overflow note; `--max-metric-calls 3` guidance. |
| [VALIDATION.md](VALIDATION.md) | New section "Phase 3 (GEPA + Qwen2.5-7B-Instruct)". |
| [LOG.md](LOG.md) | This entry. |
| [TODO.md](TODO.md) | Qwen phase checked off; context-overflow follow-up added. |

### Notes

- `--enforce-eager` is required for Qwen2.5-7B-Instruct on 24 GB TITAN RTX: without it, CUDA
  graph capture consumes all VRAM headroom beyond model weights, leaving only 382 blocks
  (6,112 tokens) for KV cache.
- Context overflow is a GEPA-internal issue (history accumulation). Workaround: `--max-metric-calls 3`.
  A model with 32k+ context (e.g. Qwen2.5-14B or a quantized 70B) would remove the limit.
- Model was downloaded to `/tmp/hf_pm3371` (NFS home-dir quota; xet-protocol left incomplete blobs;
  bypass: `HF_HUB_DISABLE_XET=1` + `HF_HOME=/tmp/hf_pm3371`).

---

## [2026-05-09] plan-v2 — milestone 3 DONE (local vLLM GEPA reflection)

### What ran

- vLLM 0.6.1.post1 + `meta-llama/Llama-3.2-1B` on GPU 0 (`CUDA_VISIBLE_DEVICES=0`,
  `HF_HUB_OFFLINE=1`, `--dtype half`, `--chat-template llama_base_chat_template.jinja`).
- `gepa_runner.py --max-metric-calls 6 --reflection-model openai/meta-llama/Llama-3.2-1B
  --api-base http://127.0.0.1:8000/v1 --api-key EMPTY`.
- Iteration 0: evaluator scored seed harness ~0.778. Iterations 1–3: LLM called and
  returned HTTP 200 each time (outlines/venv issues fully resolved). Proposed texts
  scored −1.0 (1B base model, not instruct-tuned); seed kept as best.
- Plan-v2 milestone 3 **satisfied** — reflection round-trip proven end-to-end.
- `coding-agent-dev` merged to `main` (commit `58b3191`).

### Files changed

| File | What changed |
|------|-------------|
| [cuda-ioctl-map/optimizer/scripts/llama_base_chat_template.jinja](cuda-ioctl-map/optimizer/scripts/llama_base_chat_template.jinja) | New: minimal Human/Assistant Jinja2 chat template for base LLMs. |
| [AGENT_SERVER_SETUP.md](AGENT_SERVER_SETUP.md) | §4a-hulk: correct model (Llama-3.2-1B), one-time venv fixes (numpy<2, pyairports stub). |
| [VALIDATION.md](VALIDATION.md) | New section "Phase 3 (GEPA + local vLLM)" with reproduction steps and outcome. |
| [TODO.md](TODO.md) | Milestone 3 checked off; follow-up items added. |

### Functions / fixes

| Fix | Location | Notes |
|-----|----------|-------|
| numpy<2 downgrade | vllm venv | `outlines 0.0.46` requires `numpy.lib.function_base` removed in numpy 2.0. |
| pyairports stub | vllm venv | PyPI `pyairports 0.0.1` installs a `sample` module, not `pyairports`; created empty stub. |
| llama_base_chat_template.jinja | optimizer/scripts/ | `transformers v4.44+` requires explicit chat template; Llama-3.2-1B base has none. |

---

## [2026-05-09] plan-v2 — GEPA + Gemini smoke (Phase 4 + Phase 3 attempt)

### What ran

- `cuda-ioctl-map/`: full `smoke_plan_v2.sh` with `OPT_PY=optimizer/.venv/bin/python`,
  `GEPA_USE_GEMINI=1`, `GEPA_MAX_METRIC_CALLS=6`.
- Phase 4: both harnesses `"ok": true`. Phase 3: GEPA iteration 0 scored seed;
  reflective steps failed on Gemini API **429** (free-tier quota).

### Files changed

| File | What changed |
|------|-------------|
| [VALIDATION.md](VALIDATION.md) | New subsection “Phase 3 (GEPA + Gemini)”. |
| [TODO.md](TODO.md) | Clarify strict plan-v2 local vLLM vs Gemini attempt done. |

---

## [2026-05-09] plan-v2 — GitHub Actions Phase 0 smoke

### What shipped

- `.github/workflows/optimizer-plan-v2-phase0.yml` — on `push` / `pull_request`
  to `main` or `coding-agent-dev`, runs `SKIP_LIVE=1
  ./optimizer/scripts/smoke_plan_v2.sh` from `cuda-ioctl-map/` on
  `ubuntu-latest` (no GPU).

### Files changed

| File | What changed |
|------|-------------|
| `.github/workflows/optimizer-plan-v2-phase0.yml` | New workflow. |
| `ARCH.md`, `CLAUDE.md`, `TODO.md`, `plan-v2.md` | Document CI. |
| `code.md` | Delta review for `5438bb4` + CI row in plan cross-ref. |

### Local verify

- `SKIP_LIVE=1 ./optimizer/scripts/smoke_plan_v2.sh`: PASS.

---

## [2026-05-09] plan-v2 Phase 4 live smoke (dev clone)

### What ran

- Full `./optimizer/scripts/smoke_plan_v2.sh` from `cuda-ioctl-map/` (no
  `SKIP_LIVE`): unittest, dry-run, live `evaluate.py` on `harness.yaml` and
  `harness.smoke2.yaml`. Phases 2–3 skipped (no `VLLM_API_BASE`).

### Files changed

| File | What changed |
|------|-------------|
| [VALIDATION.md](VALIDATION.md) | Appended plan-v2 Phase 4 evidence (SHA, host, pass). |
| [TODO.md](TODO.md) | Mark Phase 4 live run done; clarify remaining operator steps. |

---

## [2026-05-09] plan-v2 implement-from-plan (smoke script + docs)

### What shipped

- `cuda-ioctl-map/optimizer/scripts/smoke_plan_v2.sh` — Phase 0 with
  `SKIP_LIVE=1`; optional Phase 4 live evaluate; optional Phase 2–3 when
  `VLLM_API_BASE` + `GEPA_REFLECTION_MODEL` are set.
- Doc updates: `plan-v2.md` (automation table), `VALIDATION.md` (plan-v2 stub +
  script PASS), `code.md` (plan-v2 cross-ref), `ARCH.md`, `CLAUDE.md`,
  `TODO.md`, `optimizer/README.md`.

### Local verify

- `SKIP_LIVE=1 ./optimizer/scripts/smoke_plan_v2.sh` from `cuda-ioctl-map/`:
  PASS.

---

## [2026-05-09] plan-v1 validation (live + GEPA partial)

### What ran

- Unit tests under `cuda-ioctl-map/optimizer/tests/`: PASS.
- Live evaluator on `programs/cu_init.cu` and `programs/cu_mem_alloc.cu`: PASS
  (see [VALIDATION.md](VALIDATION.md)).
- GEPA `gepa_runner.py` with `uv`-managed `optimizer/.venv`: evaluator scored
  seed harness; reflection blocked without `OPENAI_API_KEY` (litellm); see
  VALIDATION.md.

### Files changed (this follow-up)

| File | What changed |
|------|--------------|
| `VALIDATION.md` | New: commands and pass/fail notes. |
| `cuda-ioctl-map/optimizer/harness.smoke2.yaml` | New: smoke-2 harness for `cu_mem_alloc.cu`. |
| `cuda-ioctl-map/optimizer/requirements.txt` | Add `litellm`; pin `gepa` floor. |
| `cuda-ioctl-map/optimizer/.gitignore` | Ignore `optimizer/.venv/`. |
| `cuda-ioctl-map/optimizer/README.md` | uv venv install, GEPA env notes, link to VALIDATION.md. |

---

## [2026-05-09] GEPA Optimizer Harness (plan-v1)

### Features Implemented

- Live evaluator orchestrating double capture, `find_handle_offsets.py`, baseline vs candidate replay, JSON metrics, and skip-regression checks versus baseline replay.
- `metrics.py` for parsing `DONE` replay summaries and diffing `handle_offsets.json` entries.
- Optional `gepa_runner.py` calling `optimize_anything` over harness YAML text.
- JSON harness for dry-run without PyYAML; YAML harness for normal use.
- Unit tests for metrics parsing and scoring gates.

### Files Changed

| File | What changed |
|------|--------------|
| `cuda-ioctl-map/optimizer/metrics.py` | New: replay summary parse, offset diff, ASI builder, score gate. |
| `cuda-ioctl-map/optimizer/evaluate.py` | New: harness load, pipeline, CLI. |
| `cuda-ioctl-map/optimizer/gepa_runner.py` | New: GEPA driver with temp harness file per candidate. |
| `cuda-ioctl-map/optimizer/harness.yaml` | New: default single-program harness. |
| `cuda-ioctl-map/optimizer/harness.min.json` | New: JSON harness for dry-run / no PyYAML. |
| `cuda-ioctl-map/optimizer/requirements.txt` | New: `gepa`, `PyYAML`. |
| `cuda-ioctl-map/optimizer/README.md` | New: usage and prerequisites. |
| `cuda-ioctl-map/optimizer/runs/.gitignore` | New: ignore generated run artifacts. |
| `cuda-ioctl-map/optimizer/tests/test_metrics.py` | New: unittest suite. |
| `code.md` | New: review + plan cross-reference. |
| `CLAUDE.md` | New: agent-oriented project notes. |
| `ARCH.md` | New: architecture overview including optimizer layer. |
| `TODO.md` | New: done items and follow-ups. |

### Functions Written

| Function | File | Description |
|----------|------|-------------|
| `parse_replay_summary` | `optimizer/metrics.py` | Extract ok/total/failed/skipped from replay stdout. |
| `compare_handle_offsets` | `optimizer/metrics.py` | Compare baseline vs candidate handle offset lists per ioctl. |
| `score_gate` | `optimizer/metrics.py` | Enforce zero failures and skip regression bound. |
| `evaluate_harness` | `optimizer/evaluate.py` | Run full per-program evaluation pipeline. |
| `load_harness_file` | `optimizer/evaluate.py` | Load harness YAML/JSON from disk. |

### Data Structures Created

| Name | File | Description |
|------|------|-------------|
| `ReplaySummary` | `optimizer/metrics.py` | Dataclass for parsed `DONE` line fields. |

### Notes

- `gepa` and `PyYAML` are not verified installed in this environment; install via `optimizer/requirements.txt` before running `gepa_runner.py` or YAML harness loads.
- Full live evaluation requires NVIDIA CUDA capture and privileged replay; use `--dry-run` for smoke checks without hardware.
- Dynamic import of `metrics.py` registers a unique `sys.modules` name so `@dataclass` works under `importlib`.
