# Experiments

Scratch space for prototypes, benchmarks, and throwaway code. Each experiment gets its own subdirectory with a README explaining what was tested and what was learned.

## Active experiments

- [inference-bench](inference-bench/) — reusable throughput/TTFT benchmark for
  OpenAI-compatible LLM servers (llama-server, mlx_lm, ollama, vLLM). Result
  #001: MLX decodes Ornith-9B ~12% faster than ollama on the M2.

## Guidelines

- Each experiment directory has a README.md explaining the test, data, and conclusions
- Negative results are welcome and valuable
- Clean up large files (>100 MB) after documenting results
- If an experiment proves a hypothesis wrong, note it in the research directory and update `plans/index.md`
