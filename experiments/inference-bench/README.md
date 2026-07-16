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

## Result #002 — DFlash speculative decoding on Ornith-9B (2026-07-15)

Does z-lab's DFlash draft model buy wall-clock speedup for Ornith on this host?
Ornith-1.0-9B is a hybrid linear-attention `qwen3_5` model; DFlash support lives
in **mlx-vlm 0.6.3** (bundled in the `mlx-lm` uv-tool env), which trims KV caches
while preserving the linear-attn `ArraysCache` during spec-verify (the `mlx_lm`
blocker — `bugs/spark-mlx-ornith-linear-attn-no-spec-decoding-001` — doesn't apply
there). The drafter must dim-match the target: `z-lab/Qwen3.5-9B-DFlash` (hidden
4096, bf16, 2.5 GB) pairs with Ornith; the 4B-DFlash (2560) does not.

This result supersedes a first pass taken in **macOS Low Power Mode** (which halves
GPU throughput — everything landed at ~7 tok/s and DFlash looked like a flat
1.08×). **Everything below is with Low Power Mode OFF, on AC power** (`pmset -g` →
`lowpowermode 0`), which is why plain 4-bit recovers to ~18 tok/s, back in line
with result #001's 17.1.

Full sweep — Ornith-9B, 256-tok, temp 0, median of 3 warm runs, benchmarked
sequentially (one model resident at a time), M2 / 17.2 GB:

| Target quant | Config | Weights (+drafter) | Decode tok/s | Accept | Verdict |
|---|---|---|---|---|---|
| **4-bit** | **plain** | ~5.2 GB | **18.2** (18.1–18.4) | — | **★ optimal on this host** |
| 4-bit | DFlash block=16 | ~7.7 GB | 17.1 (13.0–17.1) | 6.10 | 0.94× — net **loss** |
| 4-bit | DFlash block=8 | ~7.7 GB | 13.3 | 4.92 | 0.73× — worse (lower accept) |
| 6-bit | plain | ~8.2 GB | 13.5 | — | fits |
| 6-bit | DFlash block=16 | ~10.7 GB | **OOM** | (7 warmup) | crashes on real generation |
| 8-bit | plain | ~10.5 GB | 10.3 | — | fits |
| 8-bit | DFlash block=16 | ~13 GB | **OOM** | — | crashes on real generation |
| bf16 | (any) | ~18.8 GB | won't load | — | exceeds 17.2 GB |

### Why DFlash can't win here — a memory × precision trap

Spec-decoding pays off when single-token decode is **memory-bandwidth-bound**:
the block-verify reloads the target's weights once and amortizes them over ~N
accepted tokens. That regime is **high-precision targets**. But:

1. **4-bit decode is already bandwidth-light** — weights are half of 8-bit, so
   plain 4-bit is fast (18.2 tok/s) and there's little weight-reloading to
   amortize. Adding the drafter + block-verify is pure overhead → **0.94× (a
   loss)**, and worse TTFT. High accept length (6.10) doesn't help because the
   verify pass isn't the bottleneck. Two independent MLX-DFlash projects agree
   ("quantized targets reduce acceptance / 4-bit degrades performance"); their
   3.3–3.7× wins are all **bf16 / 8-bit** targets.
2. **The precision levels where DFlash *would* help don't fit.** 6-bit and 8-bit
   Ornith load fine *plain* (13.5 / 10.3 tok/s) but **OOM during real generation
   once the 2.5 GB bf16 drafter is added** (10.7 GB / 13 GB weights + KV + Metal
   working set on a 17.2 GB box → jetsam kill; the 8-token warmup survives, the
   256-token run dies). bf16 (18.8 GB) won't even load. The published 3.7×
   results used a **128 GB M4 Max** — no memory ceiling.

So on 16 GB-class hardware you're forced to 4-bit — the one regime where DFlash is
a net loss. `--draft-block-size` 16 beats 8 (higher accept; the drafter is trained
for 16), but no block size or KV knob changes the verdict, because the limiter is
target-weight bandwidth (4-bit) or unified memory (6/8-bit), not the drafter.

### Optimal settings (this host) & when to revisit

- **Serve Ornith as plain 4-bit, no drafter — 18.2 tok/s.** Backend `mlx_lm`
  (equivalent to plain `mlx_vlm`; `mlx_lm` has the leaner text path). Low Power
  Mode off.
- **DFlash becomes worth testing only with headroom for a high-precision target
  + the drafter** — i.e. ≳ 24 GB unified memory to run 8-bit Ornith (13 GB) or
  ≳ 32 GB for bf16 (21 GB) alongside the drafter. Re-run this sweep on the M4 Max
  target profile; the wiring is already in place.
- **Or wait for a quantized DFlash drafter** — a 4-/8-bit draft head would shrink
  the 2.5 GB tax enough to let a 6/8-bit target + drafter fit in 16 GB, which is
  the only way DFlash could win on this class of machine.

Reproduce: `scratchpad/sweep.sh` drives it (`sweep.sh out.jsonl 256 "label|repo|flags" …`);
`spark run ornith` serves the DFlash arm live. Spark wiring lives in
`~/.config/spark/config.toml` (runtime binary override) + the `ornith-1.0-9b-4bit`
registry entry (`launch_overrides`). **Host:** Apple M2, 17.2 GB.

## Result #003 — PrismML Ternary Bonsai 27B at 2-bit, MLX (2026-07-15)

Can an extreme-low-bit 27B decode on this 16 GB M2 at all — and how does it sit
against the 9B baselines? PrismML's **Ternary-Bonsai-27B** is Qwen3.6-27B moved to
ternary weights; the HF MLX repo ships them as **stock MLX affine 2-bit (g128)** —
`model_type qwen3_5` (same family as Ornith), so `mlx_lm` 0.31.3 loads it with no
fork and no custom kernel. (The "custom 2-bit hybrid-attention kernels" PrismML
advertises are only on the *GGUF/llama.cpp* path — a separate PrismML fork — not
this MLX build.) It's a `ForConditionalGeneration` VLM, but the lean `mlx_lm` text
path serves it fine; image input would route through mlx_vlm (untested).

Same harness as #001/#002: `bench.py`, 256-tok, temp 0, median of 3 warm runs,
served via `spark run ternary-bonsai-27b-mlx-2bit` (`mlx_lm.server` on :8081).

| Model | Params | Runtime | Quant | Weights on disk | Peak RSS | Decode tok/s | TTFT (warm) |
|---|---|---|---|---|---|---|---|
| **Bonsai** | **27.8B** | `mlx_lm.server` | MLX 2-bit affine g128 | 8.49 GB | **7.86 GB** | **9.55** (9.48–9.60) | ~0.35 s |
| Ornith (#002) | 9.0B | `mlx_lm` | 8-bit | ~10.5 GB | ~10.5 GB | 10.3 | — |
| Ornith (#002) | 9.0B | `mlx_lm` | 4-bit | ~5.2 GB | ~5.2 GB | 18.2 | ~0.25 s |

Rock-stable across runs (deterministic at temp 0). Raw `mlx_lm.generate` clocks
11.3 tok/s on a short prompt; the served/streamed number under the standard bench
(longer thinking prompt) is **9.55** — that's the comparable figure.

### The finding that matters for patchwork

**A 27.8B model fits the 16 GB box in 7.86 GB peak and decodes at ~9.5 tok/s —
right in the envelope of Ornith-9B at *8-bit* (10.5 GB, 10.3 tok/s).** Extreme-low-bit
buys you a **3× larger model at the same memory + throughput cost** as a mid-bit
9B. This is a direct, real data point for patchwork's north-star ("~30B-equivalent
capability at ~16 GB"): a single 2-bit 27B is one concrete way to hit that
envelope — the modular-composition alternative now has a monolithic baseline to
beat, on both quality (PrismML claims ~95% of FP16) and the tok/s above.

Caveats:
- **Not a quality measurement.** This is decode throughput on a thinking model;
  most of the 256-tok budget is chain-of-thought. Whether the 2-bit 27B actually
  out-reasons a 4-bit 9B is a separate eval, not run here.
- **Bandwidth, not the point of comparison to PrismML's numbers.** PrismML cites
  26 tok/s (M5 Pro) / 87 (M5 Max) for this build; 9.55 on an M2 is roughly the
  memory-bandwidth ratio. Re-baseline on the M4 Max target profile before treating
  9.55 as anything but this-host.
- **2-bit affine ≠ their "1.71 bits/weight."** The efficient ternary packing that
  hits 1.71 bpw lives in the GGUF/native path; the MLX repo spends a full 2 bits
  (hence 8.49 GB for 27.8B). A native-packed MLX build, if PrismML ships one, would
  shrink footprint further.

Reproduce: `spark run ternary-bonsai-27b-mlx-2bit` (registry entry
`~/.local/share/spark/models/ternary-bonsai-27b-mlx-2bit.toml`, backend `mlx_lm`),
then `python3 bench.py --base-url http://127.0.0.1:8081/v1 --model prism-ml/Ternary-Bonsai-27B-mlx-2bit --runs 3`.
**Host:** Apple M2, 16 GB.
