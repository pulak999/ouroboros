# ioctl-cuda-mapping — agent notes

## Overview

This repository captures ioctl traffic from CUDA programs to NVIDIA driver
devices (`/dev/nvidia*`), infers which buffer bytes are handles, and replays
captures without `libcuda.so`. See [README.md](README.md) for the user-facing
story and [roadmap.md](roadmap.md) for the longer-term trace-driven toolkit.

## Build and run

Primary working directory: `cuda-ioctl-map/`.

```bash
cd cuda-ioctl-map
bash run.sh programs/matmul.cu          # compile, capture, replay
bash run.sh -c programs/cu_init.cu      # capture only → sniffed/cu_init.jsonl
bash run.sh sniffed/matmul.jsonl        # replay only (needs privileges)
```

Sniffer build: `make -C intercept` produces `intercept/libnv_sniff.so`.

Replay typically requires **root** or `CAP_SYS_ADMIN` for `/dev/nvidia*`
opens.

## Optimizer harness (plan-v1)

- **Throwaway clone (shared login ok) + local Titan LLM:** see
  [AGENT_SERVER_SETUP.md](AGENT_SERVER_SETUP.md).
- Config: `cuda-ioctl-map/optimizer/harness.yaml`
- Evaluator: `python3 optimizer/evaluate.py` (from `cuda-ioctl-map/`)
- GEPA driver (optional): `python3 optimizer/gepa_runner.py`
- Python deps: `pip install -r optimizer/requirements.txt`
- **plan-v2 smoke:** `cd cuda-ioctl-map && SKIP_LIVE=1 ./optimizer/scripts/smoke_plan_v2.sh`
  (Phase 0 only). The same command runs in CI (`.github/workflows/optimizer-plan-v2-phase0.yml`)
  on pushes and PRs to `main` / `coding-agent-dev`. Full plan-v2 (live evaluate + optional local LLM + GEPA) is
  [plan-v2.md](plan-v2.md); results belong in [VALIDATION.md](VALIDATION.md).

**`smoke_plan_v2.sh` environment (see plan-v2 “Automation” table):**

| Variable | Role |
|----------|------|
| `SKIP_LIVE=1` | Unittest + dry-run + precondition hints only. |
| `OPT_PY` | Interpreter for unittest / `evaluate.py` (default `python3`). Use `optimizer/.venv/bin/python` if system Python lacks deps. |
| `OPT_VENV_PY` | Interpreter for `gepa_runner.py` (defaults to `.venv` if present). |
| `VLLM_API_BASE` | e.g. `http://127.0.0.1:8000/v1` — after live evaluate, curls `…/models`. |
| `GEPA_REFLECTION_MODEL` | e.g. `openai/<id>` — with `VLLM_API_BASE`, runs GEPA reflection. |
| `GEPA_MAX_METRIC_CALLS`, `GEPA_API_KEY` | Optional; see script. |
| `GEPA_USE_GEMINI` | Set to `1` to run Phase 3 with **Gemini** (LiteLLM `gemini/…`). Loads `GEMINI_API_KEY` from env or from `GEMINI_KEY_FILE` / default `gpu-virt/gemini-key.txt` (sibling of `ioctl-cuda-mapping`). |
| `GEMINI_KEY_FILE` | Optional path to a one-line Gemini API key file (never commit). |

## Conventions

- Shell entry point assumes current directory is `cuda-ioctl-map/`.
- JSONL one JSON object per line; ioctl `req` is a hex string.
- Handle patching uses 4-byte little-endian fields per `handle_offsets.json`.

## Effect-map tooling (`cuda-ioctl-map/tools/effectmap/`) — added 2026-07-30

Serves `control-folder/plans/effect-map-experiment-v1.md`. Needs **no root**
and no `libcuda`; it builds the RM object ladder by hand.

```bash
cd cuda-ioctl-map
SDK=../refs/open-gpu-kernel-modules/src/common/sdk/nvidia/inc

gcc -O2 -Wall -Wextra -o tools/effectmap/sweep_controls tools/effectmap/sweep_controls.c
/usr/local/cuda-12.5/bin/nvcc -arch=native -O0 -lcuda \
    -o tools/effectmap/effect_probe tools/effectmap/effect_probe.cu

# 1. command table from the SDK headers (sizes measured with a compiled probe)
python3 tools/effectmap/extract_ctrl_table.py --sdk $SDK \
        --out tools/effectmap/out/ctrl_table.json

# 2. probe the *shipped* driver: presence + true paramsSize for every command
python3 -c "..."   # see LOG.md for the one-liner that emits all_scan.txt
./tools/effectmap/sweep_controls --cmds all_scan.txt \
        --out tools/effectmap/out/abi_probe_all.jsonl --size-scan 65536

# 3. read-only command list, sized from the driver rather than the headers
python3 tools/effectmap/gen_sweep_list.py \
        --table tools/effectmap/out/ctrl_table.json \
        --probe tools/effectmap/out/abi_probe_all.jsonl \
        --out   tools/effectmap/out/sweep_cmds_555.txt
python3 tools/effectmap/gen_templates.py \
        --cmds tools/effectmap/out/sweep_cmds_555.txt \
        --out  tools/effectmap/out/sweep_cmds_555_tmpl.txt

# 4. A2 noise-floor gate, then A3/A4 effect map
./tools/effectmap/sweep_controls --cmds tools/effectmap/out/sweep_cmds_555_tmpl.txt \
        --out tools/effectmap/out/state_vector_run1.jsonl
./tools/effectmap/sweep_controls --cmds tools/effectmap/out/sweep_cmds_555_tmpl.txt \
        --out tools/effectmap/out/state_vector_run2.jsonl
python3 tools/effectmap/noise_floor.py \
        tools/effectmap/out/state_vector_run{1,2}.jsonl \
        --report tools/effectmap/out/noise_floor_report.json
python3 tools/effectmap/run_effect_map.py \
        --cmds  tools/effectmap/out/sweep_cmds_555_tmpl.txt \
        --noise tools/effectmap/out/noise_floor_report.json \
        --reps 5 --out tools/effectmap/out/effect_map.json

# 5. MIG classification report
python3 tools/effectmap/classify_mig.py \
        --table tools/effectmap/out/ctrl_table.json \
        --probe tools/effectmap/out/abi_probe_all.jsonl \
        --sniffed sniffed/ \
        --out-json tools/effectmap/out/mig_classification.json \
        --out-md   ../control-folder/plans/mig-command-classification.md
```

### Design decisions you must know before touching this

1. **Do not trust `lookup/ioctl_table.json` or `CUDA_IOCTL_MAP.md`.** Their
   escape-code names are wrong. `0xC020462A` is `NV_ESC_RM_CONTROL`, not
   `NV_ESC_RM_ALLOC`. Derive names from `nv_escape.h` with magic `'F'`.
2. **The vendored SDK is 610.43.02; hulk runs 555.42.02.** 12% of paramsSize
   values differ and 508 of 1675 commands do not exist in 555. Where the
   driver probe and the header disagree, the driver wins.
3. **Two oracles, both justified by `control.c:445-456`.** Presence uses a real
   object and an impossible size (`0x56` absent / `0x1F` present). Size uses a
   bogus `hObject` so the size check answers before object resolution
   (`0x57` = accepted size). The bogus-handle form never runs the handler, so
   it is safe on write commands.
4. **hulk is shared.** `gen_sweep_list.py` admits a command only if it is
   positively a read. Keep that filter conservative.
5. **A zeroed params buffer reads almost nothing.** Many GET controls are
   request-driven; use `gen_templates.py`.
6. **Snapshot while the operation is live.** `effect_probe` blocks on stdin so
   the sweep runs before the context is torn down.
