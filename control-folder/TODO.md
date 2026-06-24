# TODO — ioctl-cuda-mapping

## Done (plan-v1 baseline)

- [x] Optimizer harness: `cuda-ioctl-map/optimizer/harness.yaml`
- [x] Metrics: `optimizer/metrics.py` (replay summary parse, offset diff)
- [x] Evaluator CLI: `optimizer/evaluate.py`
- [x] GEPA runner stub: `optimizer/gepa_runner.py` + `requirements.txt`
- [x] Optimizer README + `runs/` gitignore
- [x] Unit tests for metrics parsing (`optimizer/tests/test_metrics.py`)

## Next (roadmap / follow-up)

### plan-v2 ([plan-v2.md](plan-v2.md)) — split: repo vs operator

- [x] **In repo:** `optimizer/scripts/smoke_plan_v2.sh` (Phase 0, 4, optional 2–3);
      `SKIP_LIVE=1` CI-friendly path; [VALIDATION.md](VALIDATION.md) plan-v2 stub
      + Phase 0 log.
- [x] **Phase 4 (live evaluate)** on dev clone: full `smoke_plan_v2.sh` without
      `SKIP_LIVE` — PASS; see [VALIDATION.md](VALIDATION.md) “Phase 4 (live
      evaluate)”.
- [x] **Phase 3 (local vLLM + GEPA reflection) — 2026-05-09:** vLLM 0.6.1.post1
      + `meta-llama/Llama-3.2-1B`, `--api-base http://127.0.0.1:8000/v1`; 3
      reflection iterations completed end-to-end (HTTP 200 from LLM each time).
      Model quality insufficient to improve harness (1B base), but wiring proven.
      See [VALIDATION.md](VALIDATION.md) "Phase 3 (GEPA + local vLLM)".
- [x] **Phase 3 (Qwen2.5-7B-Instruct) — 2026-05-10:** downloaded to `/tmp/hf_pm3371`;
      vLLM `--enforce-eager --max-model-len 16384`; GEPA iteration 1 proposed
      `cu_ctx_create.cu` → score 0.8889 → **0.8926**; accepted; `harness.gepa_seed.yaml`
      updated.  Iterations 2+ hit context-window overflow (~19k tokens > 16384 limit).
- [ ] GEPA context overflow: GEPA history accumulates per iteration; mitigate with
      `--max-metric-calls 3` or use a 32k+ context model (Qwen2.5-14B, quantized 70B).
- [ ] Phase 6 (scratch clone cleanup): operator step after throwaway clone run.
- [x] **Phase 3 (Gemini path) — smoke attempt (2026-05-09):** documented in
      [VALIDATION.md](VALIDATION.md); reflection blocked by Gemini **429**
      (quota), not auth wiring.
- [ ] Phase 1 roadmap: generic sniffer device globs + extended JSONL fields
- [ ] Phase 2: `infer/classify.py` + emitted `spec.json` vs handwritten offsets
- [ ] Wire GEPA to richer candidate space (thresholds) once inference is configurable
- [x] CI workflow (optional): `.github/workflows/optimizer-plan-v2-phase0.yml` — `SKIP_LIVE=1` smoke (unittest + dry-run) on Ubuntu

### SkyDiscover as a multi-algorithm successor to `gepa_runner.py`

Vendored at [`skydiscover/`](skydiscover/) (moved in from `gpu-virt/skydiscover`,
Apache-2.0, own `.git`). SkyDiscover speaks the same `optimize_anything`
interface as our current GEPA wrapper but also exposes **AdaEvolve**, **EvoX**,
**OpenEvolve**, **Top-K**, **Beam**, and **Best-of-N** backends behind one CLI
(`uv run skydiscover-run … --search <algo>`). Same evaluator, swappable
algorithm — lets us A/B GEPA against AdaEvolve/EvoX on the same harness without
forking the eval pipeline.

- [ ] **Wrapper:** new `optimizer/skydiscover_runner.py` that wraps
      `optimizer/evaluate.py` as a SkyDiscover evaluator returning
      `{"combined_score": replay_success_rate, "artifacts": {…ASI…}}`.
      Artifacts should carry the replay-failure diagnostics already produced by
      `metrics.py` so SkyDiscover's reflection prompts see the same ASI the
      roadmap calls out in Component 6.
- [ ] **Candidate shape:** treat the candidate as a Python file that emits
      `handle_offsets.json` (or, later, the broader `spec.json` from
      `infer/classify.py`). Wrap the JSON inside EVOLVE-BLOCK markers so the
      surrounding I/O code is left alone.
- [ ] **Bake-off:** under identical iteration / token budgets, compare
      `--search gepa` (today's path) vs `--search adaevolve` vs `--search evox`
      on the `cu_init` → `matmul` ladder. Track replay success, offset
      agreement vs handwritten baseline, and tokens-to-first-improvement.
      Record in [VALIDATION.md](VALIDATION.md) alongside the existing GEPA
      results.
- [ ] **Blocker:** same GPU requirement as plan-v2 Phase 4+ — evaluator needs
      `/dev/nvidia*` for capture+replay. Wrapper + dry-run plumbing can be
      built and unit-tested without a GPU.

## Branch

- Implement and iterate on `coding-agent-dev` when doing multi-session work;
  merge to `main` after live validation.
