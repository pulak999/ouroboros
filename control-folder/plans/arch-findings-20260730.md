# Ouroboros architecture findings — 2026-07-30

**Status:** ongoing. This file accumulates concrete, source-grounded findings
about `cuda-ioctl-map/`'s current implementation, found while building the
effect-map experiment. Not a redesign — a punch list against the existing
Workstream A gaps in `ouroboros-plan-v1.md` §4, with exact evidence.

Per plan-v1 §5, this serves the one owned `ARCHITECTURE.md` — it does not fork
it. Promote entries here into that doc once it exists.

---

## Finding 1 — the sniffer cannot see the payload of the command that matters most

**Severity: blocks reuse of `nv_sniff.c` for the effect-map's Layer 1, and
probably undercounts every existing trace's information content.**

`intercept/nv_sniff.c:218-249` snapshots `before_buf`/`after_buf` around the
raw `ioctl()` syscall argument, sized by `_NV_IOC_SIZE(request)`:

```c
size_t sz = _NV_IOC_SIZE(request);
...
if (arg) memcpy(before_buf, arg, sz);
...
int ret = real_ioctl(fd, request, arg);
...
if (arg) memcpy(after_buf, arg, sz);
```
[nv_sniff.c:219-249](ouroboros/cuda-ioctl-map/intercept/nv_sniff.c#L219)

For `NV_ESC_RM_CONTROL` (the ioctl behind essentially every interesting CUDA
and MIG operation — see `mig-command-classification.md`), the syscall
argument is `NVOS54_PARAMETERS`:

```c
typedef struct {
    NvHandle hClient;
    NvHandle hObject;
    NvV32    cmd;
    NvU32    flags;
    NvP64    params NV_ALIGN_BYTES(8);   // <- a POINTER, not the payload
    NvU32    paramsSize;
    NvV32    status;
} NVOS54_PARAMETERS;
```
[nvos.h:2216-2225](open-gpu-kernel-modules/src/common/sdk/nvidia/inc/nvos.h#L2216)

`before_buf`/`after_buf` capture this **40-ish byte envelope only**. The
`params` field is a pointer *value* — the driver reads and writes through it,
but the pointer itself doesn't change, so the sniffer's own before/after diff
on that field is always empty. The actual command-specific payload (the
struct the driver reads `cmd`-specific fields from — `swizzId`, `memorySize`,
`smcMode`, whatever `GET_PARTITIONS`/`SET_PARTITIONS`/every other MIG command
carries) lives in a **separate user-space allocation the sniffer never
touches**.

**Concretely: every trace already captured by this repo has `before`/`after`
hex for RM_CONTROL calls that will diff to "nothing changed but `status`,"
regardless of what the call actually did.** The interesting signal was never
recorded.

**Why this matters right now:** it directly blocks Experiment A1/A3 from the
effect-map plan (`effect-map-experiment-v1.md`) if they try to build on the
existing sniffer output. A1 as scoped is a standalone tool (owns its own
buffers, doesn't need the sniffer) — unaffected. But A3's CUDA-corpus rows
(`cuMemAlloc`, `cuLaunchKernel`, etc., run through the *existing* `run.sh` /
`nv_sniff.c` pipeline) will not carry usable state deltas until this is fixed.

**Fix, scoped:** in the `ioctl()` interposer, special-case `request ==
NV_ESC_RM_CONTROL` (and `NV_ESC_RM_ALLOC`, same shape — `params` pointer +
separate payload): after `memcpy`-ing the fixed envelope, read `paramsSize`
from it, then `memcpy` an *additional* `paramsSize` bytes from the pointer
target, before and after the real ioctl call, and emit them as a third hex
field (`"params_before"`/`"params_after"`) in the JSONL record. This is a
~20-line addition, no new dependencies, same LD_PRELOAD boundary. It should be
done once, centrally, rather than re-solved per-experiment.

**Do this before A3, not after.** Building A3's corpus runner on the current
sniffer and discovering this later means re-running the whole corpus.

**Addendum — why this hasn't broken anything yet, and exactly where it will.**
Checked `replay/replay.c:440-522`: replay reconstructs its working buffer
*only* from the JSONL's captured `before`/`after` hex
([replay.c:442-461](ouroboros/cuda-ioctl-map/replay/replay.c#L442)) — it never dereferences a `params`
pointer either. Both capture and replay have the identical blind spot, which
is why it's invisible today: they're symmetric.

The reason plan-v1's rung-0/1 results ("`cu_ctx_create` scored 0.89") aren't
contradicted by this finding is an escape-code split, confirmed directly in
the open driver:

| Escape code | Value | Payload shape | Affected? |
|---|---|---|---|
| `NV_ESC_CARD_INFO` | legacy | `nv_ioctl_card_info_t` — flat struct, **no pointer field**, passed by value ([nv-ioctl.h:54-66](open-gpu-kernel-modules/src/nvidia/arch/nvalloc/unix/include/nv-ioctl.h#L54)) | No — direct capture/replay works |
| `NV_ESC_RM_CONTROL` | `0x2A` | `NVOS54_PARAMETERS` — pointer-indirected | **Yes** |
| `NV_ESC_RM_ALLOC` | `0x2B` | `NVOS21_PARAMETERS`/`NVOS64_PARAMETERS` — same shape | **Yes** |

([nv_escape.h:30-31](open-gpu-kernel-modules/src/nvidia/arch/nvalloc/unix/include/nv_escape.h#L30))

So the gap is real but has a clean boundary: it doesn't touch what's already
validated (rung 0, legacy fixed-struct escapes), and it exactly covers what's
next (rung 1+ object allocation, `cuMemAlloc`, everything MIG). This sharpens
the fix's urgency rather than lowering it — the curriculum's very next rung
walks straight into it.

---

## Finding 2 — the search loop optimizes a much narrower space than plan-v1 describes

**Severity: expectation-setting, not a bug. Matters for anyone reading
plan-v1 §3's whiteboard table and assuming more is wired up than is.**

Plan-v1 §3 describes the LLM1/harness box as: *"proposes `harness.yaml` /
heuristics (not C — it evolves the experiment + spec heuristics)."* The actual
code:

```python
ap.add_argument(
    "--objective",
    default=(
        "Improve the YAML harness for CUDA ioctl capture/replay evaluation: "
        "choose programs from the ladder that maximize aggregate_score while "
        "keeping lists short and realistic. Output only valid YAML."
    ),
)
```
[gepa_runner.py:44-51](ouroboros/cuda-ioctl-map/optimizer/gepa_runner.py#L44)

The candidate GEPA mutates is literally the text of `harness.yaml` — the
**list of which programs to run**, nothing about handle-offset inference
heuristics, spec structure, or ioctl sequences. `evaluator()`
([gepa_runner.py:101](ouroboros/cuda-ioctl-map/optimizer/gepa_runner.py#L101)) writes the candidate text to a
tempfile, calls `evaluate_harness`, and returns `aggregate_score` — a single
float, no structured feedback beyond whatever the reflection model reads from
stdout.

This is a legitimate GEPA use (curriculum selection), but it is a much
smaller search problem than "spec heuristics" suggests, and it explains why
plan-v1 §3 marks "memory [sol-list]" as **Weak/Gap**: there is no archive
here to be weak — there's a single `best_candidate` returned at the end
([gepa_runner.py:147-149](ouroboros/cuda-ioctl-map/optimizer/gepa_runner.py#L147)), no Pareto frontier, no MAP-Elites keying by
"which ioctls this candidate gets right" (plan-v1 §4 A3's ask).

**Relevant to the inverse-search proposal (Phase 2, from the effect-map
conversation):** if that direction gets built — *given a target state delta,
synthesize the ioctl sequence* — it needs an actual structured action space
(sequences of `(cmd, params)`) and an archive keyed on partial state-field
matches. Neither exists today. This is not a criticism of what's there; it's
a scoping note so Phase 2 isn't assumed to be "just point GEPA at it" — the
harness-YAML-mutation harness and an ioctl-sequence-synthesis harness are
different `evaluator()` functions with different candidate representations,
and the current `gepa_runner.py` would need a new evaluator, not a new
objective string.

---

## Finding 3 — the oracle is exactly as narrow as plan-v1 says, confirmed with the exact gate logic

**Severity: confirms plan-v1 §4 A1/A2; no new gap, but pins down precisely
what "Weak" means in code, which matters for anyone patching `score_gate`.**

`optimizer/metrics.py:138-153`, `score_gate()`:

```python
def score_gate(*, candidate_summary, baseline_summary,
                require_zero_failed=True, max_skip_regression=0):
    if candidate_summary is None:
        return False, "could_not_parse_candidate_replay_summary"
    if require_zero_failed and candidate_summary.failed > 0:
        return False, "candidate_replay_has_failures"
    ...
    return True, "ok"
```

And the reward actually used in `evaluate_harness`
([evaluate.py:262-270](ouroboros/cuda-ioctl-map/optimizer/evaluate.py#L262)):

```python
if not gate_ok or c_sum is None or (c_sum.failed > 0):
    row_score = -1.0
else:
    row_score = float(diff.get("handle_offset_agreement_ratio", 0.0))
    if c_sum.skipped > 0:
        row_score *= 0.85
```

So the entire reward signal is: (a) a pass/fail gate on `replay.py`'s printed
`DONE — N/M succeeded, F failed, S skipped` line, parsed by regex
([metrics.py:15-18](ouroboros/cuda-ioctl-map/optimizer/metrics.py#L15)), and (b) **handle-offset list
equality**, order-insensitive, all-or-nothing per request
(`compare_handle_offsets`, [metrics.py:54-112](ouroboros/cuda-ioctl-map/optimizer/metrics.py#L54)). There is no
trace-diff (plan-v1 §4 A1), no typed field taxonomy beyond "handle offset"
(§4 A2 — pointer/fd/size/output/inline all unscored), no Shift-and-Test
confirmation despite the roadmap designing it, and — confirming Finding 1 —
even if A2 landed today, it would have nothing but the RM_CONTROL envelope to
score against for most calls.

**This is the concrete reason A5 (wiring the effect map in as the fitness
oracle, per the earlier conversation) is worth doing regardless of whether
Layer 2 or MIG hardware ever arrive:** `score_gate` currently cannot
distinguish "candidate issued the right ioctls with the wrong config values"
from "candidate issued the right ioctls with the right config values," because
it never looks at config values at all — only handle offsets and a pass/fail
count. A candidate that reproduces the ioctl sequence exactly but flips one
field currently scores identically to one that gets it exactly right, as long
as replay doesn't error out. That's the truncation/reward-hacking gap plan-v1
§4 A4 already worried about, just instantiated concretely.

---

## Open items (not yet investigated — flagging for the next pass)

- `find_handle_offsets.py` (the inference step between two captures) has not
  been read this pass. Worth checking whether it does anything more than
  byte-position diffing between two runs — if it's pure diff-based inference,
  it inherits Finding 1's blindness for any offset that lives inside the
  RM_CONTROL payload rather than the envelope.
- `replay.c`/`replay.py` round-trip fidelity (does replay reconstruct the
  `params` pointer target correctly, or only the envelope?) — same pointer
  concern as Finding 1, opposite direction. Not yet checked.
- Whether `parse_trace.py` / `build_schema.py` (plan-v1's "how??" box) already
  have any handling for pointer-indirected ioctls that `nv_sniff.c` itself
  doesn't capture — i.e., is there a downstream component that's already
  compensating for Finding 1, making it lower-severity than stated above.
  Check before starting the Finding-1 fix, in case it's partially redundant.
