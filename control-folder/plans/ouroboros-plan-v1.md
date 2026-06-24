# Ouroboros — Plan v1

**Date:** 2026-06-23
**Author:** Pulak (with Claude)
**Status:** north-star plan. Supersedes the scattered *goal* statements in
`roadmap.md` (both appended versions), `plan-v1/2/3` and `newdirection.md`.
Those stay as **tactical references**; this doc is the thing you defend to a
professor and the thing every future plan-vN serves.

> Paths below are relative to the `ouroboros/` repo root (renamed 2026-06-23
> from `gpu-virt/gopher/`). "gopher" persists as the affectionate name for the
> RE engine inside it (`cuda-ioctl-map/`).

---

## 0. TL;DR

`gopher` (a.k.a. `ioctl-cuda-mapping`) is **already an instance of the
"ouroboros" self-improving coding loop** — generate → run on GPU → log →
analyze → score → evolve → remember. The loop, the sniffer, the replay engine,
the differential validator, a real scoring gate, and a GEPA/SkyDiscover search
backbone are **already built and partially working** (`cu_ctx_create` scored
0.89).

The blocker is not missing code. It is that the code is AI-generated and **not
yet owned** — you can't drive, defend, or sharpen what you don't understand.

**v1 is therefore: take ownership, consolidate, sharpen the two weak boxes, and
drive the loop to a hard, measurable milestone — without rewriting from
scratch.**

---

## 1. The Goal *(suggested — edit to taste; this is the one thing you must own)*

> **Thesis chosen (2026-06-23): pure RE / spec-synthesis.** The deliverable is
> the *specification*, not a virtualization layer. Replay/codegen/policy are
> downstream *consumers*, explicitly out of scope for the claim (see §8).

### North star
> **Ouroboros: a self-improving harness that recovers a complete,
> machine-readable specification of an undocumented kernel/driver ioctl ABI by
> *black-box differential execution* — diffing traces across mutated runs and
> confirming each field's semantics by *replaying against the live driver* —
> with zero hand-authored per-ioctl knowledge.**
>
> The `spec.json` is the artifact. **Replay fidelity is the oracle that measures
> it, not the product.** `gopher` (NVIDIA CUDA, driver 555) is the first ABI;
> the method is proven when a **second, unseen ABI** (ROCm/Gaudi, or just a new
> NVIDIA driver version) is recovered without touching the core inference engine.

### The research claim you defend to a professor / PhD
> *Execution-driven evolutionary RE* recovers a correct ioctl-ABI specification
> with **less human effort** and **better cross-version / cross-device
> generalization** than (a) the classic automatic-protocol-RE paradigm
> (Polyglot / Tupni / Discoverer / Prospex), which relies on *taint-tracking the
> parser*, and (b) hand-authored per-API specs/DSLs (AvA).

Why this is defensible and where the wedge is (detail in Appendix):
- **The paradigm is old; this application is open.** Automatic protocol RE
  (2007–2009) infers *network/file* formats by taint-analyzing the consuming
  parser. A literature check finds **no system that synthesizes a kernel ioctl
  ABI spec** this way. The kernel parser is closed-source and awkward to taint —
  so we replace taint with a **black-box differential oracle**: mutate inputs,
  diff traces, and *confirm* field roles by replaying against the real driver
  (Shift-and-Test). Different oracle, new domain.
- **Nobody runs an evolutionary loop over the inference strategy.** 2025
  evolutionary-coding systems (AlphaEvolve, ShinkaEvolve, SkyDiscover) optimize
  in domains with a cheap scalar reward (math, kernel speed, unit tests). Here
  the reward is a *behavioral trace diff against a live closed driver* — richer,
  messier, non-gameable — optimizing the *RE heuristics themselves*.
- **Static RE+LLM tools** (`reverser_ai`, GhidraMCP) assist a human *reader*;
  none close the loop by executing candidates against the driver. That gap is
  the contribution.

### First measurable milestone (v1 "done")
The loop, end-to-end and self-improving, drives the inferred spec for the
**`cuInit` ioctl ladder** to **replay parity with the handwritten baseline
(`0 failed`, no skip regression) using a typed `spec.json` with zero
hand-edited offsets** — beating the current GEPA seed — **AND you can explain
every box in §3 cold, from memory, at a whiteboard.** The second clause is not
optional; it is half the milestone.

### Definition of done for v1 (checklist)
- [ ] `spec.json` (typed: handle/pointer/fd/size/output) replays the cuInit
      ladder with 0 failures, no hand-edited offsets.
- [ ] One consolidated architecture doc (Workstream B) that you wrote.
- [ ] The evaluator scores on a **trace diff**, not just replay pass/fail
      (Workstream A).
- [ ] An explicit curriculum file with per-rung acceptance gates (Workstream C).
- [ ] You can defend the §1 claim and the §3 loop without notes.

---

## 2. Decision record — *"should I start from scratch?"* → **No.**

| Question | Finding |
|---|---|
| How much of it is *your* code? | ~2.3k lines Python + a few hundred C. The 172k figure is vendored (`open-gpu-kernel-modules`, `skydiscover`, `.venv`, `.pyc`). |
| Does the loop work at all? | Yes. Deterministic evaluator + scoring gate (`optimizer/evaluate.py`, `metrics.py`), GEPA reflection via local vLLM/Gemini (`gepa_runner.py`), a scored proposal on record. |
| Are the hard assets reusable? | Yes — sniffer, replay, differential validation, CI, multi-algorithm search backbone. Rebuilding ≈ months. |
| Is there direction? | Yes — a sophisticated roadmap and a prior-art-aware thesis already exist. |

**Decision:** keep the codebase; do **not** rewrite. Rewriting resets assets to
zero **and** re-incurs the identical "I don't understand my AI code" debt — it
solves nothing. The cure for un-owned AI code is an **audit + consolidation
pass** (Phase 0), not deletion.

**What we *do* retire:** documentation sprawl. `roadmap.md` has two full
roadmaps concatenated; there are 3 plan-vN + `newdirection.md` + many
`control-folder/*.md`. v1 collapses the *goal* into this file and Workstream B
into one owned architecture doc.

---

## 3. The whiteboard loop → what's already built

Your whiteboard, mapped onto the repo. **Built** = exists and runs;
**Weak** = exists but underpowered; **Gap** = not yet.

| Whiteboard box | In `gopher` | State |
|---|---|---|
| LLM1 + harness → *write code* | `gepa_runner.py` proposes `harness.yaml` / heuristics (not C — it evolves the *experiment + spec heuristics*) | **Built** |
| run code (ioctl on GPU) | `run.sh`: `nvcc` → `LD_PRELOAD` sniffer → replay | **Built** |
| log results (ioctl, **LD_PRELOAD**) | `intercept/nv_sniff.c` → `sniffed/*.jsonl` | **Built** |
| save results (**token-efficient — "how??"**) | `parse_trace.py` / `build_schema.py` → `spec.json` delta + ASI | **Weak** ← Workstream A |
| analyze results → **LLM2** | GEPA reflection model reads ASI | **Built** |
| score results (*did it do what we expected?*) | `metrics.py` `score_gate` + handle-offset agreement | **Weak** ← Workstream A |
| solution creator (GEPA / optimize_anything / **sky-discover**) | `gepa_runner.py` + vendored `skydiscover/` (AdaEvolve/EvoX/OpenEvolve/GEPA/Beam/Top-K) | **Built** |
| **memory [sol-list]** | SkyDiscover archive / GEPA Pareto frontier | **Weak/Gap** ← Workstream A |

**The punchline:** you re-derived your own system on a whiteboard. The two boxes
you starred (`how??` and the memory) are exactly the two **Weak** boxes. v1
focuses there.

> **Self-rule check (LD_PRELOAD):** your standing preference is *no LD_PRELOAD
> in the production transport* — still holds for the emitted stub/daemon. Here
> LD_PRELOAD is only the **offline tracer**. Keep that boundary; don't let it
> leak into the runtime.

---

## 4. Workstream A — the evaluator / fitness oracle *(the crux)*

In every evolutionary system the evaluator is the ceiling on difficulty. Ours
is currently "did replay print `0 failed`" + handle-offset agreement. That is a
**pass/fail proxy**, not a behavioral oracle. Sharpen it.

**A1 — Differential trace oracle (the `how??`).** Score a candidate by the
**diff between its trace and the golden trace**, not raw replay success.
Canonicalize each call to `(cmd_word, decoded_struct, ret, errno,
output_region_hash)`; dedup repeated sequences; surface **only deviations + the
first divergence point**. Feed *that* to LLM2 — never the raw JSONL firehose.
This is the token-efficient format and the richer reward in one move.

**A2 — Typed field scoring.** Extend `score_gate` from handle-only to the full
roadmap taxonomy (handle / pointer / fd / size / output / inline) with
per-field **confidence**. Pointer confirmation via the roadmap's **Shift-and-Test**
(rewrite suspected pointer with a dummy buffer; confirmed iff the driver writes
there). This is already designed in `roadmap.md` §2 — land it in `metrics.py`.

**A3 — Multi-objective + diversity-preserving memory.** Do **not** keep best-N
(premature convergence). Keep a Pareto frontier / MAP-Elites archive keyed by
*which ioctls each candidate correctly reproduces*, so partial solutions
compose (the object-alloc winner + the mmap winner → a better whole). SkyDiscover
already exposes this; wire the archive to spec **fragments**, not whole specs.

**A4 — Anti-reward-hacking.** The behavioral diff is hard to fake (a real
driver ack is real), but assert it: a candidate that "passes" by issuing *fewer*
ioctls than the golden trace must score **worse**, not better. Coverage is a
first-class objective.

**Acceptance gate:** evaluator returns a trace-diff score + typed-field score +
coverage, and a deliberately-truncated candidate scores lower than the golden
one.

---

## 5. Workstream B — the architecture doc *(consolidation = ownership)*

Deliverable: **one** `ARCHITECTURE.md` you author, that:
1. Draws the §3 loop and names the file behind every box.
2. States the offline-harness / online-runtime dichotomy (already in roadmap
   v2) in your words.
3. Marks Built / Weak / Gap honestly.
4. Links — and explicitly **demotes** — `roadmap.md`, `plan-v1/2/3`,
   `newdirection.md` to "historical / tactical."

How to *actually* take ownership (the anti-rewrite path), in order:
1. Run `/codebase-quizzer` on `cuda-ioctl-map/` — your own skill, built for
   exactly this. Target the optimizer + replay + intercept paths first.
2. Run `/ai-ledger` to audit and record what the AI wrote, file by file.
3. Re-derive the dataflow by hand (`run.sh` → `sniffed/*.jsonl` →
   `find_handle_offsets.py` → `replay.py` → `metrics.py`). Write it in
   `ARCHITECTURE.md` as you go. If you can't explain a file, that file is a v1
   risk — flag it.

**Acceptance gate:** the doc exists, is yours, and you can present §3 + §1 with
it closed.

---

## 6. Workstream C — the curriculum / corpus ladder

The roadmap's "CUDA ladder" exists latently in `programs/` but isn't a formal
curriculum. Formalize it — **do not try to one-shot `cuInit`.** Build the
protocol up rung by rung; the **diff between adjacent rungs attributes new
ioctls to new operations** (this *is* your "cuInit state-machine analysis").

Deliverable: `curriculum.yaml` — ordered rungs, each with a program, the new
ioctl(s) it should introduce, and an acceptance gate:

| Rung | Program | New surface | Gate |
|---|---|---|---|
| 0 | `card_info` | `NV_ESC_CARD_INFO` (cmd `0xC00846D6`, size-8 sentinel) | single ioctl replays |
| 1 | null-ctx | client/device object alloc | objects replay; handles map |
| 2 | one `cuMemAlloc` | memory object + mmap | alloc replays; pointer fields confirmed (Shift-and-Test) |
| 3 | one `cuMemcpyHtoD` | data-plane doorbell | copy replays |
| 4 | one kernel launch | command submission | launch replays |
| **N** | **full `cuInit`** | **whole ladder composed** | **v1 milestone (§1)** |

Start at rung 0 (`CARD_INFO`) because it's a single ioctl with a *known* cmd
word — the cheapest possible win that exercises the whole loop end to end.

**Acceptance gate:** the loop climbs the ladder; each rung's gate is enforced by
the Workstream-A evaluator; failures point at a specific rung.

---

## 7. Phasing

- **Phase 0 — Take ownership** *(do this first; blocks everything).* Workstream
  B steps 1–3. Output: `ARCHITECTURE.md` + a list of files you *can't* yet
  explain. ~1 week.
- **Phase 1 — Sharpen the oracle.** Workstream A1–A2 on the existing evaluator.
- **Phase 2 — Formalize the curriculum.** Workstream C; land rungs 0–1.
- **Phase 3 — Drive the loop.** Climb rungs 2→N; A3–A4 (archive + anti-hacking)
  as the search horizon grows. Hit the §1 milestone.
- **Phase 4 — Research evidence.** Generalization: train on NVIDIA, validate on
  a held-out program / second accelerator. This is the figure for the paper.

Phases 1–3 can reuse `/implement-from-plan` (you already drove plan-v2 that
way). Phase 0 cannot be delegated — it's the part where *you* learn the code.

---

## 8. Risks / what will bite

- **Eval is expensive & dangerous.** Candidate ioctls wedge the GPU/driver.
  Sample-efficiency is existential → this is *why* SkyDiscover/ShinkaEvolve over
  raw AlphaEvolve. Land the VFIO-VM snapshot/revert containment from roadmap v2
  before heavy fuzzing in Phase 3.
- **Scope sprawl (the recurring failure mode here).** The thesis is
  *spec-synthesis*, full stop. Codegen, the virtualization runtime, and the
  policy mediator are **downstream consumers — out of the thesis entirely**, not
  just post-v1; they demonstrate correctness at most, they are not the
  contribution. The **second ABI** is different: it is the *generalization
  evidence* for the spec-synthesis claim (Phase 4), so it is in-thesis but
  post-milestone. Resist the roadmap's gravity toward "build the vGPU."
- **Doc drift.** This file is the only goal doc. New plans serve it or amend it;
  they don't fork it.
- **The professor conversation needs a *claim*, not a *toolkit*.** Lead with §1's
  research claim and the prior-art gap, not the architecture.

---

## 9. Next actions (this week)

1. **You:** read §1, rewrite the goal in your own words if mine is wrong. This
   is the one thing you must own before the PhD chat.
2. **Phase 0 kickoff:** `/codebase-quizzer cuda-ioctl-map/` → then start
   `ARCHITECTURE.md`.
3. **Settled (2026-06-23):** thesis = **pure RE / spec-synthesis** (virtualization
   is out of scope). Before the PhD chat, skim the protocol-RE survey (Appendix)
   and be ready to state the **black-box-differential vs taint-based** delta —
   that is the first question you will get.

---

## Appendix — prior art (for the PhD conversation)

**Tier 1 — your real related work: automatic protocol/format RE.** This is the
lineage a reviewer places you in. Lead with it; do not let them think you missed it.
- **Polyglot** (Caballero, CCS'07), **Discoverer** (Cui, USENIX Sec'07),
  **Tupni** (Cui, CCS'08), **Prospex** (Comparetti, S&P'09), AutoFormat, ReFormat.
  Survey: *Automatic Protocol Reverse-Engineering: Message Format Extraction and
  Field Semantics Inference* (2012, Dawn Song's group). They infer message
  **formats/fields** from observing a program — almost all via **dynamic taint
  analysis of the parser**.
- **Your delta (state it crisply):** (1) *domain* — kernel **ioctl ABI**, not
  network/file formats; a literature check finds no spec-synthesis system here.
  (2) *oracle* — the kernel parser is closed-source, so instead of taint you use
  a **black-box differential oracle**: mutate, diff traces, and *confirm* field
  roles by **replaying against the live driver** (Shift-and-Test). (3) *outer
  loop* — an **evolutionary optimizer over the inference heuristics**, not a
  fixed pipeline. Daikon (dynamic invariant inference) is the adjacent
  trace-based-spec lineage.

**Tier 2 — the evolutionary-loop machinery (validates the method; not the
claim).** AlphaEvolve (DeepMind '25), **ShinkaEvolve** (Sakana '25,
sample-efficient — closest base to fork), OpenEvolve, **SkyDiscover** (Berkeley,
vendored here), Darwin Gödel Machine. Voyager ('23) = the memory/skill-library
box. GEPA (ICLR'26 oral) evolves *text params* and composes inside the loop.

**Tier 3 — virtualization (downstream consumers — NOT the thesis; know them so
you can say why they are orthogonal).** **AvA** = closest spec-driven virt, but
needs a hand-authored DSL per API; we *derive* the spec. rCUDA / gVirtuS forward
1000+ documented API calls; we target the ~15-ioctl UAPI beneath. geohot's
`cuda_ioctl_sniffer` (vendored) = manual sniffing, no synthesis. If asked "why
not just build the vGPU?" → it is a *consumer* of the spec; the spec is the
contribution.
