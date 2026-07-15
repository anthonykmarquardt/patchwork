# Patchwork — Master Planning Document

> **Status:** Early exploration. Open questions outnumber settled design decisions. This document is the central planning artifact — it lays out the design space, presents alternatives at every layer, and identifies where investigation is needed before a design can be locked in.
> **Intended audience:** Any agent entering this workspace. The goal is to bring a future agent up to speed and give it clear next steps to investigate.
> **Last updated:** 2026-07-14

---

## 0. The Vision

A **modular model runtime** that treats individual .GGUF models as pluggable expert components in a dynamically routed, memory-tiered ensemble. Think:

- Eurorack for LLMs — modules in, modules out, patch cables are learned projections
- Colibrì's memory tiering, but at the *module* level instead of the *expert* level
- A Lego set for language model composition

The machine this runs on: **Apple Silicon M4 Max, ~16 GB usable RAM, fast NVMe SSD.** No GPU requirement (Metal backend is a bonus).

---

## 1. Design Alternatives by Layer

Each layer has multiple plausible approaches. They're presented as alternatives — investigation should narrow them down, not necessarily pick one.

### 1.1 Model Family

**The leading candidate** is Qwen2.5, because:
- Multiple variants (base, coder, instruct) share identical architecture — merges are lossless
- Same tokenizer across all sizes — no bridge needed for shared vocabulary
- 7B at IQ4_XS is ~3.5-4 GB → 4 fit in 16 GB with room for cache
- 14B at IQ4_XS is ~7-8 GB → 2 fit comfortably
- The entire family (0.5B → 72B) is the same architecture — test at 1.5B, deploy at 7B

**Alternatives to evaluate:**

| Family | Architecture Uniformity | Tokenizer | 4-bit Density | Ecosystem |
|--------|----------------------|-----------|---------------|-----------|
| **Qwen2.5** | Perfect (all sizes same arch) | Shared | ~3.5 GB/7B | Excellent (mergekit, llama.cpp, MLX) |
| **Llama-3.2** | Good (3B and 11B differ slightly) | Different per size | ~2 GB/3B | Best ecosystem |
| **Gemma-2** | Poor (2B, 9B, 27B are different archs) | Shared across sizes | ~4.5 GB/9B | Moderate |
| **DeepSeek-V2-Lite** | Single model | Unique | ~8 GB/16B | Small ecosystem |

**Open questions for investigation:**
- How different are Qwen2.5-7B-base and Qwen2.5-7B-Coder's representation spaces? (Measurable via CKA / SVCCA on cached activations)
- Do Gemma-2's GeGLU and post-norm architecture make cross-model bridging harder?
- Is there a 3B model family that's worth considering for dedicated router / gate roles?

### 1.2 Composition Strategy (the "how")

This is the core architectural decision. There are several fundamentally different approaches:

#### A. Sequential Composition ("Stack")
```
Input → Module A → [latent bridge] → Module B → [latent bridge] → Module C → Output
```
- Each module runs its full forward pass on the token sequence
- A learned projection passes the last hidden state of module N to the embedding space of module N+1
- Pros: Simplest to implement, preserves full model capability at each step
- Cons: Sequential latency (N × forward pass), potential representation drift
- Bridge training: small (50K tokens) fine-tuning dataset, freeze both models, train only projection
- **Readiness:** Can be prototyped immediately with llama.cpp or MLX + a small Python bridge layer

#### B. Token-Level MoE Routing
```
Input → [Router] → dispatches each token to one of N modules → weighted combination → Output
```
- Each module processes only the tokens routed to it
- The router is a small learned classifier (or even a hash function over token IDs)
- Pros: True expert specialisation, parallelisable across modules, memory-efficient
- Cons: Complex implementation, router training needs labelled routing data, attention across routed tokens is tricky
- This is the closest analogue to colibrì's approach (experts = modules, router = router)
- **Readiness:** Requires building a custom inference engine. High complexity.

#### C. Layer-Level Interleaving ("Stripe")
```
Layer 1-16: Module A
Layer 17-32: Module B
Layer 33-48: Module C
```
- Models are split at layer boundaries. Module A handles early features, module B handles later reasoning, etc.
- Pros: Architecture-agnostic (any model with same hidden dim works), no bridging projection needed
- Cons: No dynamic routing, requires all models to have compatible hidden sizes
- This is effectively what "stacking" does at the model level
- **Readiness:** Straightforward with MergeKit or manual weight concatenation

#### D. Parallel Ensemble
```
Input → Module A ──┐
       → Module B ──┼→ [Weighted Vote / Mixture] → Output
       → Module C ──┘
```
- All modules run in parallel on the full input
- Output logits (or hidden states) are combined via learned weights, attention, or simple averaging
- Pros: Cheapest per-token inference, parallelisable
- Cons: N× compute per token (but parallel), no specialisation of attention
- **Readiness:** Prototype-ready with existing inference engines; just need a fusion layer

#### E. Adaptive Strategy Selection
```
Input → [Router detects task type] → selects composition strategy (A, B, C, or D)
```
- A meta-classifier decides which strategy to use per prompt
- Coding query → Stack: Code module → Writing module
- Math query → MoE routing
- Simple Q&A → Single module (fallback)
- Pros: Best of all worlds, resource-efficient
- Cons: Complex to build, router needs task-labelled data
- **Readiness:** Downstream of other strategies being built first

**Recommended investigation order:** A (Stack) → D (Ensemble) → B (MoE) → E (Adaptive). Stack is the fastest path to a working prototype and will reveal the most about latent bridge behaviour.

### 1.3 Latent Bridge Architecture ("Telepathy")

The bridge is the key technical novelty — a learned transformation that maps one model's hidden states into another model's input space.

#### Design Space

| Dimension | Alternative A | Alternative B | Alternative C |
|-----------|--------------|--------------|--------------|
| **Fidelity** | Linear projection (1 layer, no bias) | MLP bottleneck (2-3 layers, GeLU) | Cross-attention (Q from A, KV from B) |
| **Target** | Map to first-layer input space | Map to embedding space | Map to last-layer hidden space, then re-run decoder |
| **Training** | Post-hoc on cached (A,B) pairs | End-to-end on mixed dataset | Adversarial (bridge tries to match B's output from A's hidden) |
| **Quantization** | Bridge at FP16, freeze everything else | Bridge at FP16, LoRA-fine-tune module B | Bridge at IQ4_XS for speed |

#### Known techniques in this space:
- **GEMINI-style steering:** Linear probe trained on model A's last hidden to predict model B's next-token embedding. Feed result into model B's embedding layer.
- **Sakana's cross-tokenizer bridge:** Autoencoder that maps tokenizer-vocabulary representations between different tokenizers. Much more expensive but architecture-agnostic.
- **LM-merge / FrankenMoE:** Direct linear projection between intermediate layers of different models — requires matching hidden dimensions.
- **Trained adapters as bridge:** Instead of a separate bridge, fine-tune a LoRA that makes module B's first layer accept module A's output.

**Open questions:**
- Do Qwen2.5 base and instruct already share enough representation space that a simple linear projection suffices? (Hypothesis: yes — they share tokenizer, vocabulary, and most weights.)
- Does the bridge work token-by-token, or does it need span-level context?
- At 4-bit quantization, does the bridge's gradient signal survive? (Test: train bridge on FP16 models, evaluate on IQ4_XS models.)
- Can the bridge be merged into the target model's first layer at inference time (zero-cost bridge)?

### 1.4 Memory Tiering

Colibrì's key insight: **don't load what you're not using.** We apply the same principle at the module level.

#### Tier Design

| Tier | Contents | Size at IQ4_XS | Access Time |
|------|----------|----------------|-------------|
| **VRAM (if available)** | 1 active module + bridge | ~4 GB (7B) | ~0 |
| **RAM (hot)** | 2-3 active modules + router | ~12 GB | ~0 |
| **Disk (cold)** | All other modules (~10+ variants) | ~40 GB for 10 modules | ~1 second cold swap (NVMe) |
| **Download (archive)** | Models not currently installed | Cloud | N/A |

#### Design Questions
- **Preload vs. on-demand:** Preload the most common routing paths (usually 2-3 modules)? Or swap on every router decision?
- **Cache policy:** Colibrì-style LRU with learning cache? Or explicit routing predictions?
- **How many modules can coexist?** At ~4 GB each (7B IQ4_XS): 3 in 12 GB, leaving 4 GB for KV cache, bridge, and OS. Or 1 at 14B + 1 at 7B.
- **Cold-to-hot promotion:** If the router selects a module that's cold, can we overlap I/O with the current module's computation? (Starting inference in module A while loading module B from disk.)
- **KV cache invalidation on bridge switch:** If we switch the active module, does the KV cache for the old module survive? For how many tokens?

### 1.5 Router Architecture

If we pursue token-level MoE routing (Option B):

#### Router Options

| Type | Size | Training Data | Inference Cost |
|------|------|--------------|----------------|
| **Learned classifier** (transformer) | ~100M params | Labelled prompts → which module | ~5 ms / token |
| **N-gram / prefix hash** | <1 MB | Token-to-module mapping from task labels | ~0 ms |
| **Hidden-state probe** | ~10M params | Module-internal representations | ~2 ms / token (needs partial forward pass) |
| **Meta-LLM** (small model) | ~1.5B params | Full prompt → module assignment | ~50 ms / prompt (one-shot classification) |
| **Rule-based** | None | Regex / keyword patterns on prompt | ~0 ms, but fragile |

The meta-LLM approach is particularly interesting: a 1.5B Qwen2.5 model whose entire job is to look at the prompt and say "this is a code problem → use the code chain." At IQ4_XS, that's ~1 GB.

### 1.6 Quantization-Aware Design

All models at IQ4_XS (from llama.cpp / GGUF):
- 7B model: ~3.8 GB
- 14B model: ~7.5 GB
- 32B model: ~16.5 GB (doesn't fit with room for others)
- 1.5B model: ~0.9 GB

**Open questions:**
- Does the latent bridge work at IQ4_XS? Or does it need one model at FP16 to be the "anchor"?
- Can the router be higher precision (Q8_0) for better dispatch accuracy? A 100M-parameter router at Q8_0 is ~100 MB — negligible.
- Bridge quality at 4-bit: if a linear projection between two IQ4_XS models works as well as between two FP16 models, we have no precision tax.

---

## 2. Prioritised Investigation Plan

These are the concrete directions an agent can pick up and investigate. Each ends with a "verdict" — a clear next-agent action.

### Phase 0: Foundations (1-2 agent sessions)

**Investigation 0a:** Verify Qwen2.5 family compatibility
- Download Qwen2.5-1.5B (base, coder, instruct) at IQ4_XS
- Verify they load in llama.cpp / MLX
- Compare hidden state spaces (CKA / SVCCA) between base, coder, and instruct
- *Verdict:* "Qwen2.5 representations are close enough for linear bridging" or "they diverge too much"

**Investigation 0b:** Measure cold-swap latency
- Time how long it takes to load a Qwen2.5-7B GGUF from NVMe into RAM
- Compare: first load vs. second load (page cache)
- *Verdict:* "Cold swap is ~X seconds, preload is ~Y seconds" — sets the tiering design constraints

**Investigation 0c:** Survey existing cross-model inference frameworks
- Evaluate: llama.cpp embedding mode, MLX LoRA, MergeKit for stacking, Sakana evolutionary merging, FrankenMoE
- What already exists that we can use vs. what must we build?
- *Verdict:* "We can build on X, Y, Z" or "We need greenfield for reason A, B, C"

### Phase 1: Latent Bridge Prototype (2-3 agent sessions)

**Investigation 1a:** Implement linear bridge between two Qwen2.5-1.5B models
- Use llama.cpp in embedding mode to cache hidden states
- Train a linear layer (PyTorch) to predict model B's next hidden state from model A's last hidden state
- Evaluate on perplexity and generation quality vs. vanilla B
- *Verdict:* "Linear bridge at 1.5B achieves X% of B's quality" — determines if the concept works

**Investigation 1b:** Test bridge at IQ4_XS
- Repeat 1a with both models quantised to IQ4_XS
- Compare bridge loss and generation quality
- *Verdict:* "Quantisation costs Y% in bridge quality" — determines if we need higher-precision anchor

### Phase 2: Routing Prototype (2-3 agent sessions)

**Investigation 2a:** Build a simple token-level router
- Labelled prompt dataset (code, math, chat, creative, RAG) → module assignment
- Train a small classifier (bow + MLP, or a small transformer)
- Evaluate accuracy on held-out prompts
- *Verdict:* "Router achieves Z% accuracy" — determines if routing is viable at all

**Investigation 2b:** Evaluate routing overhead
- Measure inference latency with vs. without router
- Measure memory cost of keeping router loaded
- *Verdict:* "Routing adds W ms per token and M MB" — determines real-world viability

### Phase 3: Composition Strategies (3-4 agent sessions)

**Investigation 3a:** Build Stack prototype (full chain)
- Module A: Qwen2.5-7B-Coder
- Latent bridge (from Phase 1)
- Module B: Qwen2.5-7B-Instruct
- Evaluate on coding + explanation tasks
- *Verdict:* "Stack produces coherent N-step reasoning" or "Representation drift makes >2 modules unworkable"

**Investigation 3b:** Build Ensemble prototype (parallel vote)
- Run multiple models in parallel, combine outputs via learned weights
- Compare quality vs. Stack and vs. single model
- *Verdict:* "Ensemble beats single model by X% on Y benchmark" or "Not worth the cost"

### Phase 4: Runtime Design (2-3 agent sessions)

**Investigation 4a:** Runtime architecture proposal
- Based on findings from Phases 0-3, propose a concrete runtime architecture
- What component is the central dispatcher? How does memory tiering work?
- Where does each computation happen?
- *Verdict:* A design document for the runtime

**Investigation 4b:** Performance modelling
- Model the latency, memory, and throughput of the proposed runtime on this machine (M4 Max, 16 GB)
- Identify bottlenecks and mitigation strategies
- *Verdict:* "The design is viable at X tok/s" or "Redesign needed for reason Y"

---

## 3. Key Technical Risks

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Latent bridge doesn't preserve model quality | Medium | High (concept invalidated) | Prototype at 1.5B first; test quantisation impact early |
| 4×7B at IQ4_XS doesn't fit in 16 GB | Low | Medium | Use 2×7B + 1×14B configuration; or 2×7B |
| Cold-swap latency kills interactive use | Medium | High | Overlap I/O with computation; preload likely routes |
| Router accuracy too low for reliable dispatch | Medium | Medium | Fall back to single-model mode when uncertain; use meta-LLM approach |
| Cross-model KV cache management is intractable | Unknown | High | Build without KV reuse first; optimise later |
| No community model families support the composability patterns | Low | High | Qwen2.5 exists and is well-supported; the risk is hypothetical |

---

## 4. Related Work and Inspiration

| Project | Relevance | What We Take |
|---------|-----------|-------------|
| **Colibrì** (JustVugg/colibri) | Expert streaming, tiered memory | Memory hierarchy design, expert-on-disk approach, learning cache |
| **FrankenMoE** | Converting dense models to MoE | Expert-level routing concept, layer interleaving patterns |
| **Sakana evolutionary merging** | Cross-model representation bridges | Cross-tokenizer bridge techniques, model merging as composition |
| **MergeKit** | Model merging (SLERP, TIES, DARE) | "Merge" composition pattern, practical merging tools |
| **llama.cpp / MLX** | Local inference engines | Quantisation kernels (IQ4_XS), model loading, GGUF format |
| **Mixture of Adapters** (MoA) | Routing across adapters, not base models | Router architecture, per-token dispatch patterns |
| **DeepSpeed** (MoE) | Large-scale MoE training | Router implementation details, load balancing |
| **PPL (Stanford)** | Model composition as programming | Thinking about modules as composable compute units |

---

## 5. Agent Handoff Instructions

If you're an agent entering this workspace fresh:

1. Read this entire document
2. Read `AGENTS.md` for bootstrap procedures
3. Read `research/` directory to see what's already been investigated
4. Check `CONTINUE.md` for the last agent's state
5. Pick an investigation from Phase 0 that has a `[ ]` (unchecked) next to it below
6. Document your findings in the relevant `research/` file
7. Update `CONTINUE.md` and `plans/index.md` with your results

**Current Phase 0 status:**
- [ ] 0a: Verify Qwen2.5 family compatibility
- [ ] 0b: Measure cold-swap latency
- [ ] 0c: Survey existing cross-model inference frameworks
- [ ] 0d: Evaluate tokenizer compatibility across model families
- [ ] 0e: Measure representation similarity between Qwen2.5 variants (CKA)

**Current Phase 1 status:**
- [ ] 1a: Implement linear bridge between two Qwen2.5-1.5B models
- [ ] 1b: Test bridge at IQ4_XS

**Current Phase 2 status:**
- [ ] 2a: Build a simple token-level router
- [ ] 2b: Evaluate routing overhead

---

## 6. Design Decision Log

| # | Decision | Status | Date | Rationale |
|---|----------|--------|------|-----------|
| D001 | Model family: Qwen2.5 as primary candidate | Tentative | 2026-07-14 | Architecture uniformity, shared tokenizer, strong ecosystem |
| D002 | Quantisation baseline: IQ4_XS via GGUF | Tentative | 2026-07-14 | Best quality/ratio for available RAM; colibrì also uses int4 |
| D003 | Prototype path: Stack → Ensemble → MoE → Adaptive | Tentative | 2026-07-14 | Stack is fastest to working prototype; reveals bridge behaviour early |
| D004 | Bridge training: post-hoc on cached representations | Tentative | 2026-07-14 | Cheapest to experiment with; end-to-end is a refinement |

---

*This document is a living artefact. Every agent that enters should add findings, revise alternatives, and update the status of investigations. No single agent owns the design.*
