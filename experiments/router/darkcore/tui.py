"""gauge board — the operator TUI over dark-core telemetry.

The steam-engine framing made literal: dark-core is the engine, this is the
brass gauge panel. Reads logs/router/*.jsonl (never content — the logs are
already PII-safe) and renders what the router is doing as it runs.

  python -m darkcore.tui                # snapshot of everything logged
  python -m darkcore.tui --live         # follow today's log as it grows
  python -m darkcore.tui --replay       # re-play history at --speed (default 8x)

Design language: Catppuccin Frappé (ghostty/nvim), transparent-background
safe (no painted backgrounds), cyan structural rails (starship), color and
glyph over text.
"""
import argparse
import glob
import json
import os
import time
from collections import deque

from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich import box

from . import telemetry

# ---------------------------------------------------------- Catppuccin Frappé
C = {
    "text": "#c6d0f5", "sub": "#a5adce", "dim": "#737994", "surf": "#51576d",
    "red": "#e78284", "maroon": "#ea999c", "peach": "#ef9f76",
    "yellow": "#e5c890", "green": "#a6d189", "teal": "#81c8be",
    "sky": "#99d1db", "sapphire": "#85c1dc", "blue": "#8caaee",
    "lavender": "#babbf1", "mauve": "#ca9ee6", "pink": "#f4b8e4",
}
TIER_C = {"T0": C["green"], "T1": C["peach"], "T2": C["mauve"]}
CLASS_C = {"agentic": C["sapphire"], "reasoning": C["lavender"],
           "emotional": C["pink"], "default": C["dim"]}
RAIL = C["sky"]  # the starship cyan
SPARK = "▁▂▃▄▅▆▇█"


def spark(vals, width=24):
    vals = list(vals)[-width:]
    if not vals:
        return Text("·" * 3, style=C["dim"])
    hi = max(vals) or 1.0
    return Text("".join(SPARK[min(int(v / hi * 7.999), 7)] for v in vals))


def bar(count, total, width, color):
    n = int(width * count / total) if total else 0
    t = Text("█" * n, style=color)
    t.append("░" * (width - n), style=C["surf"])
    return t


def meter(frac, width=18):
    """A gauge needle: green→yellow→red zones."""
    frac = max(0.0, min(1.0, frac))
    n = int(round(frac * width))
    t = Text()
    for i in range(width):
        col = C["green"] if i < width * 0.34 else (C["yellow"] if i < width * 0.67 else C["red"])
        t.append("▰" if i < n else "▱", style=col if i < n else C["surf"])
    return t


# ------------------------------------------------------------------- state
class Board:
    def __init__(self):
        self.routes = deque(maxlen=14)      # finished + in-flight rows
        self.inflight = {}                  # route_id -> row dict
        self.tier_final = {}
        self.class_counts = {}
        self.edges = {}                     # (start,final) -> n
        self.verdicts = {}                  # (class, verdict) -> n
        self.rungs = {}                     # class -> last rung seen
        self.lat = {t: deque(maxlen=40) for t in ("T0", "T1", "T2")}
        self.swaps = deque(maxlen=40)       # load_ms history
        self.swap_n = 0
        self.swap_ms = 0.0
        self.resident = set()
        self.alarms = deque(maxlen=6)
        self.overhead = deque(maxlen=60)
        self.n_routes = 0
        self.n_esc = 0
        self.n_flagged = 0
        self.config_version = "·"
        self.last_ts = ""

    # ---- event ingestion -------------------------------------------------
    def feed(self, e):
        ev = e.get("event")
        self.last_ts = e.get("ts", self.last_ts)
        if ev == "config_loaded":
            self.config_version = e.get("config_version", "·")
        elif ev == "config_invalid":
            self.alarms.appendleft(("config invalid → defaults", e.get("ts", "")))
        elif ev == "routing_decision":
            row = {"id": e["route_id"], "qhash": e.get("qhash", "?")[:7],
                   "class": e.get("class", "default"), "path": [],
                   "start": e.get("start_tier"), "final": None,
                   "ms": None, "flag": False, "live": "◌"}
            self.inflight[e["route_id"]] = row
            self.routes.appendleft(row)
            self.overhead.append(e.get("overhead_ms", 0.0))
        elif ev == "tier_dispatched":
            r = self.inflight.get(e["route_id"])
            if r is not None:
                r["path"].append([e["tier"], "…"])
                r["live"] = "◉"
        elif ev == "verifier_result":
            r = self.inflight.get(e["route_id"])
            if r is not None and r["path"]:
                r["path"][-1][1] = "✓" if e["verdict"] == "pass" else "✗"
            k = (e.get("class", "?"), e.get("verdict", "?"))
            self.verdicts[k] = self.verdicts.get(k, 0) + 1
            if e.get("rung") is not None:
                self.rungs[e.get("class", "?")] = e["rung"]
        elif ev == "escalation":
            pass  # path glyphs carry it
        elif ev == "route_completed":
            r = self.inflight.pop(e["route_id"], None)
            if r is not None:
                r["final"] = e.get("final_tier")
                r["ms"] = e.get("total_ms")
                r["flag"] = e.get("flagged", False)
                r["live"] = " "
                if r["path"] and r["path"][-1][1] == "…":
                    r["path"][-1][1] = "·"
            self.n_routes += 1
            self.n_esc += e.get("escalations", 0)
            self.n_flagged += e.get("flagged", False)
            ft = e.get("final_tier", "?")
            self.tier_final[ft] = self.tier_final.get(ft, 0) + 1
            c = e.get("class", "?")
            self.class_counts[c] = self.class_counts.get(c, 0) + 1
            start = (e.get("attempts") or [{}])[0].get("tier", ft)
            self.edges[(start, ft)] = self.edges.get((start, ft), 0) + 1
            for a in e.get("attempts", []):
                if a.get("gen_ms") and a.get("tier") in self.lat:
                    self.lat[a["tier"]].append(a["gen_ms"])
        elif ev == "model_loaded":
            self.swap_n += 1
            self.swap_ms += e.get("load_ms", 0.0)
            self.swaps.append(e.get("load_ms", 0.0))
            self.resident.add(e.get("tier"))
        elif ev == "model_evicted":
            self.resident.discard(e.get("tier"))
        elif ev in ("terminal_failure", "budget_exhausted", "tier_failover",
                    "tier_unavailable"):
            self.alarms.appendleft((f'{ev} {e.get("tier", e.get("kind", ""))}',
                                    e.get("ts", "")))

    # ---- rendering -------------------------------------------------------
    def _header(self):
        t = Text()
        t.append("┌ ", style=RAIL)
        t.append("dark-core", style=f"bold {C['text']}")
        t.append(" · gauge board", style=C["dim"])
        t.append("    ")
        t.append("cfg ", style=C["dim"])
        t.append(f"v{self.config_version}", style=C["teal"])
        t.append("   routes ", style=C["dim"])
        t.append(str(self.n_routes), style=C["text"])
        t.append("   flags ", style=C["dim"])
        t.append(str(self.n_flagged), style=C["red"] if self.n_flagged else C["dim"])
        t.append("   " + (self.last_ts[11:19] if len(self.last_ts) > 19 else self.last_ts),
                 style=C["dim"])
        return t

    def _tiers(self):
        total = sum(self.tier_final.values())
        g = Table.grid(padding=(0, 1))
        g.add_column(); g.add_column(); g.add_column(justify="right")
        for tier in ("T0", "T1", "T2"):
            n = self.tier_final.get(tier, 0)
            chip = Text(f"● {tier}", style=f"bold {TIER_C[tier]}")
            res = Text(" ◆" if tier in self.resident else " ◇",
                       style=C["teal"] if tier in self.resident else C["surf"])
            chip.append_text(res)
            g.add_row(chip, bar(n, total, 16, TIER_C[tier]), Text(str(n), style=C["sub"]))
        g.add_row(Text(""), Text(""), Text(""))
        pct = 100 * sum(self.tier_final.get(t, 0) for t in ("T0", "T1")) / total if total else 0
        g.add_row(Text("≤T1", style=C["dim"]), meter(pct / 100, 16),
                  Text(f"{pct:.0f}%", style=C["sub"]))
        g.add_row(Text("swap", style=C["dim"]), spark(self.swaps, 16),
                  Text(f"{self.swap_ms/1000:.1f}s·{self.swap_n}", style=C["sub"]))
        return Panel(g, title=Text("tiers ◆=resident", style=C["dim"]),
                     border_style=RAIL, box=box.ROUNDED)

    def _cascade(self):
        g = Table.grid(padding=(0, 1))
        g.add_column(); g.add_column(); g.add_column(justify="right")
        for (s, f), n in sorted(self.edges.items()):
            arrow = Text(s, style=TIER_C.get(s, C["dim"]))
            if s == f:
                arrow.append(" ⇢ ", style=C["dim"]); arrow.append("stay", style=C["dim"])
            else:
                arrow.append(" ➜ ", style=C["peach"]); arrow.append(f, style=TIER_C.get(f, C["dim"]))
            g.add_row(arrow, bar(n, self.n_routes, 10, C["sapphire"] if s == f else C["peach"]),
                      Text(str(n), style=C["sub"]))
        rate = self.n_esc / self.n_routes if self.n_routes else 0
        g.add_row(Text(""), Text(""), Text(""))
        g.add_row(Text("esc", style=C["dim"]), meter(rate, 10),
                  Text(f"{rate:.2f}", style=C["sub"]))
        return Panel(g, title=Text("cascade flow", style=C["dim"]),
                     border_style=RAIL, box=box.ROUNDED)

    def _stream(self):
        tb = Table(box=None, padding=(0, 1), show_header=True,
                   header_style=C["dim"], expand=True)
        tb.add_column(" ", width=1, no_wrap=True)
        tb.add_column("route", style=C["dim"], width=7, no_wrap=True)
        tb.add_column("class", width=5, no_wrap=True)
        tb.add_column("path", ratio=1, no_wrap=True, overflow="ellipsis")
        tb.add_column("ms", justify="right", width=6, no_wrap=True)
        for r in list(self.routes):
            cls = Text("● ", style=CLASS_C.get(r["class"], C["dim"]))
            cls.append(r["class"][:3], style=CLASS_C.get(r["class"], C["dim"]))
            path = Text()
            for i, (tier, verdict) in enumerate(r["path"]):
                if i:
                    path.append(" ➜ ", style=C["peach"])
                path.append(tier, style=f"bold {TIER_C.get(tier, C['dim'])}")
                vstyle = {"✓": C["green"], "✗": C["red"], "…": C["yellow"], "·": C["dim"]}.get(verdict, C["dim"])
                path.append(verdict, style=vstyle)
            if r["flag"]:
                path.append(" ⚑", style=f"bold {C['red']}")
            ms = Text("…", style=C["yellow"]) if r["ms"] is None else \
                Text(f"{r['ms']/1000:.1f}s", style=C["sub"])
            live = Text(r["live"], style=C["yellow"])
            tb.add_row(live, r["qhash"], cls, path, ms)
        if not self.routes:
            tb.add_row(" ", Text("—", style=C["dim"]), Text("waiting", style=C["dim"]),
                       Text("no routes yet", style=C["dim"]), Text(""))
        return Panel(tb, title=Text("route stream", style=C["dim"]),
                     border_style=RAIL, box=box.ROUNDED)

    def _latency(self):
        g = Table.grid(padding=(0, 1))
        g.add_column(); g.add_column(); g.add_column(justify="right")
        for tier in ("T0", "T1", "T2"):
            h = self.lat[tier]
            last = f"{h[-1]/1000:.1f}s" if h else "·"
            g.add_row(Text(tier, style=f"bold {TIER_C[tier]}"),
                      spark(h, 22), Text(last, style=C["sub"]))
        if self.overhead:
            oh = sorted(self.overhead)
            p95 = oh[int(0.95 * (len(oh) - 1))]
            g.add_row(Text("rtr", style=C["dim"]), spark(self.overhead, 22),
                      Text(f"{p95:.2f}ms", style=C["teal"]))
        return Panel(g, title=Text("gen latency / router overhead", style=C["dim"]),
                     border_style=RAIL, box=box.ROUNDED)

    def _verifiers(self):
        classes = sorted({c for c, _ in self.verdicts} | set(self.class_counts))
        tb = Table(box=None, padding=(0, 1), show_header=True, header_style=C["dim"])
        tb.add_column("class"); tb.add_column("rung", justify="center")
        tb.add_column("pass", justify="right"); tb.add_column("fail", justify="right")
        for c in classes:
            p = self.verdicts.get((c, "pass"), 0)
            f = self.verdicts.get((c, "fail"), 0)
            rung = self.rungs.get(c)
            rung_t = Text("—", style=C["dim"]) if rung is None else \
                Text(str(rung), style=C["teal"] if rung <= 1 else
                     (C["yellow"] if rung < 5 else C["dim"]))
            tb.add_row(Text(c, style=CLASS_C.get(c, C["dim"])), rung_t,
                       Text(str(p), style=C["green"] if p else C["dim"]),
                       Text(str(f), style=C["red"] if f else C["dim"]))
        if not classes:
            tb.add_row(Text("—", style=C["dim"]), Text(""), Text(""), Text(""))
        return Panel(tb, title=Text("verifier verdicts", style=C["dim"]),
                     border_style=RAIL, box=box.ROUNDED)

    def _alarms(self):
        lines = []
        for msg, ts in self.alarms:
            t = Text("▲ ", style=f"bold {C['red']}")
            t.append(msg, style=C["maroon"])
            t.append(f"  {ts[11:19]}", style=C["dim"])
            lines.append(t)
        if not lines:
            lines = [Text("○ quiet", style=C["dim"])]
        return Panel(Group(*lines), title=Text("alarms", style=C["dim"]),
                     border_style=C["maroon"] if self.alarms else RAIL,
                     box=box.ROUNDED)

    def render(self, width):
        left = Group(self._tiers(), self._cascade(), self._verifiers())
        right = Group(self._stream(), self._latency(), self._alarms())
        grid = Table.grid(expand=True, padding=(0, 1))
        grid.add_column(width=36)
        grid.add_column(ratio=1)
        grid.add_row(left, right)
        return Group(self._header(), grid,
                     Text("└➜", style=RAIL))


# ------------------------------------------------------------------- runner
def events(paths):
    for p in paths:
        with open(p) as f:
            for line in f:
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue


def parse_ts(ts):
    try:
        base, ms = ts.rsplit(".", 1)
        return time.mktime(time.strptime(base, "%Y-%m-%dT%H:%M:%S")) + int(ms) / 1000
    except (ValueError, AttributeError):
        return None


def main():
    ap = argparse.ArgumentParser(prog="darkcore.tui")
    ap.add_argument("--live", action="store_true", help="follow today's log")
    ap.add_argument("--replay", action="store_true", help="replay history")
    ap.add_argument("--speed", type=float, default=8.0, help="replay speedup")
    ap.add_argument("--logs", default=telemetry.LOG_DIR)
    args = ap.parse_args()

    console = Console()
    board = Board()
    paths = sorted(glob.glob(os.path.join(args.logs, "*.jsonl")))

    if args.replay:
        with Live(board.render(console.width), console=console,
                  refresh_per_second=20, screen=True) as live:
            prev = None
            for e in events(paths):
                ts = parse_ts(e.get("ts", ""))
                if prev is not None and ts is not None:
                    time.sleep(min(max(ts - prev, 0) / args.speed, 1.5))
                prev = ts if ts is not None else prev
                board.feed(e)
                live.update(board.render(console.width))
            live.update(board.render(console.width))
            time.sleep(3)
        console.print(board.render(console.width))  # leave the final board visible
    elif args.live:
        today = os.path.join(args.logs, time.strftime("%Y-%m-%d") + ".jsonl")
        for e in events([p for p in paths if p != today]):
            board.feed(e)  # history first, silently
        pos = 0
        with Live(board.render(console.width), console=console,
                  refresh_per_second=4) as live:
            while True:
                if os.path.exists(today):
                    with open(today) as f:
                        f.seek(pos)
                        for line in f:
                            try:
                                board.feed(json.loads(line))
                            except json.JSONDecodeError:
                                pass
                        pos = f.tell()
                live.update(board.render(console.width))
                time.sleep(0.5)
    else:  # snapshot
        for e in events(paths):
            board.feed(e)
        console.print(board.render(console.width))


if __name__ == "__main__":
    main()
