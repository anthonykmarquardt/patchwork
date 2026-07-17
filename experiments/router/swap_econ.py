#!/usr/bin/env python3
"""Spec 0001 — model-swap economics bench (the cascade's falsification test).

On a 16 GB box only ~one model is resident; escalation = LOADING a model.
This measures what the Exp-3 cost model ignored:

  * per-tier load latency (cold-ish round 1 vs page-cache-warm round 2)
  * TTFT after a fresh load, decode tok/s, Metal peak memory + process RSS
  * unload cost (del + clear_cache)
  * T0+T1 co-residency feasibility (both loaded, generate on each)

Emits incremental JSONL (survives an OOM-killed T2) to:
  experiments/router/swap-econ.results.jsonl     (bench datapoints)
  logs/swap-econ/<date>.jsonl                    (runtime log, repo standard)

Run with the mlx-lm uv-tool python:
  $HOME/.local/share/uv/tools/mlx-lm/bin/python experiments/router/swap_econ.py

Caveats recorded in-band: page-cache warmth is uncontrolled (no sudo purge);
round 1 after a reboot would be the true cold number. n=1 per cell unless
rounds show variance.
"""
import gc
import json
import os
import resource
import sys
import time
import uuid

os.environ["HF_HUB_OFFLINE"] = "1"

import mlx.core as mx
from mlx_lm import load, stream_generate

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
RESULTS = os.path.join(HERE, "swap-econ.results.jsonl")
LOG_DIR = os.path.join(REPO, "logs", "swap-econ")
os.makedirs(LOG_DIR, exist_ok=True)
LOG = os.path.join(LOG_DIR, time.strftime("%Y-%m-%d") + ".jsonl")

SESSION = uuid.uuid4().hex[:12]
PID = os.getpid()

TIERS = {
    "T0": "prism-ml/Ternary-Bonsai-1.7B-mlx-2bit",
    "T1": "prism-ml/Ternary-Bonsai-8B-mlx-2bit",
    "T2": "prism-ml/Ternary-Bonsai-27B-mlx-2bit",
}
PROMPT = "Explain TCP slow start in two sentences."
MAX_TOKENS = 64


def log(level, event, **ctx):
    rec = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S") + f".{int(time.time()*1000)%1000:03d}",
        "level": level, "component": "swap_econ", "event": event,
        "session_id": SESSION, "pid": PID, **ctx,
    }
    line = json.dumps(rec)
    with open(LOG, "a") as f:
        f.write(line + "\n")
    print(line, flush=True)


def result(record):
    record = {"session_id": SESSION, **record}
    with open(RESULTS, "a") as f:
        f.write(json.dumps(record) + "\n")


def rss_gb():
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e9  # bytes on macOS


def chat(tokenizer, text):
    if tokenizer.chat_template is not None:
        return tokenizer.apply_chat_template(
            [{"role": "user", "content": text}],
            tokenize=False, add_generation_prompt=True,
        )
    return text


def bench_tier(tier, round_no):
    """Load → TTFT → decode → unload; return the measured cell."""
    repo_id = TIERS[tier]
    mx.reset_peak_memory()
    log("info", "load_start", tier=tier, model=repo_id, round=round_no)

    t0 = time.perf_counter()
    model, tokenizer = load(repo_id)
    load_s = time.perf_counter() - t0
    log("info", "load_done", tier=tier, round=round_no, load_s=round(load_s, 3))

    prompt = chat(tokenizer, PROMPT)
    ttft_s = None
    n_tok = 0
    gen_t0 = time.perf_counter()
    last = None
    for resp in stream_generate(model, tokenizer, prompt, max_tokens=MAX_TOKENS):
        if ttft_s is None:
            ttft_s = time.perf_counter() - gen_t0
        n_tok += 1
        last = resp
    gen_s = time.perf_counter() - gen_t0
    decode_tps = getattr(last, "generation_tps", None) if last else None
    peak_gb = mx.get_peak_memory() / 1e9

    cell = {
        "kind": "tier_cell", "tier": tier, "round": round_no,
        "load_s": round(load_s, 3),
        "ttft_s": round(ttft_s, 3) if ttft_s is not None else None,
        "gen_s": round(gen_s, 3), "tokens": n_tok,
        "decode_tps": round(decode_tps, 2) if decode_tps else None,
        "metal_peak_gb": round(peak_gb, 3), "proc_max_rss_gb": round(rss_gb(), 3),
    }
    result(cell)
    log("info", "tier_cell_done", **{k: v for k, v in cell.items() if k != "kind"})

    t0 = time.perf_counter()
    del model, tokenizer
    gc.collect()
    mx.clear_cache()
    unload_s = time.perf_counter() - t0
    result({"kind": "unload", "tier": tier, "round": round_no,
            "unload_s": round(unload_s, 3)})
    log("info", "unload_done", tier=tier, round=round_no, unload_s=round(unload_s, 3))
    return cell


def bench_coresidency():
    """T0 + T1 loaded together (0.5 + 2.3 GB should fit): does escalation
    T0→T1 avoid the swap entirely?"""
    log("info", "coresidency_start", tiers="T0+T1")
    mx.reset_peak_memory()
    t0 = time.perf_counter()
    m0, tk0 = load(TIERS["T0"])
    m1, tk1 = load(TIERS["T1"])
    both_load_s = time.perf_counter() - t0

    cells = {}
    for tier, (m, tk) in (("T0", (m0, tk0)), ("T1", (m1, tk1))):
        prompt = chat(tk, PROMPT)
        ttft = None
        t0 = time.perf_counter()
        last = None
        n = 0
        for resp in stream_generate(m, tk, prompt, max_tokens=MAX_TOKENS):
            if ttft is None:
                ttft = time.perf_counter() - t0
            n += 1
            last = resp
        cells[tier] = {
            "ttft_s": round(ttft, 3),
            "decode_tps": round(getattr(last, "generation_tps", 0.0), 2),
            "tokens": n,
        }
    rec = {
        "kind": "coresidency", "tiers": "T0+T1",
        "both_load_s": round(both_load_s, 3),
        "metal_peak_gb": round(mx.get_peak_memory() / 1e9, 3),
        "proc_max_rss_gb": round(rss_gb(), 3),
        "per_tier": cells,
    }
    result(rec)
    log("info", "coresidency_done", **{k: v for k, v in rec.items() if k != "kind"})
    del m0, tk0, m1, tk1
    gc.collect()
    mx.clear_cache()


def main():
    log("info", "process_start", exe=sys.executable,
        argv=sys.argv, cwd=os.getcwd(), ppid=os.getppid(),
        note="page-cache warmth uncontrolled; round1 ~= cold-ish, round2 = warm")
    result({"kind": "run_meta", "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "prompt_hash": hex(abs(hash(PROMPT)))[2:14], "max_tokens": MAX_TOKENS,
            "tiers": TIERS})

    # Two rounds over each tier; T2 last so an OOM still leaves T0/T1 data.
    for round_no in (1, 2):
        for tier in ("T0", "T1", "T2"):
            try:
                bench_tier(tier, round_no)
            except Exception as e:  # noqa: BLE001 — record, keep going
                log("error", "tier_cell_failed", tier=tier, round=round_no,
                    error_type=type(e).__name__, message=str(e)[:300])
                result({"kind": "tier_cell_error", "tier": tier,
                        "round": round_no, "error": str(e)[:300]})

    try:
        bench_coresidency()
    except Exception as e:  # noqa: BLE001
        log("error", "coresidency_failed", error_type=type(e).__name__,
            message=str(e)[:300])
        result({"kind": "coresidency_error", "error": str(e)[:300]})

    log("info", "process_exit", exit_code=0)


if __name__ == "__main__":
    main()
