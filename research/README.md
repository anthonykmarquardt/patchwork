# Research Directory

> Structured findings from investigations. Each subdirectory or file is one investigation thread.

## Contents

| File | Topic | Status |
|------|-------|--------|
| `small-specialist-landscape.md` | Survey of sub-4B specialist models for composed architectures (SmolLM3 3B, Phi-4-mini, Qwen3.5-4B, tiny routers/drafters) | Complete |
| `latent-bridge-survey.md` | Cross-model latent communication techniques | Not started |
| `routing-literature.md` | Token routing approaches (MoE, MoA, etc.) | Not started |
| `memory-tiering-analysis.md` | Colibrì-inspired tiering at module level | Not started |
| `quant-impact.md` | Quantization-aware bridge quality | Not started |

## How to contribute

- Create a new file for each investigation thread
- Use this frontmatter format:

```
## Investigation: [Brief Title]
**Agent:** [profile name]
**Date:** YYYY-MM-DD
**Status:** in-progress | complete | inconclusive

### Hypothesis
What we expected to find.

### Method
What we did.

### Results
What we found. Include numbers, data, and failure modes.

### Implications
What this means for the design.
```

- Add negative results clearly. They save the next agent from repeating dead ends.
- After completing an investigation, update the status in `plans/index.md`.
