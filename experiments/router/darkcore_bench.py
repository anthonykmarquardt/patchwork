#!/usr/bin/env python3
"""dark-core v0 benchmark — the whole battery through the real cascade,
plus a T2-only baseline on the labeled subset for the cost-saved number.

  python experiments/router/darkcore_bench.py

Outputs:
  experiments/router/report.json        (aggregate, spec 0001 verify substrate)
  logs/router/<date>.jsonl              (per-route telemetry, emitted by dark-core)

Answers are kept OUT of the report (PII discipline is content discipline —
the battery is synthetic, but the pipeline treats all content the same).
Per-query answer snapshots for operator inspection go to
experiments/router/bench-answers/ (explicitly a bench artifact, not a log).
"""
import argparse
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.environ["HF_HUB_OFFLINE"] = "1"

from darkcore import surface, telemetry  # noqa: E402
from darkcore.router import Router  # noqa: E402

ANSWER_DIR = os.path.join(HERE, "bench-answers")
os.makedirs(ANSWER_DIR, exist_ok=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", default="darkcore-v0")
    ap.add_argument("--skip-baseline", metavar="PRIOR_REPORT",
                    help="reuse t2_baseline from a prior report.json instead of re-running")
    args = ap.parse_args()

    battery = [json.loads(l) for l in open(os.path.join(HERE, "battery.jsonl")) if l.strip()]
    surface.ensure_config()
    router = Router()
    telemetry.emit("bench_start", n_queries=len(battery), bench=args.label)

    rows = []
    for item in battery:
        print(f"[route] {item['id']} ({item['class']}) ...", flush=True)
        t0 = time.perf_counter()
        out = router.route(item["query"], expected=item.get("expected"))
        wall = round(time.perf_counter() - t0, 2)
        tr = out["trace"]
        rows.append({
            "id": item["id"], "class_expected": item["class"],
            "class_detected": tr["class"],
            "start_tier": tr["start_tier"], "final_tier": out["tier"],
            "escalations": out["escalations"], "flagged": out["flagged"],
            "attempts": tr["attempts"], "total_ms": tr["total_ms"],
            "overhead_ms": tr["router_overhead_ms"], "wall_s": wall,
            "labels": item.get("labels"), "smallest_sat": item.get("smallest_sat"),
            "route_id": tr["route_id"],
        })
        with open(os.path.join(ANSWER_DIR, f"{item['id']}.txt"), "w") as f:
            f.write(f"# {item['id']} | class {tr['class']} | final {out['tier']} | "
                    f"escalations {out['escalations']} | flagged {out['flagged']}\n"
                    f"--- QUERY ---\n{item['query']}\n--- ANSWER ---\n{out['answer']}\n")
        print(f"        -> final {out['tier']}  esc {out['escalations']}  "
              f"flag {out['flagged']}  {wall}s", flush=True)

    # ---- T2-only baseline on the labeled subset (the always-big comparator)
    baseline = {}
    labeled = [b for b in battery if b.get("labels")]
    if args.skip_baseline:
        baseline = json.load(open(args.skip_baseline))["t2_baseline"]
        print(f"[baseline] reusing t2_baseline from {args.skip_baseline}", flush=True)
        labeled_to_run = []
    else:
        labeled_to_run = labeled
    for item in labeled_to_run:
        print(f"[baseline-T2] {item['id']} ...", flush=True)
        t0 = time.perf_counter()
        r = router._pool.generate("T2", item["query"])
        baseline[item["id"]] = {
            "load_ms": r["load_ms"], "gen_ms": r["gen_ms"],
            "tokens": r["tokens"], "tps": r["tps"],
            "wall_s": round(time.perf_counter() - t0, 2),
        }
        print(f"        -> {baseline[item['id']]['wall_s']}s", flush=True)

    # ---- aggregate
    n = len(rows)
    esc_total = sum(r["escalations"] for r in rows)
    tier_dist = {}
    for r in rows:
        tier_dist[r["final_tier"]] = tier_dist.get(r["final_tier"], 0) + 1
    class_ok = sum(r["class_detected"] == r["class_expected"] for r in rows)
    cascade_ms_labeled = sum(r["total_ms"] for r in rows if r["labels"])
    baseline_ms = sum(b["load_ms"] + b["gen_ms"] for b in baseline.values())
    # quality via session labels: quality of the tier the cascade landed on
    quality = [r["labels"][r["final_tier"]] for r in rows if r["labels"]]
    q_t2 = [r["labels"]["T2"] for r in rows if r["labels"]]

    report = {
        "bench": args.label, "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "config_version": surface.get_config()["config_version"],
        "n_queries": n,
        "tier_distribution": tier_dist,
        "pct_at_or_below_T1": round(
            100 * sum(v for k, v in tier_dist.items() if k in ("T0", "T1")) / n, 1),
        "escalation_rate": round(esc_total / n, 3),
        "class_detection_accuracy": round(class_ok / n, 3),
        "flagged": [r["id"] for r in rows if r["flagged"]],
        "labeled_subset": {
            "n": len(labeled),
            "cascade_total_s": round(cascade_ms_labeled / 1000, 1),
            "t2_only_total_s": round(baseline_ms / 1000, 1),
            "speedup_vs_t2_only": round(baseline_ms / cascade_ms_labeled, 2)
            if cascade_ms_labeled else None,
            "mean_quality_cascade": round(sum(quality) / len(quality), 3) if quality else None,
            "mean_quality_t2_only": round(sum(q_t2) / len(q_t2), 3) if q_t2 else None,
        },
        "t2_baseline": baseline,
        "routes": rows,
    }
    with open(os.path.join(HERE, "report.json"), "w") as f:
        json.dump(report, f, indent=2)
    telemetry.emit("bench_done", **{k: report[k] for k in
                   ("n_queries", "tier_distribution", "escalation_rate")})
    print("\n=== report.json written ===")
    print(json.dumps({k: v for k, v in report.items() if k not in ("routes", "t2_baseline")},
                     indent=2))


if __name__ == "__main__":
    main()
