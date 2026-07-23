"""dark-core operator CLI.

  python -m darkcore serve            # start the server + live gauge board
  python -m darkcore route "query"    # one-shot route with live climb status
  python -m darkcore status           # config / predictor / tiers / rollup at a glance
  python -m darkcore board            # gauge board (snapshot | --live | --replay)
  python -m darkcore config get|patch # control-surface ops (JSON, machine-readable)
  python -m darkcore state            # live_metrics rollup (JSON, machine-readable)

Human-facing commands render rich/Frappé like the gauge board; `config` and
`state` keep plain-JSON contracts for the control plane (tuner/orchestrator).
Handy alias:  alias darkcore='$MLXPY -m darkcore'
"""
import argparse
import glob
import json
import os
import sys
import time

from . import __version__, surface, telemetry


# ---------------------------------------------------------------- shared bits
def _console(stderr=False):
    from rich.console import Console
    return Console(stderr=stderr)


def _status(name, **f):
    """Live climb visibility on stderr (stdout stays machine-readable)."""
    line = {
        "dispatch": lambda: f"◉ {f['tier']} answering (attempt {f['attempt']}) …",
        "verdict": lambda: (f"{'✓' if f['passed'] else '✗'} {f['tier']} "
                            f"{'accepted' if f['passed'] else 'rejected'} "
                            f"[{f.get('check')}] {f.get('gen_ms', 0)/1000:.1f}s"),
        "escalation": lambda: f"➜ escalating {f['from_tier']} → {f['to_tier']} (loading if cold) …",
        "terminal_failure": lambda: f"⚑ {f['tier']} also failed — emitting flagged answer",
    }.get(name)
    if line:
        print("  " + line(), file=sys.stderr, flush=True)


def _store_meta(params):
    """Exemplar-store meta.json for display, or None."""
    ref = params.get("exemplar_store_ref") or {}
    uri = surface.resolve_exemplar_path(ref)
    if not uri:
        return None
    try:
        return json.load(open(os.path.join(uri, "meta.json")))
    except (OSError, json.JSONDecodeError):
        return None


def _rollup():
    """One pass over logs/router/*.jsonl → the live_metrics dict (surface §7)."""
    tiers, esc, classes, verdicts = {}, 0, {}, {}
    routes, last_ts, overhead = 0, "", []
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
                    last_ts = e.get("ts", last_ts)
                    overhead.append(e.get("overhead_ms", 0.0))
                elif ev == "verifier_result":
                    key = f'{e.get("class","?")}/{e.get("verdict")}'
                    verdicts[key] = verdicts.get(key, 0) + 1
    oh = sorted(overhead)
    return {
        "routes": routes,
        "tier_distribution": tiers,
        "escalation_rate": round(esc / routes, 3) if routes else None,
        "class_distribution": classes,
        "verifier_verdicts": verdicts,
        "overhead_p95_ms": round(oh[int(0.95 * (len(oh) - 1))], 2) if oh else None,
        "last_route_ts": last_ts,
    }


# --------------------------------------------------------------------- serve
def _banner(console, cfg, host, port, board_on):
    from rich.text import Text
    from .tui import C, RAIL
    p = cfg["params"]
    meta = _store_meta(p)
    rows = [
        ("endpoint", f"http://{host}:{port}/v1  (OpenAI-compatible)"),
        ("health", "/health  (?deep=1 for config/tiers/store)"),
        ("config", f'v{cfg["config_version"]} · updated_by {cfg.get("updated_by", "?")}'
                   + (" · predictor class_prior" if p.get("predictor_enabled") and meta
                      else " · predictor off")),
    ]
    if meta:
        rows.append(("exemplars", f'v{meta["version"]} · n={meta["n"]} · {meta["embedder"]}'))
    tiers = " · ".join(f'{t["id"]} {t["model"].rsplit("/", 1)[-1]}'
                       for t in p["tier_roster"])
    rows.append(("tiers", tiers))

    head = Text()
    head.append("┌ ", style=RAIL)
    head.append("dark-core", style=f"bold {C['text']}")
    head.append(f" v{__version__}", style=C["teal"])
    head.append(" · patchwork dynamic router", style=C["dim"])
    console.print(head)
    for k, v in rows:
        line = Text()
        line.append("│ ", style=RAIL)
        line.append(f"{k:<10}", style=C["dim"])
        line.append(v, style=C["text"])
        console.print(line)
    tail = Text()
    tail.append("└➜ ", style=RAIL)
    tail.append("live board — ctrl-c to stop" if board_on else "headless — ctrl-c to stop",
                style=C["dim"])
    console.print(tail)


def cmd_serve(args):
    console = _console(stderr=True)
    headless = args.headless or args.no_board or not sys.stderr.isatty()

    with console.status("[dim]warming router (config · exemplars · embedder) …[/]"):
        from .server import create_app
        app = create_app()
    import uvicorn

    cfg = surface.get_config()
    _banner(console, cfg, args.host, args.port, board_on=not headless)

    uv_config = uvicorn.Config(
        app, host=args.host, port=args.port,
        log_level="info" if headless else "warning",
        access_log=headless,
    )
    server = uvicorn.Server(uv_config)

    if headless:
        server.run()  # blocks; uvicorn owns signals + logs
        return

    # TTY: uvicorn in a daemon thread, gauge board in the foreground.
    import threading
    from rich.console import Group
    from rich.live import Live
    from rich.text import Text
    from .tui import Board, C, RAIL, events

    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    deadline = time.time() + 15
    while not server.started and t.is_alive() and time.time() < deadline:
        time.sleep(0.05)
    if not t.is_alive():
        console.print(f"[bold {C['red']}]server failed to start[/] — "
                      f"is port {args.port} in use? "
                      f"(lsof -i :{args.port})")
        sys.exit(1)

    started = time.time()
    board = Board()
    today = os.path.join(telemetry.LOG_DIR, time.strftime("%Y-%m-%d") + ".jsonl")
    paths = sorted(glob.glob(os.path.join(telemetry.LOG_DIR, "*.jsonl")))
    pos = 0
    for e in events([p for p in paths if p != today]):
        board.feed(e)  # history first, silently — gauges keep their context
    if os.path.exists(today):
        with open(today) as f:  # today's pre-start routes are history too
            for line in f:
                try:
                    board.feed(json.loads(line))
                except json.JSONDecodeError:
                    pass
            pos = f.tell()
    baseline_routes = board.n_routes  # "served" counts THIS process only

    def status_bar():
        up = int(time.time() - started)
        bar = Text()
        bar.append("▲ ", style=f"bold {C['green']}")
        bar.append(f"http://{args.host}:{args.port}/v1", style=C["teal"])
        bar.append("   served ", style=C["dim"])
        bar.append(str(board.n_routes - baseline_routes), style=C["text"])
        bar.append("   up ", style=C["dim"])
        bar.append(f"{up//3600}:{up%3600//60:02d}:{up%60:02d}", style=C["text"])
        bar.append("   ctrl-c stops", style=C["dim"])
        return bar

    try:
        with Live(Group(status_bar(), board.render(console.width)),
                  console=console, refresh_per_second=4) as live:
            while t.is_alive():
                if os.path.exists(today):
                    with open(today) as f:
                        f.seek(pos)
                        for line in f:
                            try:
                                board.feed(json.loads(line))
                            except json.JSONDecodeError:
                                pass
                        pos = f.tell()
                live.update(Group(status_bar(), board.render(console.width)))
                time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        server.should_exit = True
        t.join(timeout=10)
    outro = Text()
    outro.append("└➜ ", style=RAIL)
    outro.append(f"stopped · {board.n_routes - baseline_routes} routes this session",
                 style=C["dim"])
    console.print(outro)


# --------------------------------------------------------------------- route
def cmd_route(args):
    from .router import Router  # deferred: needs mlx
    if args.json:
        r = Router()
        out = r.route(args.query, on_event=None if args.quiet else _status)
        print(json.dumps({k: out[k] for k in ("tier", "escalations", "flagged", "trace")},
                         indent=2))
        print("\n--- answer ---\n" + out["answer"])
        return

    console = _console(stderr=True)
    from rich.panel import Panel
    from rich.text import Text
    from rich import box
    from .tui import C, CLASS_C, TIER_C, RAIL

    with console.status("[dim]loading router …[/]"):
        r = Router()
    out = r.route(args.query, on_event=None if args.quiet else _status)

    tr = out["trace"]
    path = Text()
    for i, a in enumerate(tr["attempts"]):
        if i:
            path.append(" ➜ ", style=C["peach"])
        path.append(a["tier"], style=f"bold {TIER_C.get(a['tier'], C['dim'])}")
        glyph = {"pass": "✓", "fail": "✗", "unavailable": "∅"}.get(a.get("outcome"), "·")
        path.append(glyph, style=C["green"] if glyph == "✓" else C["red"])
    line = Text()
    line.append("● ", style=CLASS_C.get(tr["class"], C["dim"]))
    line.append(f'{tr["class"]}  ', style=CLASS_C.get(tr["class"], C["dim"]))
    line.append_text(path)
    line.append(f'  {tr["total_ms"]/1000:.1f}s', style=C["sub"])
    line.append(f'  route {tr["route_id"]}', style=C["dim"])
    line.append(f'  cfg v{tr["config_version"]}', style=C["dim"])
    if out["flagged"]:
        line.append("  ⚑ flagged", style=f"bold {C['red']}")

    out_console = _console()  # answer on stdout — pipeable
    out_console.print(Panel(out["answer"],
                            title=Text(f'answer · {out["tier"]}', style=C["dim"]),
                            border_style=C["red"] if out["flagged"] else RAIL,
                            box=box.ROUNDED))
    console.print(line)


# -------------------------------------------------------------------- status
def cmd_status(args):
    console = _console()
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text
    from rich import box
    from .tui import C, CLASS_C, TIER_C, RAIL

    cfg = surface.get_config()
    p = cfg["params"]
    meta = _store_meta(p)
    roll = _rollup()

    head = Text()
    head.append("┌ ", style=RAIL)
    head.append("dark-core", style=f"bold {C['text']}")
    head.append(f" v{__version__}", style=C["teal"])
    head.append(" · status", style=C["dim"])
    console.print(head)

    g = Table.grid(padding=(0, 2))
    g.add_column(style=C["dim"])
    g.add_column()
    g.add_row("config", Text(f'v{cfg["config_version"]} · updated_by '
                             f'{cfg.get("updated_by", "?")} · {cfg.get("updated", "?")}',
                             style=C["text"]))
    pred = (f'class_prior · store v{meta["version"]} · n={meta["n"]} · {meta["embedder"]}'
            if p.get("predictor_enabled") and meta else "off")
    g.add_row("predictor", Text(pred, style=C["text"]))
    pol = p["cascade_policy"]
    g.add_row("cascade", Text(f'≤{pol["max_tiers_per_query"]} tiers · '
                              f'{pol["per_query_ms_budget"]/1000:.0f}s budget · '
                              f'skip_start {"on" if pol.get("skip_start") else "off"} · '
                              f'terminal {pol["terminal_failure"]}', style=C["text"]))
    g.add_row("paths", Text(f'{surface.CONFIG_PATH} · {telemetry.LOG_DIR}', style=C["dim"]))
    console.print(Panel(g, title=Text("surface", style=C["dim"]),
                        border_style=RAIL, box=box.ROUNDED))

    tb = Table(box=None, padding=(0, 1), show_header=True, header_style=C["dim"])
    tb.add_column("tier"); tb.add_column("model"); tb.add_column("max_tok", justify="right")
    tb.add_column("start for"); tb.add_column("floor for")
    for t in p["tier_roster"]:
        tid = t["id"]
        starts = ", ".join(k for k, v in p["class_start_map"].items() if v == tid) or "—"
        floors = ", ".join(k for k, v in p["class_floor"].items() if v == tid) or "—"
        tb.add_row(Text(tid, style=f'bold {TIER_C.get(tid, C["dim"])}'),
                   Text(t["model"], style=C["sub"]),
                   Text(str(t["max_tokens"]), style=C["sub"]),
                   Text(starts, style=C["text"]), Text(floors, style=C["dim"]))
    console.print(Panel(tb, title=Text("tiers", style=C["dim"]),
                        border_style=RAIL, box=box.ROUNDED))

    vb = Table(box=None, padding=(0, 1), show_header=True, header_style=C["dim"])
    vb.add_column("class"); vb.add_column("rung", justify="center")
    vb.add_column("verifier"); vb.add_column("λ", justify="right")
    for klass, vc in p["verifier_config"].items():
        vb.add_row(Text(klass, style=CLASS_C.get(klass, C["dim"])),
                   Text(str(vc["rung"]), style=C["teal"] if vc["rung"] <= 1
                        else (C["yellow"] if vc["rung"] < 5 else C["dim"])),
                   Text(vc["verifier"] or "— (fixed policy)", style=C["sub"]),
                   Text(f'{p["lambda_by_class"].get(klass, "—")}', style=C["sub"]))
    console.print(Panel(vb, title=Text("verifiers · λ", style=C["dim"]),
                        border_style=RAIL, box=box.ROUNDED))

    r = Table.grid(padding=(0, 2))
    r.add_column(style=C["dim"]); r.add_column()
    total = roll["routes"]
    if total:
        dist = " · ".join(f'{t} {n} ({100*n/total:.0f}%)'
                          for t, n in sorted(roll["tier_distribution"].items()))
        r.add_row("routes", Text(f'{total} · {dist}', style=C["text"]))
        r.add_row("escalation", Text(f'{roll["escalation_rate"]}', style=C["text"]))
        r.add_row("overhead p95", Text(f'{roll["overhead_p95_ms"]} ms '
                                       f'(gate <1% of route cost · target 20 ms)',
                                       style=C["text"]))
        r.add_row("last route", Text(roll["last_route_ts"], style=C["dim"]))
    else:
        r.add_row("routes", Text("none logged yet", style=C["dim"]))
    console.print(Panel(r, title=Text("telemetry rollup", style=C["dim"]),
                        border_style=RAIL, box=box.ROUNDED))
    console.print(Text("└➜", style=RAIL))


# --------------------------------------------------------------------- board
def cmd_board(args):
    from . import tui
    tui.run(live=args.live, replay=args.replay, speed=args.speed)


# ------------------------------------------------------- config/state (JSON)
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
    cfg = surface.get_config()
    print(json.dumps({"config_version": cfg["config_version"], **_rollup()}, indent=2))


# ---------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(
        prog="darkcore",
        description="dark-core — the patchwork dynamic router (spec 0001).")
    ap.add_argument("--version", action="version", version=f"darkcore {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("serve", help="start the OpenAI-compatible server (+ live board)")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--headless", action="store_true",
                   help="plain uvicorn logs, no board (default when not a TTY)")
    p.add_argument("--no-board", action="store_true", help="alias for --headless")
    p.set_defaults(fn=cmd_serve)

    p = sub.add_parser("route", help="route one query through the cascade")
    p.add_argument("query")
    p.add_argument("--quiet", action="store_true", help="suppress live status stream")
    p.add_argument("--json", action="store_true", help="machine-readable trace + answer")
    p.set_defaults(fn=cmd_route)

    p = sub.add_parser("status", help="config · predictor · tiers · rollup at a glance")
    p.set_defaults(fn=cmd_status)

    p = sub.add_parser("board", help="gauge board (snapshot; --live; --replay)")
    p.add_argument("--live", action="store_true")
    p.add_argument("--replay", action="store_true")
    p.add_argument("--speed", type=float, default=8.0)
    p.set_defaults(fn=cmd_board)

    p = sub.add_parser("config", help="control-surface get/patch (JSON)")
    p.add_argument("action", choices=["get", "patch"])
    p.add_argument("patch", nargs="?")
    p.add_argument("--base", type=int, default=None)
    p.add_argument("--actor", default="operator")
    p.add_argument("--note", default="")
    p.set_defaults(fn=cmd_config)

    p = sub.add_parser("state", help="live_metrics rollup (JSON; surface get_state)")
    p.set_defaults(fn=cmd_state)

    args = ap.parse_args()
    if args.cmd == "config" and args.action == "patch" and (args.patch is None or args.base is None):
        ap.error("config patch requires PATCH json and --base VERSION")
    args.fn(args)


if __name__ == "__main__":
    main()
