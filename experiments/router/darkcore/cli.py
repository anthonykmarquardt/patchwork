"""dark-core CLI.

  python -m darkcore.cli route "query text"
  python -m darkcore.cli config get
  python -m darkcore.cli config patch '{"lambda_by_class":{"agentic":0.5}}' \
      --base 0 --actor operator [--note "..."]
  python -m darkcore.cli state          # live_metrics rollup from telemetry
"""
import argparse
import glob
import json
import os
import sys

from . import surface, telemetry


def cmd_route(args):
    from .router import Router  # deferred: needs mlx
    r = Router()
    out = r.route(args.query)
    print(json.dumps({k: out[k] for k in ("tier", "escalations", "flagged", "trace")},
                     indent=2))
    print("\n--- answer ---\n" + out["answer"])


def cmd_config(args):
    if args.action == "get":
        print(json.dumps(surface.get_config(), indent=2))
        return
    res = surface.set_config(json.loads(args.patch), args.base, args.actor,
                             note=args.note)
    print(json.dumps(res, indent=2))
    sys.exit(0 if res["status"] == "ok" else 1)


def cmd_state(args):
    """get_state(): on-demand rollup over logs/router/*.jsonl (surface §7)."""
    tiers, esc, classes, verdicts = {}, 0, {}, {}
    routes = 0
    for path in sorted(glob.glob(os.path.join(telemetry.LOG_DIR, "*.jsonl"))):
        with open(path) as f:
            for line in f:
                try:
                    e = json.loads(line)
                except json.JSONDecodeError:
                    continue
                ev = e.get("event")
                if ev == "route_completed":
                    routes += 1
                    tiers[e["final_tier"]] = tiers.get(e["final_tier"], 0) + 1
                    esc += e.get("escalations", 0)
                    c = e.get("class", "?")
                    classes[c] = classes.get(c, 0) + 1
                elif ev == "verifier_result":
                    key = f'{e.get("class","?")}/{e.get("verdict")}'
                    verdicts[key] = verdicts.get(key, 0) + 1
    cfg = surface.get_config()
    print(json.dumps({
        "config_version": cfg["config_version"],
        "routes": routes,
        "tier_distribution": tiers,
        "escalation_rate": round(esc / routes, 3) if routes else None,
        "class_distribution": classes,
        "verifier_verdicts": verdicts,
    }, indent=2))


def main():
    ap = argparse.ArgumentParser(prog="darkcore")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("route")
    p.add_argument("query")
    p.set_defaults(fn=cmd_route)

    p = sub.add_parser("config")
    p.add_argument("action", choices=["get", "patch"])
    p.add_argument("patch", nargs="?")
    p.add_argument("--base", type=int, default=None)
    p.add_argument("--actor", default="operator")
    p.add_argument("--note", default="")
    p.set_defaults(fn=cmd_config)

    p = sub.add_parser("state")
    p.set_defaults(fn=cmd_state)

    args = ap.parse_args()
    if args.cmd == "config" and args.action == "patch" and (args.patch is None or args.base is None):
        ap.error("config patch requires PATCH json and --base VERSION")
    args.fn(args)


if __name__ == "__main__":
    main()
