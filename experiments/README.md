# Experiments

Scratch space for prototypes, benchmarks, and throwaway code. Each experiment gets its own subdirectory with a README explaining what was tested and what was learned.

## Active experiments

- [inference-bench](inference-bench/) — reusable throughput/TTFT benchmark for
  OpenAI-compatible LLM servers (llama-server, mlx_lm, ollama, vLLM). Latest:
  result #003 (Ternary Bonsai 27B at 2-bit, ~9.55 tok/s / 7.86 GB on the M2).
- [router](router/) — empirical-closure harness for spec 0001 (the tiered cascade
  router): embedder/V2, per-class verifiers, and the λ sweep on the n=6 battery.

## Guidelines

- Each experiment directory has a README.md explaining the test, data, and conclusions
- Negative results are welcome and valuable
- Clean up large files (>100 MB) after documenting results
- If an experiment proves a hypothesis wrong, note it in the research directory and update `plans/index.md`
