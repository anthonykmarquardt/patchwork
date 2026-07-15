#!/usr/bin/env python3
"""inference-bench — throughput / TTFT benchmark for OpenAI-compatible LLM servers.

Measures the metrics patchwork cares about when sizing candidate modules and
comparing quant/runtime choices: time-to-first-token and steady-state decode
throughput (tokens/sec). Works against any OpenAI-compatible
``/v1/chat/completions`` endpoint — llama-server, mlx_lm.server, ollama
(``:11434/v1``), vLLM, etc.

Design notes (hard-won):
- **Count content AND thinking tokens.** Reasoning models stream their thinking
  under ``delta.reasoning`` or ``delta.reasoning_content``, not ``delta.content``.
  Miss those and a thinking model looks like it emits zero tokens.
- **Prefer server-reported token counts.** With ``stream_options.include_usage``
  the final chunk carries an authoritative ``completion_tokens``; fall back to
  counting streamed deltas only when the server omits usage (one delta ≈ one
  token for llama.cpp/mlx/ollama, but that's an assumption).
- **Warm up, then measure.** The first request pays model-load + graph-compile
  cost. Exclude it. Run N measured passes and report the median.
- **Benchmark backends SEQUENTIALLY**, never concurrently — two 9B models will
  not co-reside in 16 GB, and contention corrupts the numbers.
- Stdlib only (urllib) so it runs anywhere with no install.

Usage:
    # single endpoint
    python3 bench.py --base-url http://127.0.0.1:8081/v1 \
        --model mlx-community/Ornith-1.0-9B-4bit --label spark-mlx --runs 3

    # compare several (run one at a time; caller is responsible for only having
    # the one under test resident in memory)
    python3 bench.py --compare \
        "spark-mlx=http://127.0.0.1:8081/v1=mlx-community/Ornith-1.0-9B-4bit" \
        "ollama=http://127.0.0.1:11434/v1=ornith:9b" \
        --json results.json

Importable:
    from bench import benchmark
    r = benchmark("http://127.0.0.1:8081/v1", "model-id", runs=3)
    print(r["decode_tps_median"])
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
import urllib.request

DEFAULT_PROMPT = (
    "List the first 40 prime numbers, then briefly explain why 1 is not "
    "considered prime."
)


def stream_once(base_url: str, model: str, prompt: str, max_tokens: int,
                temperature: float = 0.0, timeout: float = 600.0) -> dict:
    """One streamed completion. Returns timing + token counts for this pass."""
    url = base_url.rstrip("/") + "/chat/completions"
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer local"},
    )
    t_send = time.perf_counter()
    t_first = None
    delta_count = 0
    usage_tokens = None
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        for raw in resp:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            try:
                obj = json.loads(data)
            except json.JSONDecodeError:
                continue
            usage = obj.get("usage")
            if usage and usage.get("completion_tokens") is not None:
                usage_tokens = usage["completion_tokens"]
            choices = obj.get("choices") or []
            if not choices:
                continue
            delta = choices[0].get("delta", {})
            piece = (delta.get("content") or delta.get("reasoning_content")
                     or delta.get("reasoning") or "")
            if piece:
                if t_first is None:
                    t_first = time.perf_counter()
                delta_count += 1
    t_end = time.perf_counter()
    tokens = usage_tokens if usage_tokens is not None else delta_count
    ttft = (t_first - t_send) if t_first else float("nan")
    decode_s = (t_end - t_first) if t_first else float("nan")
    # tokens-1: the first token's cost is TTFT, decode window covers the rest.
    tps = (tokens - 1) / decode_s if tokens and tokens > 1 and decode_s > 0 else float("nan")
    return {
        "ttft_s": ttft, "decode_s": decode_s, "wall_s": t_end - t_send,
        "tokens": tokens, "decode_tps": tps,
        "token_source": "usage" if usage_tokens is not None else "delta_count",
    }


def benchmark(base_url: str, model: str, *, prompt: str = DEFAULT_PROMPT,
              max_tokens: int = 256, runs: int = 3, warmup: bool = True,
              temperature: float = 0.0, label: str | None = None) -> dict:
    """Warm up (optional) then N measured passes; aggregate to medians."""
    label = label or model
    if warmup:
        try:
            stream_once(base_url, model, "hi", 8, temperature)
        except Exception as exc:  # a failed warmup shouldn't abort the run
            print(f"[{label}] warmup failed: {exc}", file=sys.stderr)
    passes = []
    for i in range(runs):
        r = stream_once(base_url, model, prompt, max_tokens, temperature)
        passes.append(r)
        print(f"[{label}] run{i+1}: ttft={r['ttft_s']:.2f}s "
              f"tokens={r['tokens']} decode={r['decode_s']:.2f}s "
              f"tps={r['decode_tps']:.1f} ({r['token_source']})")
    tpss = [p["decode_tps"] for p in passes if p["decode_tps"] == p["decode_tps"]]
    ttfts = [p["ttft_s"] for p in passes if p["ttft_s"] == p["ttft_s"]]
    return {
        "label": label, "base_url": base_url, "model": model,
        "runs": runs, "max_tokens": max_tokens, "prompt": prompt,
        "decode_tps_median": statistics.median(tpss) if tpss else float("nan"),
        "decode_tps_min": min(tpss) if tpss else float("nan"),
        "decode_tps_max": max(tpss) if tpss else float("nan"),
        "ttft_s_median": statistics.median(ttfts) if ttfts else float("nan"),
        "passes": passes,
    }


def print_comparison(results: list[dict]) -> None:
    w = max((len(r["label"]) for r in results), default=8)
    print(f"\n{'backend':<{w}}  {'decode tok/s (med)':>18}  {'range':>13}  {'ttft (med)':>11}")
    print("-" * (w + 48))
    best = max((r["decode_tps_median"] for r in results
                if r["decode_tps_median"] == r["decode_tps_median"]), default=None)
    for r in sorted(results, key=lambda x: -(x["decode_tps_median"]
                    if x["decode_tps_median"] == x["decode_tps_median"] else -1)):
        med = r["decode_tps_median"]
        star = "  *" if best and med == best else ""
        print(f"{r['label']:<{w}}  {med:>18.1f}  "
              f"{r['decode_tps_min']:>5.1f}-{r['decode_tps_max']:<5.1f}  "
              f"{r['ttft_s_median']:>10.2f}s{star}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base-url", help="OpenAI-compatible base, e.g. http://127.0.0.1:8081/v1")
    ap.add_argument("--model", help="model id the server expects")
    ap.add_argument("--label", help="name for this backend in output")
    ap.add_argument("--compare", nargs="+", metavar="label=base_url=model",
                    help="benchmark several backends (run them one at a time)")
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--max-tokens", type=int, default=256)
    ap.add_argument("--prompt", default=DEFAULT_PROMPT)
    ap.add_argument("--temperature", type=float, default=0.0)
    ap.add_argument("--no-warmup", action="store_true")
    ap.add_argument("--json", help="write full results to this path")
    args = ap.parse_args()

    specs = []
    if args.compare:
        for s in args.compare:
            label, base_url, model = s.split("=", 2)
            specs.append((label, base_url, model))
    elif args.base_url and args.model:
        specs.append((args.label or args.model, args.base_url, args.model))
    else:
        ap.error("provide --base-url and --model, or --compare")

    results = [benchmark(base_url, model, prompt=args.prompt,
                         max_tokens=args.max_tokens, runs=args.runs,
                         warmup=not args.no_warmup, temperature=args.temperature,
                         label=label)
               for label, base_url, model in specs]

    if len(results) > 1:
        print_comparison(results)
    if args.json:
        with open(args.json, "w") as fh:
            json.dump(results, fh, indent=2)
        print(f"\nwrote {args.json}")


if __name__ == "__main__":
    main()
