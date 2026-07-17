"""Layer 3 — the cascade (verify-and-escalate). The spine.

Run a tier -> apply the class's rung-appropriate verifier -> escalate on
fail, within cascade_policy (attempt budget, wall-clock budget, terminal
emit_flagged). This is what makes the confidently-wrong T0 safe. Every step
is telemetered; content never is.
"""
import time

from . import telemetry, verifiers
from .models import TierUnavailable


def run(pool, query, qhash, route_id, klass, start_tier, params):
    policy = params["cascade_policy"]
    vconf = params["verifier_config"].get(klass, params["verifier_config"]["default"])
    override = params["escalation_overrides"].get(klass)
    if override:
        start_tier = override

    attempts = []
    tier = start_tier
    t_start = time.perf_counter()
    result = None
    flagged = False

    while tier is not None:
        elapsed_ms = (time.perf_counter() - t_start) * 1000
        if len(attempts) >= policy["max_tiers_per_query"]:
            flagged = True
            telemetry.emit("budget_exhausted", level="warn", route_id=route_id,
                           kind="max_tiers", attempts=len(attempts))
            break
        if elapsed_ms > policy["per_query_ms_budget"]:
            flagged = True
            telemetry.emit("budget_exhausted", level="warn", route_id=route_id,
                           kind="wall_clock", elapsed_ms=round(elapsed_ms, 1))
            break

        telemetry.emit("tier_dispatched", route_id=route_id, tier=tier,
                       attempt=len(attempts) + 1, **{"class": klass})
        try:
            result = pool.generate(tier, query)
        except TierUnavailable:
            # infra failure != verifier failure: fail over to the next tier
            telemetry.emit("tier_failover", level="warn", route_id=route_id,
                           tier=tier)
            attempts.append({"tier": tier, "outcome": "unavailable"})
            tier = pool.next_tier(tier)
            continue

        if vconf["rung"] == 5 or vconf["verifier"] is None:
            passed, detail = True, {"rung": 5, "check": None,
                                    "note": "fixed_policy_no_verifier", "verify_ms": 0.0}
        else:
            fn = verifiers.REGISTRY[vconf["verifier"]]
            passed, detail = fn(query, result["answer"], pool, tier,
                                {"expected": params.get("_expected"),
                                 "thresholds": vconf.get("thresholds", {})})

        telemetry.emit("verifier_result", route_id=route_id, tier=tier,
                       verdict="pass" if passed else "fail", **{"class": klass},
                       **detail)
        attempts.append({
            "tier": tier, "outcome": "pass" if passed else "fail",
            "load_ms": result["load_ms"], "ttft_ms": result["ttft_ms"],
            "gen_ms": result["gen_ms"], "tokens": result["tokens"],
            "tps": result["tps"], "verify_ms": detail.get("verify_ms", 0.0),
            "rung": detail.get("rung"),
        })

        if passed:
            break
        nxt = pool.next_tier(tier)
        if nxt is None:
            # terminal failure: T2's verifier also failed
            flagged = True
            telemetry.emit("terminal_failure", level="error", route_id=route_id,
                           tier=tier, action=policy["terminal_failure"],
                           alarm=True, **{"class": klass})
            break
        telemetry.emit("escalation", route_id=route_id,
                       from_tier=tier, to_tier=nxt, **{"class": klass})
        tier = nxt

    total_ms = round((time.perf_counter() - t_start) * 1000, 1)
    final = attempts[-1]["tier"] if attempts else start_tier
    return {
        "answer": result["answer"] if result else "",
        "final_tier": final,
        "escalations": max(0, len([a for a in attempts if a.get("outcome") != "unavailable"]) - 1),
        "flagged": flagged,
        "attempts": attempts,
        "total_ms": total_ms,
    }
