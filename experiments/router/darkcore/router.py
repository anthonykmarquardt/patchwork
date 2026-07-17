"""dark-core entry point: route(query) -> {answer, tier, escalations, trace}.

Wiring: control surface (hot-reload on version change) -> prefilter ->
[predictor: auto-off, exemplar store empty] -> cascade -> telemetry.
"""
import time

from . import cascade, prefilter, surface, telemetry
from .models import ModelPool


class Router:
    def __init__(self):
        self._mtime = 0
        self._config = None
        self._pool = None
        self._reload()

    def _reload(self):
        cfg, violations = surface.load_config()
        if violations:
            telemetry.emit("config_invalid", level="error",
                           violations=violations[:10],
                           fallback="defaults")
        roster = cfg["params"]["tier_roster"]
        if self._config is None or roster != self._config["params"]["tier_roster"]:
            self._pool = ModelPool(roster)  # roster change rebuilds the pool
        self._config = cfg
        self._mtime = surface.config_mtime()
        telemetry.emit("config_loaded", config_version=cfg["config_version"],
                       updated_by=cfg.get("updated_by"))

    def _maybe_reload(self):
        if surface.config_mtime() != self._mtime:
            self._reload()

    def route(self, query, expected=None):
        """The one public entry. `expected` = optional rung-1 ground truth
        (bench mode / checkable callers)."""
        self._maybe_reload()
        p = self._config["params"]
        route_id = telemetry.new_route_id()
        qhash = telemetry.query_hash(query)
        t0 = time.perf_counter()

        pf = prefilter.run(query, p["prefilter_rules"])
        klass = pf["class"]

        # predictor: dark mode — exemplar store empty => auto-off (I8)
        predictor = {"enabled": bool(p["predictor_enabled"]
                                     and p["exemplar_store_ref"]["uri"]),
                     "predicted_tier": None}

        start = p["class_start_map"].get(klass, p["class_start_map"]["default"])
        floor = p["class_floor"].get(klass, p["class_floor"]["default"])
        order = [t["id"] for t in p["tier_roster"]]
        if order.index(start) < order.index(floor):
            start = floor
        overhead_ms = round((time.perf_counter() - t0) * 1000, 2)

        telemetry.emit("routing_decision", route_id=route_id, qhash=qhash,
                       features=telemetry.derived_features(query),
                       prefilter=pf, predictor=predictor,
                       start_tier=start, floor=floor,
                       config_version=self._config["config_version"],
                       overhead_ms=overhead_ms, **{"class": klass})

        params = dict(p)
        params["_expected"] = expected or []
        out = cascade.run(self._pool, query, qhash, route_id, klass, start, params)

        telemetry.emit("route_completed", route_id=route_id, qhash=qhash,
                       final_tier=out["final_tier"],
                       escalations=out["escalations"], flagged=out["flagged"],
                       attempts=[{k: v for k, v in a.items()} for a in out["attempts"]],
                       total_ms=out["total_ms"], overhead_ms=overhead_ms,
                       config_version=self._config["config_version"],
                       **{"class": klass})

        return {
            "answer": out["answer"],
            "tier": out["final_tier"],
            "escalations": out["escalations"],
            "flagged": out["flagged"],
            "trace": {
                "route_id": route_id, "qhash": qhash, "class": klass,
                "prefilter": pf, "predictor": predictor,
                "start_tier": start, "floor": floor,
                "attempts": out["attempts"], "total_ms": out["total_ms"],
                "router_overhead_ms": overhead_ms,
                "config_version": self._config["config_version"],
            },
        }
