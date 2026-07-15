# inference-bench

A reusable throughput / TTFT benchmark for OpenAI-compatible LLM servers, plus
its first result (MLX vs ollama on the same 9B model).

## Why this is here

Patchwork's open questions — minimum viable module size, quant strategy, memory
tiering, cold-swap latency — all bottom out in *how fast does this module
actually decode on this host*. `bench.py` measures that consistently across any
runtime that speaks `/v1/chat/completions` (llama-server, mlx_lm.server, ollama,
vLLM), so candidate modules can be compared on equal footing.

## The tool

`bench.py` — stdlib only (urllib), no install. Measures **time-to-first-token**
and **steady-state decode throughput** by wall-clock over the streamed tokens.

```bash
# single endpoint
python3 bench.py --base-url http://127.0.0.1:8081/v1 \
    --model mlx-community/Ornith-1.0-9B-4bit --label spark-mlx --runs 3

# compare several (LAUNCH ONE AT A TIME — see caveats)
python3 bench.py --compare \
    "spark-mlx=http://127.0.0.1:8081/v1=mlx-community/Ornith-1.0-9B-4bit" \
    "ollama=http://127.0.0.1:11434/v1=ornith:9b" \
    --json results.json
```

Importable: `from bench import benchmark; benchmark(base_url, model, runs=3)`.

Design decisions that matter (each one bit us during the first run):

1. **Count thinking tokens.** Reasoning models stream their chain-of-thought
   under `delta.reasoning` / `delta.reasoning_content`, *not* `delta.content`.
   A naive parser sees zero output from a thinking model.
2. **Trust the server's token count.** With `stream_options.include_usage` the
   final chunk carries `completion_tokens`; the tool uses that and falls back to
   counting deltas only if absent. Counting streamed chunks **undercounts** —
   in the first run it read 208/212 "chunks" for a 256-token completion,
   inflating the apparent gap and understating both backends by ~20%.
3. **Warm up, then measure N passes, report the median.** The first request pays
   model-load + graph-compile.
4. **Benchmark sequentially.** Two 9B models will not co-reside in 16 GB. The
   tool does *not* enforce this — the caller must launch/stop each backend so
   only the one under test is resident.

## Result #001 — Ornith-1.0-9B, MLX vs ollama (2026-07-15)

Same model, same 4-bit class, same host, benchmarked sequentially (warm, 3 runs
each, `temperature=0`, 256-token cap, identical prompt).

| Backend | Runtime | Quant | Decode tok/s (median) | TTFT (warm) |
|---|---|---|---|---|
| **spark** | `mlx_lm.server` | 4-bit affine, g64 | **17.1** (16.9–17.1) | ~0.25 s |
| ollama | llama.cpp | Q4_K_M | 15.3 | ~0.32 s |

**MLX decodes ~12% faster.** Rock-stable across runs (deterministic at temp 0).

Caveats:
- **Not a controlled identical-weights test.** ollama's Q4_K_M is a mixed 4/6-bit
  k-quant (some tensors at 6-bit → higher fidelity, more compute/token); MLX is
  uniform 4-bit affine. Part of the gap is quant scheme, not engine. A stricter
  run would use ollama Q4_0 (uniform 4-bit) to isolate engine throughput.
- ollama applies its Modelfile system prompt; both TTFTs are low warm, and
  decode tok/s is unaffected by prompt length, so the throughput number is clean.
- Ornith is a reasoning model — most of the 256-token budget is thinking tokens
  (`reasoning`), which the tool counts. This is decode throughput, not
  useful-output rate.

### Implication for patchwork

On this hardware MLX has a real, repeatable decode edge over llama.cpp/ollama
for dense 4-bit models — a data point for the runtime choice, though it must be
weighed against llama.cpp's GGUF/IQ4_XS ecosystem, k-quant fidelity, and
streaming/tiering features that patchwork's memory-tiering plan leans on. Worth
re-running per candidate module size (0.5B / 1.7B / 3B / 7B) to see whether the
edge holds or narrows as models shrink.

**Host:** Apple M2, 16 GB (note: patchwork's target profile in AGENTS.md is an
M4 Max — re-baseline there before treating these absolute tok/s as the target
numbers; the *relative* MLX-vs-ollama gap should carry).
