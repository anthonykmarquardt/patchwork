# References — Spec 0001 tiered cascade router

## Primary (drives layer 2)

- **arXiv:2505.12601** — *Rethinking Predictive Modeling for LLM Routing: When
  Simple kNN Beats Complex Learned Routers* (2025).
  PDF: [`2505.12601-knn-beats-learned-routers.pdf`](2505.12601-knn-beats-learned-routers.pdf) · <https://arxiv.org/abs/2505.12601>
  - kNN over standard embeddings matches/beats MF, BERT, MLP, graph routers.
  - Locality (r ≈ −0.8) + low intrinsic dimension (~2–28) explain why.
  - Recipe: plain embedder (BERT-768 suffices), cosine, k≈100,
    `utility = mean_k quality − λ·mean_k cost`, argmax over tiers. No training;
    add a model by adding exemplars.

## Context / alternatives (not adopted, tracked)

- **arXiv:2506.16655** — *Arch-Router: Aligning LLM Routing with Human
  Preferences* — a 1.5B router model (`katanemo/Arch-Router-1.5B`, ~93% acc / 51 ms).
  Preference/domain routing, not difficulty; and a whole model to host — heavier
  than kNN for local tiering. <https://arxiv.org/abs/2506.16655>
- **RouteLLM** (lm-sys) — binary strong/weak framework; trained checkpoints on HF
  (`routellm/mf_gpt4_augmented`, `bert_…`, `causal_llm_…`). <https://github.com/lm-sys/RouteLLM>
- **vLLM Semantic Router** — production BERT-embedding router (HF `llm-semantic-router`).
- **arXiv:2603.04445** — *Dynamic Model Routing and Cascading for Efficient LLM
  Inference: A Survey* — situates the cascade (layer 3). <https://arxiv.org/pdf/2603.04445>
- **arXiv:2511.03808** — *Optimizing Reasoning Efficiency through Prompt Difficulty
  Prediction* — difficulty-predictor angle for the reasoning class.

## Internal provenance (the seed data)

- `spark/MODEL-EVAL-2026-07-15.md` — tier capability matrix + the confidently-wrong
  failure mode that motivates the cascade.
- `spark/spikes/human-emotion-eval-skill.md` — the R1/R2/A1/A2/E1/E2 battery whose
  per-tier pass/fail labels become the kNN exemplars.
