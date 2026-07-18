## Investigation: Small Specialist Models for Composed Architectures
**Agent:** penny
**Date:** 2026-07-17
**Status:** complete

### Hypothesis
The sub-4B model landscape has matured to the point where dedicated small specialists can serve as **workers, routers, drafters, and guardrails** in a modular composed architecture like Patchwork — potentially with higher reliability per-parameter than a monolithic mid-size model.

### Method
Survey of the current (mid-2026) open-weight model landscape in the 0.3B–4B range, with attention to:
- **Task specialisation:** Which models excel at agentic coding, math, tool use, instruction following, classification
- **Pragmatic fit:** Runtime availability (MLX, llama.cpp/GGUF), licensing, context length, quantised footprint
- **Architectural novelty:** Gated DeltaNet, NoPE hybrid attention, synthetic training data as a quality lever

### Results

---

#### Tier 1: 3–4B — The "real workers"

These models can generate substantive output and are the strongest candidates for composed-system worker nodes.

##### 1. SmolLM3 3B — the headline act

| Attribute | Detail |
|---|---|
| **Maker** | HuggingFace (HuggingFaceTB) |
| **License** | Apache 2.0 — fully open (weights + data + training code) |
| **Architecture** | Decoder-only transformer, GQA, NoPE (3:1 linear/attn ratio) |
| **Training** | 11.2T tokens, staged curriculum (web→code→math→reasoning) |
| **Context** | 64K native, 128K via YaRN extrapolation |
| **Post-training** | Midtraining on 140B reasoning tokens → SFT → APO alignment |
| **Thinking** | Extended thinking mode (on by default), toggled per-request |
| **Tool calling** | Native XML tool format + Python function-call format |
| **Runtimes** | Transformers ≥ 4.53.0, vLLM, SGLang |
| **Quantised size** | ~2 GB at Q4 |

**Benchmarks (Works With Agents — agentic coding benchmark, 32 models):**

| Rank | Model | Score |
|---|---|---|
| 1 | **SmolLM3 3B** | **93.3** |
| 2 | Phi-4-mini 3.8B | 90.0 |
| 3 | Claude Sonnet 4 | 85.0 |
| 4-5 | Qwen2.5 3B | 85.0 |
| 6 | Ministral 3B | 81.7 |

A 3B model beats Claude Sonnet 4 by 8 points on agentic coding. The benchmark tests multi-file edits, shell command execution, traceback recovery — precisely the agent-loop behaviour a modular architecture delegates to a worker. The hypothesis is that small models have "purer" instruction following because they lack the capacity to over-reason and hallucinate tool calls, a pattern that larger models exhibit.

**Relevance to Patchwork:**
- Ideal worker node for the composed ensemble — cheap enough to run multiple copies, reliable enough to trust with tool execution
- Native tool calling means it can self-orchestrate within its delegated scope
- Apache 2.0 + fully open weights + public training data = no licensing surprises

##### 2. Phi-4-mini 3.8B — the math specialist

| Attribute | Detail |
|---|---|
| **Maker** | Microsoft |
| **License** | MIT |
| **Architecture** | Dense transformer, GQA |
| **Context** | 128K tokens |
| **Training** | Synthetic math derivation data emphasis |
| **Thinking** | No built-in thinking — separate reasoning variant exists |
| **Quantised size** | ~2.5 GB at Q4_K_M |
| **Runtimes** | GGUF, MLX, Ollama, Transformers |

**Benchmarks (standard CoT, no extended thinking):**
- GSM8K: 88.6% (8-shot CoT)
- MATH: 64.0% (0-shot CoT)
- Works With Agents: 90.0

Phi-4-mini's strength is that its math scores are achieved *without* extended thinking — just standard chain-of-thought prompting. This means fast, reliable arithmetic and derivation for the same token budget that other models spend on preamble. Its synthetic training data produces unusually clean derivations that resist the pattern of "close but wrong" hallucination.

**Relevance to Patchwork:**
- Fast math / structured reasoning module in a composed system
- Good for verification passes — check another model's arithmetic
- MIT license means no restrictions on commercial composed deployment

##### 3. Qwen3.5-4B — the generalist lynchpin

| Attribute | Detail |
|---|---|
| **Maker** | Alibaba / Qwen Team |
| **License** | Apache 2.0 |
| **Architecture** | Gated DeltaNet hybrid (3:1 linear:full attention), 32 layers |
| **Context** | 262K native, 1M+ via YaRN |
| **Multimodal** | Text + image + video input |
| **Languages** | 201 |
| **Thinking** | Extended thinking on by default (toggled via `/no_think`) |
| **Quantised size** | 2.74 GB at Q4_K_M |
| **Runtimes** | Transformers, vLLM, SGLang, Ollama, GGUF, MLX |

**Benchmarks (thinking mode likely enabled):**

| Benchmark | Qwen3.5-4B | Notes |
|---|---|---|
| MMLU-Pro | 79.1 | |
| MMLU-Redux | 88.8 | |
| GPQA Diamond | 76.2 | With thinking — above GPT-4o's ~53% without |
| LiveCodeBench v6 | 55.8 | Code generation |
| HMMT Feb 25 | 74.0 | Competition math |
| IFEval | 89.8 | Instruction following |
| LongBench v2 | 50.0 | Long-context QA |

The Gated DeltaNet architecture is significant: three-quarters of the layers replace the growing KV cache with a fixed-size compressed state. At long contexts (100K+), this means predictable memory overhead instead of the linear blowup of dense attention. The remaining quarter uses full softmax attention for precise token retrieval.

**Relevance to Patchwork:**
- The best "single small model that does everything passably" — coordinator role in a composed system
- Hybrid attention is architecturally interesting for the composed runtime — fixed-size KV state eliminates a variable that complicates memory planning
- Multimodal input means it can examine screenshots, diagrams, etc. before routing to text-only specialists

---

#### Tier 2: 1–2B — Fast utilities (routers, drafters, classifiers)

These models are too small for reliable complex generation but excel at narrow, fast decisions.

**Routing classifiers (the SLM-router pattern):**
NVIDIA Research's "Small Language Models are the Future of Agentic AI" formalises heterogeneous model routing: a lightweight (~300M) classifier decides per-turn whether to call a cheap SLM or a heavyweight LLM. Inference overhead is 5–15 ms. The router can be a fine-tuned BERT variant or a small transformer trained on user-query × model-quality pairs. This is the *exact* architectural slot Patchwork needs for its per-token or per-turn routing layer.

**Key references:**
- `rahul-alhan/slm-router-agent` (GitHub) — reference implementation of the NVIDIA pattern
- Routing classifier survey: `jonathanding.github.io/llm-learning/en/articles/routing-classifiers/`

**Speculative drafting:**
Bonsai 27B's DSpark drafter is a 6-layer block-parallel transformer (~0.5B parameters, ~0.5 GB in low-bit) trained against the target model. It achieves 1.34× decode speedup on H100. The pattern is general: a tiny drafter can be trained against any target model via confidence-scheduled verification (lossless — verification preserves the target distribution exactly).

**Guardrail models:**
- ShieldGemma 2B — safety/harm classification, not generative; ~1.2 GB at Q4
- Could gate inputs to and outputs from larger or more expensive models in the ensemble

**Embedding models:**
- bge-micro / jina-embeddings v3 (~100–300M parameters, ~0.3 GB)
- Semantic routing keys and RAG retrieval for the memory/composition layer

---

#### Tier 3: <1B — Micro-utilities

- **Qwen3.5-0.8B** (~2 GB FP16, ~800 MB at Q4) — Gated DeltaNet hybrid, multilingual, could run as an always-on "keening listener" that decides when to wake a larger model
- **Tiny BERT classifiers (110M–330M)** — pure routing, intent classification, guardrails. ~400 MB at FP16, effectively free in context

---

### Cross-Cutting: The Ternary Compression Opportunity

Bonsai 27B's ternary compression (1.71 bpw, 95% intelligence retention, ~7 GB for a 27B) changes the size calculus for composed systems. The same technique could apply to any of the specialist models above — a ternary-compressed SmolLM3 3B would be ~0.7 GB instead of ~2 GB, making it feasible to keep 5–6 worker models resident.

However, ternary compression currently requires PrismML's custom kernels (forked MLX, forked llama.cpp). No off-the-shelf toolchain exists to apply it to arbitrary models. This is an active limitation.

---

### Implications for Patchwork

**The provocative resource budget (M4 Max, ~16 GB):**

| Component | Model | Size | Role |
|---|---|---|---|
| Slow thinker / coordinator | Qwen3.5-4B | 2.74 GB | Generalist, multimodal input router |
| Agentic worker (x2) | SmolLM3 3B | ~4 GB | Two parallel code/reasoning workers |
| Math verifier | Phi-4-mini 3.8B | 2.5 GB | Arithmetic guard, derivation checker |
| Big reasoning engine | Ternary Bonsai 27B | 7.05 GB | Heavy inference, final synthesis |
| Router (always resident) | Tiny classifier (~300M) | ~0.4 GB | Per-turn/ per-token dispatch decision |
| **Total** | | **~16.7 GB** | Tight but feasible with KV-cache compression |

All four generative models plus a router could be memory-tiered (active model swapped in per-token by the router's decision, cold models on NVMe swapping in ~1s as Colibrì-style streaming) — or, with ternary compression on the small models, all could fit resident.

**Key insight:** The Works With Agents benchmark suggests that small models (SmolLM3 3B at 93.3) may actually be *better* than large models at agentic coding tasks because they follow instructions more literally without generating distracting reasoning chains. This aligns with the Patchwork thesis that composed small models can outperform a single monolithic large model — the advantage is architectural, not just economic.

### Open Questions for Future Investigation

1. Would SmolLM3 3B's Works With Agents score hold up on Terminal-Bench 2.1 and SWE-Bench Verified under identical evaluation conditions?
2. Can the SLM-router pattern be adapted from per-call routing to per-token routing (the Patchwork architecture's core requirement)?
3. Does Phi-4-mini's synthetic-training robustness to hallucination generalise to other domains, or is it specific to mathematical derivation?
4. How do the Gated DeltaNet's fixed-size KV states interact with latent bridging between models — does the compressed state preserve enough information for cross-model steering?
5. Can the ternary compression technique be reproduced for 3B-scale models using publicly available tooling, or does it require PrismML's proprietary kernels?
