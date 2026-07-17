# External References

> **Scope.** The papers below are for the **latent-bridge / composition** thread.
> The **routing pillar**'s references live with their spec:
> `../specs/0001-tiered-cascade-router/references/` (incl. the kNN paper PDF) and
> `../docs/routing-architecture.md` §12. Key routing refs: arXiv:2505.12601
> (kNN ≥ learned routers), 2506.16655 (Arch-Router), 2603.04445 (routing/cascade
> survey), RouteLLM, FrugalGPT.

## Papers

### Cross-Model Representation Bridging
- **"LANGUAGE MODELS ARE HIDDEN ENCODERS"** — linear probes between model hidden spaces suggest representation spaces are aligned across models trained on similar data
- **"WHEN DO MODELS LEARN REPRESENTATIONS THAT SHARE A COMMON GEOMETRY?"** — CKA analysis across model families
- **Merge and then compress** — Sakana AI's approach to merging models with different tokenizers
- **"FrankenMoE: Converting Dense Models to Mixture-of-Experts"** — layer-level model interleaving

### MoE Routing
- **"Mixture of Adapters"** — routing across multiple fine-tuned adapters instead of full model experts
- **"Mixture of Experts Meets Instruction Tuning"** — routing learned via instruction following
- **"ST-MoE: Designing Stable and Transferable Sparse Expert Models"** — router load balancing techniques
- **"GLaM: Efficient Scaling of Language Models with Mixture-of-Experts"** — routing design from large-scale MoE

### Quantization and Model Quality
- **"AWQ: Activation-aware Weight Quantization"** — better quantization for downstream task quality
- **"QuIP#: Even Better LLM Quantization"** — theoretical framework for quantization-aware training
- **"The Impact of Quantization on Small Models"** — how far can you push 7B models?

### Memory Tiering
- **"MQSpatial: Scaling Memory with Disk for Large Model Inference"** — academic colibrì
- **"FlexGen: High-Throughput Generative Inference of Large Language Models with a Single GPU"** — offloading to CPU and disk
- **"Efficient Streaming Language Models with Attention Sinks"** — KV cache management for streaming

## Projects

- **Colibrì** (`JustVugg/colibri`) — expert-streaming MoE inference, zero-dependency C engine
- **llama.cpp** — GGUF format, IQ4_XS quantization, local inference
- **MLX** — Apple Silicon native ML framework
- **MergeKit** (`arcee-ai/mergekit`) — model merging toolkit
- **Sakana AI** (`SakanaAI/evolutionary-model-merge`) — evolutionary model merging
- **FrankenMoE** — converting dense transformers to Mixture-of-Experts
- **FlexGen** — offloaded inference
- **DeepSpeed MoE** — Microsoft's MoE training/inference framework

## Tools

- **GGUF format** — model container format designed for CPU inference
- **CKA (Centered Kernel Alignment)** — measuring representation similarity between models
- **SVCCA** — singular vector CCA for representation comparison
- **lm-eval-harness** — standardised evaluation benchmarks
