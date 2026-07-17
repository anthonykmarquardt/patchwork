"""dark-core — spec 0001's standalone data-plane router.

The dumb, fast, dark-operable half of the patchwork routing architecture:
prefilter → (predictor, off at n=0) → cascade(verify+escalate), emitting
PII-safe JSONL telemetry, actuated only through the control surface
(surface.py == specs/0001/control-surface.md v1).

Intelligence lives in the control plane (0002 tuner, 0003 orchestrator),
not here. Keep it dumb.
"""
__version__ = "0.1.0"
