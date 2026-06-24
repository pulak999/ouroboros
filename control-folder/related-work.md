# Related Work — Ouroboros / gopher

**Purpose.** Seed of the paper's related-work section + a reading list. Organized
around the [pure RE / spec-synthesis thesis](plans/ouroboros-plan-v1.md): gopher
*recovers a machine-readable ioctl-ABI spec by black-box differential execution*.

The literature splits cleanly in two:
- **Part A — what gopher *is*:** active model learning, spec mining, protocol RE.
  This is the lineage a reviewer places you in; the *delta* lives here.
- **Part B — what gopher is built *with*:** self-evolving / evolutionary program
  discovery. Infra and context — know it cold (reviewers will ask "why not just
  AlphaEvolve?"), but the novelty is **not** here.

Each entry: link(s) + one line on *why you're reading it / what to check*.

> **Read-first priority**
> 1. **PROSPER** (A3) — closest scoop risk: LLMs + protocol spec extraction.
> 2. **de Ruiter & Poll, TLS state fuzzing** (A1) — the framing template for gopher.
> 3. **Automatic Protocol RE survey** (A2) — the classic lineage in one read.
> 4. **EvoEngineer** (B4) — closest scoop risk for the qr kernel instance.
> 5. **FunSearch** (B1) + **SkyDiscover** (B1, what you vendor) + **ADAS** (B2, cross-domain transfer claims).

> **Open scoop-checks (resolve before committing the thesis):** PROSPER,
> Automatic State Machine Inference (2412.02540), BinPRE — does any already do
> *LLM-guided spec synthesis for ioctl/driver ABIs with a replay oracle*? If no →
> the **ioctl-ABI domain + differential-replay oracle** is the wedge.

---

## Part A — What gopher *is*

### A1. Active model learning (the lineage gopher extends)
*Learn a black-box system's spec by querying it. gopher = replay-as-query.*
- **Angluin, L\*** — *Learning Regular Sets from Queries and Counterexamples* (1987) —
  [PDF](https://www.csa.iisc.ac.in/~deepakd/atc-2015/L_Star_Algo.pdf) ·
  [DOI](https://dl.acm.org/doi/10.1016/0890-5401%2887%2990052-6).
  The foundation: membership + equivalence queries. Short; read for the paradigm.
- **Vaandrager — *Model Learning*** (CACM 2017) — [doi.org/10.1145/2967606](https://doi.org/10.1145/2967606).
  The accessible survey of the whole field. Best single orientation read.
- **de Ruiter & Poll — *Protocol State Fuzzing of TLS Implementations*** (USENIX Sec 2015) —
  [USENIX](https://www.usenix.org/conference/usenixsecurity15/technical-sessions/presentation/de-ruiter) ·
  [PDF](https://pure-oai.bham.ac.uk/ws/files/21857312/usenix15.pdf).
  The closest *applied* analog: black-box state-machine learning of a real closed
  protocol stack, found real bugs. **The template for how to frame gopher.**
- **Ernst et al. — Daikon** (*Dynamically Discovering Likely Program Invariants*) —
  [TSE'01](https://homes.cs.washington.edu/~mernst/pubs/invariants-tse2001.pdf) ·
  [tool paper](https://homes.cs.washington.edu/~mernst/pubs/daikon-tool-scp2007.pdf).
  Spec/invariant mining from traces — the "memory as an accumulating spec" framing.

### A2. Automatic protocol / format RE (classic, taint-based)
*Your delta vs this cluster: black-box **differential** oracle instead of taint.*
- **Polyglot** (CCS'07) — [PDF](https://bitblaze.cs.berkeley.edu/papers/polyglot_ccs07_av.pdf) · [ACM](https://dl.acm.org/doi/10.1145/1315245.1315286). First dynamic-binary-analysis protocol format extraction.
- **Discoverer** (USENIX Sec'07) — [PDF](https://www.cs.purdue.edu/homes/xyzhang/fall07/Papers/discoverer.pdf). Formats from network traces (no parser instrumentation).
- **Tupni** (CCS'08) — [PDF](https://dl.acm.org/doi/pdf/10.1145/1455770.1455820). Fields, types, records, constraints from multiple inputs — the methodology your inference engine mirrors.
- **Prospex** (S&P'09) — [IEEE](https://ieeexplore.ieee.org/document/5207640/). Adds the protocol *state machine*, not just message format.
- **Survey** — *Automatic Protocol Reverse-Engineering* (2012, Song's group) — [PDF](https://people.eecs.berkeley.edu/~dawnsong/papers/2012%20Automatic%20Protocol%20Reverse%20Engineering.pdf). Read this instead of all four if short on time.

### A3. Modern / LLM-based protocol RE  ⚠️ SCOOP WATCH
- **PROSPER — Extracting Protocol Specifications Using LLMs** — [ACM](https://dl.acm.org/doi/10.1145/3626111.3628205). **Most direct scoop risk.** Check: ioctl/driver? replay oracle?
- **Automatic State Machine Inference for Binary Protocol RE** (2024) — [arXiv](https://arxiv.org/abs/2412.02540). Black-box state-machine recovery.
- **BinPRE — Field Inference in Binary-Analysis Protocol RE** (2024) — [arXiv](https://arxiv.org/abs/2409.01994). Overlaps your typed-field scoring (Workstream A2).
- **Database-assisted Automata Learning** (2024) — [arXiv](https://arxiv.org/abs/2406.07208). Memory + automata learning — overlaps the "memory box."

### A4. Static RE assistants (the *other* RE paradigm — assist a human reader)
- **reverser_ai** — [GitHub](https://github.com/mrphrazer/reverser_ai). LLM-on-decompiler-output. The contrast class: it never executes candidates against the live system. That's the gap gopher closes.

> **The gopher delta, one sentence (for the paper):** classical protocol RE
> taint-tracks the parser (impossible for a closed kernel driver) and classical
> model learning uses abstract membership/equivalence oracles; gopher replaces both
> with a **black-box differential-replay oracle** and **LLM-guided evolutionary
> hypothesis generation**, applied to the **ioctl/driver ABI** — a target neither
> lineage has covered.

---

## Part B — What gopher is built *with* (self-evolving discovery)

### B1. Program-evolution lineage (origin → frontier)
- **FunSearch** — *Mathematical discoveries from program search with LLMs* (Nature 2023) — [code](https://github.com/google-deepmind/funsearch) · [open-access](https://par.nsf.gov/biblio/10499230-mathematical-discoveries-from-program-search-large-language-models). The origin: LLM + evaluator + evolution over *programs*. Read first.
- **AlphaEvolve** (DeepMind 2025) — [blog](https://deepmind.google/blog/alphaevolve-a-gemini-powered-coding-agent-for-designing-advanced-algorithms/) · [white paper](https://storage.googleapis.com/deepmind-media/DeepMind.com/Blog/alphaevolve-a-gemini-powered-coding-agent-for-designing-advanced-algorithms/AlphaEvolve.pdf). The loop you redrew on the whiteboard.
- **ShinkaEvolve** (Sakana 2025) — [arXiv](https://arxiv.org/abs/2509.19349) · [code](https://github.com/SakanaAI/ShinkaEvolve). Sample-efficient + open — the one to fork. Read parent-sampling + novelty-rejection.
- **OpenEvolve** — [writeup](https://huggingface.co/blog/codelion/openevolve). Open AlphaEvolve reimplementation; a concrete codebase.
- **SkyDiscover** (Berkeley) — [site](https://skydiscover-ai.github.io/). **What you vendor.** Know its `ProgramDatabase`/archive model exactly — it's what you'd extend for cross-task memory.

### B2. Self-modifying / meta (evolve the agent or strategy itself)
- **Darwin Gödel Machine** (Sakana 2025) — [arXiv](https://arxiv.org/abs/2505.22954). Agent rewrites its own code against benchmarks.
- **ADAS — Automated Design of Agentic Systems** (Hu, Lu, Clune; ICLR 2025) — [arXiv](https://arxiv.org/abs/2408.08435) · [code](https://github.com/ShengranHu/ADAS). Meta Agent Search over a growing archive; **claims cross-domain/model transfer** — closest existing thing to the "cross-domain strategy transfer" idea, so read it to see what's already claimed.

### B3. Search/optimizer + memory layers
- **GEPA** — *Reflective Prompt Evolution Can Outperform RL* (2025) — [arXiv](https://arxiv.org/abs/2507.19457) · [DSPy](https://dspy.ai/api/optimizers/GEPA/overview/). Evolves text params via reflection on traces; composes inside the loop.
- **Voyager** (2023) — [arXiv](https://arxiv.org/abs/2305.16291). The skill-library/memory box, in full. Confirms the memory idea is largely solved here (single-domain).

### B4. Domain = kernels (the qr instance + the verifier lesson)  ⚠️ SCOOP WATCH for qr
- **The AI CUDA Engineer** (Sakana 2025) — [kernel archive (HF)](https://huggingface.co/datasets/SakanaAI/AI-CUDA-Engineer-Archive). The reward-hacking cautionary tale — read with the correctness criticism in mind.
- **Towards Robust Agentic CUDA Kernel Benchmarking, Verification, and Optimization** (2025) — [arXiv](https://arxiv.org/abs/2509.14279). The follow-up that hardens the *verifier* — directly the qr-side verifier point.
- **EvoEngineer** — *Automated CUDA Kernel Code Evolution with LLMs* (2025) — [arXiv](https://arxiv.org/abs/2510.03760). Closest direct prior art to the qr kernel evolver.

### B5. Adjacent — fully automated discovery (the extreme end)
- **The AI Scientist** v1 [arXiv](https://arxiv.org/abs/2408.06292) / **v2** [arXiv](https://arxiv.org/abs/2504.08066) (Sakana). The whole loop incl. paper-writing; v2 got a workshop paper accepted — relevant to your own workshop-paper question.

---

## Also to cite (downstream consumers — out of thesis; links TBD)
Virtualization systems the spec could *feed*, named in the plan's Tier 3. Not the
contribution; cite to say why they're orthogonal.
- **AvA** (OSDI'20) — spec-driven API virtualization, but the DSL is hand-authored (we *derive* the spec).
- **rCUDA**, **gVirtuS** — forward 1000+ documented API calls; we target the ~15-ioctl UAPI beneath.
- **geohot's `cuda_ioctl_sniffer`** (vendored) — manual sniffing, no synthesis.
