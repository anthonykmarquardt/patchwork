#!/usr/bin/env python3
"""MiniCPM5-1B-8bit standalone benchmark.

Measures what the existing inference-bench/ and battery framework capture:
  - Decode throughput (tok/s, TTFT) — like inference-bench #001–003
  - Answers for all 12 battery queries — like closure.py / darkcore_bench.py
  - Where MiniCPM5 sits vs the known T0/T1/T2 quality labels

Usage:  uv run python minicpm5_bench.py [--prompts battery.jsonl]
Output: minicpm5-results.json + bench-answers-minicpm5/*.txt
"""
import json, os, sys, time
import statistics

HERE = os.path.dirname(os.path.abspath(__file__))
BATTERY = os.path.join(HERE, "router", "battery.jsonl")
MODEL_ID = "mlx-community/MiniCPM5-1B-8bit"

# ── throughput benchmark ──────────────────────────────────────────────────────
THROUGHPUT_PROMPT = (
    "List the first 40 prime numbers, then briefly explain why 1 is not "
    "considered prime."
)

def stream_generate(model, tokenizer, prompt, max_tokens=256, temperature=0.0):
    """Single generation; returns timed result dict."""
    from mlx_lm import generate as mlx_generate, stream_generate as mlx_stream

    messages = [{"role": "user", "content": prompt}]
    if tokenizer.chat_template is not None:
        formatted = tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True)
    else:
        formatted = prompt

    t0 = time.perf_counter()
    ttft = None
    chunks = []
    n_tok = 0
    for resp in mlx_stream(model, tokenizer, formatted, max_tokens=max_tokens):
        if ttft is None:
            ttft = time.perf_counter() - t0
        chunks.append(resp.text)
        n_tok += 1
    t_end = time.perf_counter()
    text = "".join(chunks)
    wall = t_end - t0
    decode_s = t_end - t0 - ttft if ttft else 0.0
    tps = (n_tok - 1) / decode_s if decode_s > 0 and n_tok > 1 else float("nan")
    return {
        "text": text.strip(),
        "tokens": n_tok,
        "ttft_s": round(ttft, 4) if ttft else float("nan"),
        "wall_s": round(wall, 2),
        "decode_s": round(decode_s, 2),
        "decode_tps": round(tps, 1) if tps == tps else None,
    }


def throughput_bench(model, tokenizer, runs=3, warmup_tokens=8):
    """Warm up, then N measured passes, report median."""
    print(f"\n  warmup ({warmup_tokens} tokens) ...", flush=True)
    stream_generate(model, tokenizer, "hi", max_tokens=warmup_tokens)

    passes = []
    for i in range(runs):
        r = stream_generate(model, tokenizer, THROUGHPUT_PROMPT, max_tokens=256)
        passes.append(r)
        tps = r["decode_tps"] or 0
        print(f"  run {i+1}: ttft={r['ttft_s']:.3f}s  tokens={r['tokens']}  "
              f"wall={r['wall_s']:.1f}s  tps={tps:.1f}", flush=True)

    tpss = [p["decode_tps"] for p in passes if p["decode_tps"]]
    ttfts = [p["ttft_s"] for p in passes if str(p["ttft_s"]) != "nan"]
    return {
        "prompt": THROUGHPUT_PROMPT,
        "runs": runs,
        "decode_tps_median": round(statistics.median(tpss), 1) if tpss else None,
        "decode_tps_min": round(min(tpss), 1) if tpss else None,
        "decode_tps_max": round(max(tpss), 1) if tpss else None,
        "ttft_s_median": round(statistics.median(ttfts), 3) if ttfts else None,
        "passes": passes,
    }


# ── battery generation ────────────────────────────────────────────────────────
def generate_battery(model, tokenizer, battery_path, answer_dir):
    """Run all battery queries through MiniCPM5; return results."""
    os.makedirs(answer_dir, exist_ok=True)
    items = [json.loads(l) for l in open(battery_path) if l.strip()]
    results = []

    for item in items:
        qid = item["id"]
        query = item["query"]
        print(f"  [{qid}] {query[:60]}...", flush=True)
        r = stream_generate(model, tokenizer, query, max_tokens=1024)
        r["id"] = qid
        r["class"] = item.get("class")
        r["labels"] = item.get("labels")
        r["smallest_sat"] = item.get("smallest_sat")
        results.append(r)

        # save answer text
        with open(os.path.join(answer_dir, f"{qid}.txt"), "w") as f:
            f.write(f"# {qid} | class {item.get('class')} | "
                    f"tokens {r['tokens']} | wall {r['wall_s']}s\n"
                    f"--- QUERY ---\n{query}\n--- ANSWER ---\n{r['text']}\n")

    return results


# ── comparison vs existing Bonsai tier labels ─────────────────────────────────
def compare_labels(battery_results):
    """Compare MiniCPM5 answers against existing quality labels.

    Reports, for each labeled query, the existing T0/T1/T2 quality scores and
    which tier MiniCPM5's generation cost would correspond to (by token count
    as a proxy for latency).
    """
    rows = []
    for r in battery_results:
        if not r.get("labels"):
            continue
        lbl = r["labels"]
        sat = r.get("smallest_sat")
        rows.append({
            "id": r["id"],
            "class": r["class"],
            "minicpm5_tokens": r["tokens"],
            "minicpm5_wall_s": r["wall_s"],
            "minicpm5_tps": r["decode_tps"],
            "existing_labels": lbl,
            "existing_smallest_satisfying": sat,
        })
    return rows


def main():
    import argparse
    ap = argparse.ArgumentParser(description="MiniCPM5-1B-8bit benchmark")
    ap.add_argument("--prompts", default=BATTERY,
                    help=f"battery JSONL (default: {BATTERY})")
    ap.add_argument("--json", default="minicpm5-results.json",
                    help="output JSON path")
    ap.add_argument("--answer-dir", default="bench-answers-minicpm5")
    args = ap.parse_args()

    print("=== MiniCPM5-1B-8bit Benchmark ===", flush=True)
    print(f"Loading {MODEL_ID} ...", end=" ", flush=True)
    t0 = time.perf_counter()
    from mlx_lm import load
    model, tokenizer = load(MODEL_ID)
    load_s = round(time.perf_counter() - t0, 1)
    print(f"done ({load_s}s)", flush=True)

    # 1. Throughput
    print("\n── Throughput benchmark ──", flush=True)
    tp = throughput_bench(model, tokenizer, runs=3)

    # 2. Battery generation
    print(f"\n── Battery generation ({args.prompts}) ──", flush=True)
    battery_results = generate_battery(model, tokenizer, args.prompts, args.answer_dir)

    # 3. Comparison
    print(f"\n── Quality comparison against existing labels ──", flush=True)
    comparison = compare_labels(battery_results)
    for row in comparison:
        lbl_str = json.dumps(row["existing_labels"])
        print(f"  {row['id']} ({row['class']}): MiniCPM5 {row['minicpm5_tokens']}tok "
              f"in {row['minicpm5_wall_s']:.1f}s at {row['minicpm5_tps']}tps  "
              f"| existing labels {lbl_str}  | smallest_sat={row['existing_smallest_satisfying']}",
              flush=True)

    # Aggregate
    n_labeled = len(comparison)
    bw = [r for r in battery_results]
    total_tokens = sum(r["tokens"] for r in bw)
    total_wall = sum(r["wall_s"] for r in bw)

    # Compare to existing v0.2 bench (from BENCH-REPORT)
    report = {
        "model": MODEL_ID,
        "load_s": load_s,
        "throughput": tp,
        "battery": {
            "n_queries": len(battery_results),
            "n_labeled": n_labeled,
            "total_tokens": total_tokens,
            "total_wall_s": round(total_wall, 1),
            "mean_tokens_per_query": round(total_tokens / len(battery_results), 1),
            "mean_wall_s_per_query": round(total_wall / len(battery_results), 1),
        },
        "comparison": comparison,
        "existing_v02_bench": {
            "note": "dark-core v0.2 results for reference",
            "mean_quality_cascade": 0.900,
            "mean_quality_t2_only": 0.992,
            "speedup_vs_t2_only": 1.90,
            "pct_at_or_below_t1": 83.3,
            "class_detection": "12/12",
        },
        "notes": [
            "MiniCPM5 answers saved in bench-answers-minicpm5/",
            "Quality labels are subjective (n=1) from the original closure.py battery",
            "MiniCPM5 at 8-bit (1.07 GB) vs Bonsai 1.7B ternary (0.46 GB) — 2.3x the disk",
            "The bench did NOT run through the cascade — these are standalone generations",
        ],
    }

    with open(args.json, "w") as f:
        json.dump(report, f, indent=2)
    print(f"\n=== written {args.json} ===", flush=True)
    print(f"Answers in {args.answer_dir}/", flush=True)


if __name__ == "__main__":
    main()
