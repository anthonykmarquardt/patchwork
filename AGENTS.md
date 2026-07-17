# Patchwork Agent Bootstrap

> **Purpose:** Every agent entering this workspace reads this file first. It describes the vision, open questions, ongoing investigations, and standard operating procedures for the patchwork project.
> **Workspace:** `../patchwork/`
> **Theme:** Modular model composition — routing, latent bridging, and runtime composition of small dense models into a coherent inference ensemble.

> **⇒ Active workstream (2026-07): the routing pillar.** The "Routing" leg below is
> now a concrete architecture. Start at **`docs/routing-architecture.md`** (planes,
> taxonomy, certificate rungs, DAG, glossary), then the specs: **`specs/0001`**
> (router / data plane, draft), **`specs/0002`** (config tuner, scaffold),
> **`specs/0003`** (supervisory orchestrator, scaffold). Session handoff:
> **`CONTINUE.md`**.

---

## 0. The Core Insight

Current frontier inference is monolithic: one big model does everything. Patchwork inverts this — treat individual models as **expert components** in a modular MoE-like architecture, composed at inference time via:

- **Routing** — a lightweight classifier dispatches tokens to specialised modules
- **Latent bridging** ("telepathy") — learned projections pass compressed hidden states between modules
- **Memory tiering** — only active modules are resident in RAM; cold modules live on disk and swap in ~1 second at 4×7B scale on an NVMe
- **LoRA injection** — adapters plug into any module slot without reloading the base

**The target:** ~30B-equivalent capability at ~16 GB RAM, using 4× 7B or 2× 14B dense models at IQ4_XS, composed modularly rather than merged into a single weight matrix.

---

## 1. Master Questions (Open for Investigation)

These are the questions every agent should consider and update as research progresses:

### Model Selection
- Is Qwen2.5 the right family? What about Gemma-2, Llama-3.2, DeepSeek-V2-Lite?
- Do the models need to share the same tokenizer for latent bridging, or can a learned projection handle mismatch?
- What is the minimum viable module size? 7B? 3B? 1.5B?

### Routing
- Per-token routing vs. per-phrase vs. per-layer? What latency/quality trade-offs?
- What routing classifier architecture? Small transformer? Learned hash? N-gram LM?
- Is the router learned offline or adaptive online?

### Latent Bridge ("Telepathy")
- Does a simple linear projection between last-layer hidden states of model A and first-layer inputs of model B suffice?
- Does the bridge need attention, or is an MLP bottleneck enough?
- Can we use cross-attention between modules instead of sequential bridging?
- Is the bridge trained end-to-end on a small corpus, or post-hoc on cached representations?
- How does the bridge interact with KV-cache — does bridging invalidate cache?

### Memory Tiering
- Colibrì's streaming insight (experts on disk, LRU cache, RAM/VRAM/DRAM tier) — can we apply it at the *module* level instead of the *expert* level?
- How many modules can be resident at IQ4_XS in 16 GB? 4×7B? 2×14B?
- What is the cold-swap latency from a fast NVMe?

### Quantization Strategy
- IQ4_XS (from GGUF) is the baseline. Does bridge quality degrade at 4-bit?
- Can the bridge / router live at higher precision (8-bit) for better signal?

### Composition Patterns
- **Merge:** SLERP / TIES / DARE of same-arch models
- **Stripe:** Route tokens through alternating modules layer-by-layer
- **Stack:** Run module A's full forward pass, then pass its last hidden state to module B
- **Ensemble:** Run all modules in parallel, weighted vote on output
- **MoE-style:** Router dispatches per token to one or more modules
- **Adaptive:** Router decides the composition strategy per prompt

---

## 2. Directory Layout

```
patchwork/
├── AGENTS.md                         # This file — read first
├── MEMORY.md                         # Project state, known issues, decisions
├── CONTINUE.md                       # Session handoff (auto-updated)
├── docs/
│   ├── routing-architecture.md       # MASTER doc for the active routing workstream
│   └── references.md                 # External papers, projects, and tools
├── specs/
│   ├── 0001-tiered-cascade-router/   # data plane ("dark-core") — built v0 2026-07-16
│   ├── 0002-config-tuner/            # control plane (scaffold)
│   └── 0003-supervisory-orchestrator/# control plane (scaffold)
├── experiments/
│   ├── router/                       # spec 0001 harnesses + darkcore/ (the router itself)
│   │   ├── darkcore/                 # surface/prefilter/models/verifiers/cascade/router/cli/tui
│   │   ├── battery.jsonl             # labeled battery + probes
│   │   ├── closure.py, swap_econ.py  # Exp 1–3, Exp 4 harnesses
│   │   ├── darkcore_bench.py, verify.py, BENCH-REPORT.md
│   │   └── fixtures/
│   └── inference-bench/              # tier perf measurements
├── plans/
│   └── index.md                      # latent-bridge thread (paused)
└── research/
    └── README.md                     # research artifact index
```

---

## 3. Standard Agent Workflow

1. **Read this file** (`AGENTS.md`) — understand the current open questions
2. **Read** `MEMORY.md` — current state, decisions, known issues
3. **Read** `CONTINUE.md` — what the last agent was working on and where it stopped
4. **Read** the relevant plan document(s) under `plans/` for the topic you're investigating
5. **Check** the research directory for existing findings — don't duplicate work
6. **Begin work** — prefer reading existing artifacts before running experiments

### When adding findings:
- Add structured notes to the relevant `research/` document
- Update `MEMORY.md` with durable decisions or resolved questions
- Update `CONTINUE.md` at session end with current state and next steps
- Do NOT delete another agent's research — add yours as a new section or file

### When experimenting:
- Place prototypes in `experiments/` with a clear README
- Document: what you tested, what data you used, what the result was, and what it implies
- If an experiment disproves a hypothesis, say so clearly — that's as valuable as a positive result

---

## 4. Key Constraints

- **Target machine:** ~16 GB RAM, macOS (Apple Silicon M4 Max), fast NVMe SSD
- **No GPU requirement** — CPU-only inference is the baseline; GPU is a bonus
- **Quantization:** IQ4_XS baseline (via llama.cpp / MLX). Bridge quality at 4-bit is an open question.
- **No cloud dependencies** — everything runs locally
- **All models must be permissively licensed** — Qwen2.5 (Apache 2.0 / MIT), Gemma-2 (Gemma license), Llama-3.2 (Llama 3.2 Community License)

---

## 5. Cross-Profile Notes

This workspace is designed for multiple agents to work in parallel. Avoid conflicts by:
- Working in separate files or clearly marked sections
- Writing research findings, not personal notes, in `research/`
- Leaving `plans/` documents as living documents — add, don't replace
- Using `CONTINUE.md` as the session handoff, not `MEMORY.md`

---

## 6. Cross-References

- **Colibrì:** `JustVugg/colibri` — expert streaming from disk, tiered memory, the primary inspiration for the memory tiering approach
- **llama.cpp:** `ggml` — quantization kernels (IQ4_XS), GGUF format, our likely model loader
- **MergeKit:** model merging (SLERP, TIES, DARE) — the "merge" composition pattern
- **FrankenMoE / MoEfication:** converting dense models to MoE — related to expert-level routing
- **Sakana AI:** model merging research (evolutionary model merging, cross-tokenizer bridges)
