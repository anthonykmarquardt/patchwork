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
        self._prior = self._build_prior(cfg)
        self._config = cfg
        self._mtime = surface.config_mtime()
        telemetry.emit("config_loaded", config_version=cfg["config_version"],
                       updated_by=cfg.get("updated_by"),
                       predictor="class_prior" if self._prior else "off")

    def _build_prior(self, cfg):
        """Class-prior predictor (P1: class only). Eager-warm at init so the
        first query doesn't pay the embedder load."""
        p = cfg["params"]
        ref = p.get("exemplar_store_ref", {})
        if not (p.get("predictor_enabled") and ref.get("uri")):
            return None
        prev = getattr(self, "_prior", None)
        if prev is not None and prev.index_version == ref.get("index_version"):
            return prev  # unchanged snapshot — keep the warm embedder
        try:
            from .predictor import ClassPrior
            prior = ClassPrior(ref["uri"]).warm()
            telemetry.emit("exemplar_store_loaded", uri=ref["uri"],
                           index_version=prior.index_version, n=len(prior.ids))
            return prior
        except Exception as e:  # dark-operable: predictor failure never blocks
            telemetry.emit("predictor_disabled", level="warn",
                           error_type=type(e).__name__, message=str(e)[:200])
            return None

    def _maybe_reload(self):
        if surface.config_mtime() != self._mtime:
            self._reload()

    def route(self, query, expected=None, on_event=None):
        """The one public entry. `expected` = optional rung-1 ground truth
        (bench mode / checkable callers). `on_event(name, **fields)` = optional
        live status callback so callers can see climbs (never blocks routing)."""
        self._maybe_reload()
        p = self._config["params"]
        route_id = telemetry.new_route_id()
        qhash = telemetry.query_hash(query)
        t0 = time.perf_counter()

        # Layer arbitration (journal Episode 6, step 1): deterministic rules
        # win when they fire (high precision); the embedder class-prior owns
        # the rest; low confidence abstains to "default".
        pf = prefilter.run(query, p["prefilter_rules"])
        klass = pf["class"]
        predictor = {"enabled": self._prior is not None, "predicted_tier": None}
        if klass == "default" and self._prior is not None:
            try:
                verdict = self._prior.classify(query)
                predictor.update(verdict)
                klass = verdict["class"]
            except Exception as e:  # never let the prior break the data path
                telemetry.emit("predictor_error", level="warn", route_id=route_id,
                               error_type=type(e).__name__, message=str(e)[:200])

        start = p["class_start_map"].get(klass, p["class_start_map"]["default"])
        floor = p["class_floor"].get(klass, p["class_floor"]["default"])
        order = [t["id"] for t in p["tier_roster"]]
        # skip_start (step 2): a query nobody could class is judge-chain-bound —
        # don't start it at the bottom of the ladder.
        if (p["cascade_policy"].get("skip_start") and klass == "default"
                and order.index(start) + 1 < len(order)):
            start = order[order.index(start) + 1]
            pf = {**pf, "skip_start_applied": True}
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
        out = cascade.run(self._pool, query, qhash, route_id, klass, start, params,
                          on_event=on_event)

        # Causally-honest rewarm: the route that loaded the exclusive tier
        # (and thereby paged out the embedder) pays the re-page cost here, at
        # its own tail — never the next query's overhead window.
        if self._pool.exclusive_used and self._prior is not None:
            t_rw = time.perf_counter()
            try:
                self._prior.embed("rewarm")
            except Exception:  # noqa: BLE001 — rewarm is best-effort
                pass
            self._pool.exclusive_used = False
            telemetry.emit("prior_rewarmed", route_id=route_id,
                           rewarm_ms=round((time.perf_counter() - t_rw) * 1000, 1))

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
