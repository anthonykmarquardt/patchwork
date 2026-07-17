#!/usr/bin/env python3
"""Spec 0001 verifier harness — asserts the success criteria against report.json.

  python experiments/router/verify.py --battery experiments/router/battery.jsonl \
      --report experiments/router/report.json --assert-thresholds
  ... add --run to re-run darkcore_bench.py first (needs the mlx-lm python).

Thresholds (prd.md §Success criteria):
  S1 quality retention: cascade mean quality >= T2-only mean quality - EPS (labeled subset)
  S2 safety: the confidently-wrong fixture (R1) is escalated, never emitted from T0
  S3 routing: >= 60% of labeled queries land at T0/T1
  S4 budget: router overhead < 1% of the route's total cost, per route
     (restated 2026-07-17, operator decision (b) — journal Ep. 6. The old
     absolute 20 ms/query remains the aspirational tuning target and is
     still reported for visibility; it no longer gates. Path back to the
     absolute number if ever needed: pin the embedder's memory or port
     bge-small to mlx.)
  S5 observability: every route reconstructs tier path + latency from the report alone
"""
import argparse
import json
import subprocess
import sys

EPS = 0.15
S4_PCT = 1.0             # gate: overhead < 1% of route cost (operator decision (b))
S4_ABS_TARGET_MS = 20.0  # aspirational absolute target — reported, never gates


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--battery", default="experiments/router/battery.jsonl")
    ap.add_argument("--report", default="experiments/router/report.json")
    ap.add_argument("--assert-thresholds", action="store_true")
    ap.add_argument("--run", action="store_true")
    args = ap.parse_args()

    if args.run:
        subprocess.run([sys.executable, "experiments/router/darkcore_bench.py"], check=True)

    rep = json.load(open(args.report))
    rows = rep["routes"]
    labeled = [r for r in rows if r.get("labels")]
    checks = []

    ls = rep["labeled_subset"]
    checks.append(("S1 quality retention",
                   ls["mean_quality_cascade"] >= ls["mean_quality_t2_only"] - EPS,
                   f'{ls["mean_quality_cascade"]} vs T2-only {ls["mean_quality_t2_only"]} (eps {EPS})'))

    r1 = next((r for r in rows if r["id"] == "R1"), None)
    s2 = bool(r1) and not (r1["final_tier"] == "T0")
    checks.append(("S2 safety (R1 escapes T0)", s2,
                   f'R1 final={r1["final_tier"] if r1 else "missing"} escalations={r1["escalations"] if r1 else "-"}'))

    at_or_below = sum(r["final_tier"] in ("T0", "T1") for r in labeled)
    checks.append(("S3 >=60% labeled at T0/T1", at_or_below / len(labeled) >= 0.60,
                   f"{at_or_below}/{len(labeled)}"))

    # S4 gates on relative cost; the absolute worst-case stays in the output so
    # regressions toward the 20 ms aspirational target remain visible per run.
    worst = max(rows, key=lambda r: r["overhead_ms"] / max(r["total_ms"], 1e-9))
    worst_pct = 100.0 * worst["overhead_ms"] / max(worst["total_ms"], 1e-9)
    max_overhead = max(r["overhead_ms"] for r in rows)
    checks.append(("S4 router overhead <1% of route cost", worst_pct < S4_PCT,
                   f'worst {worst_pct:.3f}% ({worst["overhead_ms"]}ms of '
                   f'{worst["total_ms"]}ms on {worst["id"]}); '
                   f"max abs {max_overhead}ms (aspirational target {S4_ABS_TARGET_MS}ms)"))

    s5 = all(r.get("attempts") and r.get("total_ms") is not None
             and all("gen_ms" in a for a in r["attempts"] if a.get("outcome") != "unavailable")
             for r in rows)
    checks.append(("S5 observability complete", s5, f"{len(rows)} routes traceable"))

    width = max(len(c[0]) for c in checks)
    failed = False
    for name, ok, detail in checks:
        print(f"  {'PASS' if ok else 'FAIL'}  {name:<{width}}  {detail}")
        failed |= not ok
    if args.assert_thresholds and failed:
        sys.exit(1)
    print("all thresholds met" if not failed else "THRESHOLD FAILURES")


if __name__ == "__main__":
    main()
