"""The control surface — specs/0001/control-surface.md v1, as code.

One validator, used by every writer (library, CLI) and by the loader.
Transport = versioned JSON file + atomic rename + append-only journal.
Dark-operable: no file -> shipped defaults; invalid file -> last known-good.
"""
import copy
import json
import os
import time

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "config.json")
JOURNAL_PATH = os.path.join(HERE, "config.journal.jsonl")

SURFACE_VERSION = 1
LAMBDA_MAX = 2.0
VERIFIER_REGISTRY = {"nested_tool_check", "plugback_or_judge", "next_tier_judge"}
SIGNAL_REGISTRY = {
    "tool_roster_present", "code_fence_present",
    "affective_first_person", "reasoning_shape",
}
ACTORS = {"tuner", "orchestrator", "operator", "default"}

DEFAULTS = {
    "surface_version": SURFACE_VERSION,
    "config_version": 0,
    "updated": "2026-07-16T00:00:00Z",
    "updated_by": "default",
    "params": {
        "tier_roster": [
            {"id": "T0", "model": "prism-ml/Ternary-Bonsai-1.7B-mlx-2bit", "max_tokens": 512},
            {"id": "T1", "model": "prism-ml/Ternary-Bonsai-8B-mlx-2bit", "max_tokens": 768},
            {"id": "T2", "model": "prism-ml/Ternary-Bonsai-27B-mlx-2bit", "max_tokens": 1536},
        ],
        "class_start_map": {"agentic": "T0", "reasoning": "T0", "emotional": "T1", "default": "T0"},
        "class_floor": {"emotional": "T1", "default": "T0"},
        "lambda_by_class": {"agentic": 0.40, "reasoning": 0.35, "emotional": 0.20, "default": 0.35},
        "verifier_config": {
            "agentic": {"rung": 0, "verifier": "nested_tool_check", "thresholds": {}},
            "reasoning": {"rung": 1, "verifier": "plugback_or_judge", "thresholds": {}},
            "emotional": {"rung": 5, "verifier": None, "thresholds": {}},  # rung 5 => fixed policy (D5)
            "default": {"rung": 4, "verifier": "next_tier_judge", "thresholds": {}},
        },
        "prefilter_rules": [
            {"id": "tool-list", "signal": "tool_roster_present", "set": {"class": "agentic"}},
            {"id": "code-fence", "signal": "code_fence_present", "set": {"class": "agentic"}},
            {"id": "affective", "signal": "affective_first_person", "set": {"class": "emotional"}},
            {"id": "reasoning-shape", "signal": "reasoning_shape", "set": {"class": "reasoning"}},
        ],
        "exemplar_store_ref": {"uri": None, "index_version": 0},
        "predictor_enabled": False,
        "cascade_policy": {
            "max_tiers_per_query": 3,
            "per_query_ms_budget": 300000,
            "retry_policy": "escalate",
            "skip_start": False,
            "terminal_failure": "emit_flagged",
        },
        "escalation_overrides": {},
    },
}


# ---------------------------------------------------------------- validation
def validate(config):
    """Whole-config check of invariants I1-I10. Returns list of violations."""
    v = []
    p = config.get("params", {})
    if config.get("surface_version") != SURFACE_VERSION:
        v.append(f"I10: surface_version must be {SURFACE_VERSION}")

    roster = p.get("tier_roster", [])
    ids = [t.get("id") for t in roster]
    if not roster:
        v.append("I1: tier_roster empty")
    if len(set(ids)) != len(ids):
        v.append("I1: tier ids not unique")
    for t in roster:
        if not t.get("model") or not isinstance(t.get("max_tokens"), int) or t["max_tokens"] <= 0:
            v.append(f"I1: tier {t.get('id')} malformed")

    def tier_ok(tid):
        return tid in ids

    start, floor = p.get("class_start_map", {}), p.get("class_floor", {})
    for name, m in (("class_start_map", start), ("class_floor", floor)):
        if "default" not in m:
            v.append(f"I3: {name} missing 'default'")
        for c, t in m.items():
            if not tier_ok(t):
                v.append(f"I2: {name}[{c}]={t} not in roster")
    rank = {tid: i for i, tid in enumerate(ids)}
    for c in set(start) | set(floor):
        s = start.get(c, start.get("default"))
        f = floor.get(c, floor.get("default"))
        if s in rank and f in rank and rank[s] < rank[f]:
            v.append(f"I4: start({c})={s} below floor {f}")

    for c, lam in p.get("lambda_by_class", {}).items():
        if not isinstance(lam, (int, float)) or not (0 <= lam <= LAMBDA_MAX):
            v.append(f"I5: lambda[{c}]={lam} outside [0,{LAMBDA_MAX}]")

    for c, vc in p.get("verifier_config", {}).items():
        rung, ver = vc.get("rung"), vc.get("verifier")
        if not isinstance(rung, int) or not (0 <= rung <= 5):
            v.append(f"I6: verifier_config[{c}].rung={rung} outside 0..5")
        if rung == 5 and ver is not None:
            v.append(f"I6: rung 5 requires verifier null ({c})")
        if rung != 5 and ver not in VERIFIER_REGISTRY:
            v.append(f"I6: unknown verifier '{ver}' for {c}")

    rule_ids = [r.get("id") for r in p.get("prefilter_rules", [])]
    if len(set(rule_ids)) != len(rule_ids):
        v.append("I7: prefilter rule ids not unique")
    for r in p.get("prefilter_rules", []):
        if r.get("signal") not in SIGNAL_REGISTRY:
            v.append(f"I7: unknown signal '{r.get('signal')}' in rule {r.get('id')}")
        if set(r.get("set", {})) - {"class", "floor"}:
            v.append(f"I7: rule {r.get('id')} sets illegal fields")

    ref = p.get("exemplar_store_ref", {})
    if p.get("predictor_enabled") and not ref.get("uri"):
        v.append("I8: predictor_enabled requires exemplar_store_ref.uri")
    if ref.get("uri") and not os.path.exists(str(ref["uri"])):
        v.append(f"I8: exemplar_store_ref.uri not resolvable: {ref['uri']}")

    cp = p.get("cascade_policy", {})
    if not (1 <= cp.get("max_tiers_per_query", 0) <= max(len(roster), 1)):
        v.append("I9: max_tiers_per_query outside 1..|roster|")
    if not (isinstance(cp.get("per_query_ms_budget"), (int, float)) and cp["per_query_ms_budget"] > 0):
        v.append("I9: per_query_ms_budget must be > 0")
    if cp.get("retry_policy") not in {"escalate", "retry_once_then_escalate"}:
        v.append("I9: retry_policy invalid")
    if cp.get("terminal_failure") not in {"emit_flagged"}:
        v.append("I9: terminal_failure invalid")

    for c, t in p.get("escalation_overrides", {}).items():
        if not tier_ok(t):
            v.append(f"I2: escalation_overrides[{c}]={t} not in roster")
    return v


# ---------------------------------------------------------------- load / save
def _atomic_write(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f, indent=2)
        f.write("\n")
    os.rename(tmp, path)


def ensure_config():
    """Bootstrap shipped defaults if no config exists (config_version 0)."""
    if not os.path.exists(CONFIG_PATH):
        _atomic_write(CONFIG_PATH, DEFAULTS)
    return CONFIG_PATH


def load_config():
    """Dark-operable load: missing -> defaults; invalid -> defaults + violations.

    Returns (config, violations). Caller logs `config_invalid` when violations
    are non-empty and runs on the fallback.
    """
    if not os.path.exists(CONFIG_PATH):
        return copy.deepcopy(DEFAULTS), []
    try:
        with open(CONFIG_PATH) as f:
            cfg = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        return copy.deepcopy(DEFAULTS), [f"unparseable config: {e}"]
    violations = validate(cfg)
    if violations:
        return copy.deepcopy(DEFAULTS), violations
    return cfg, []


def get_config():
    cfg, _ = load_config()
    return cfg


def config_mtime():
    try:
        return os.stat(CONFIG_PATH).st_mtime_ns
    except OSError:
        return 0


# ---------------------------------------------------------------- set_config
def _merge(base, patch):
    """RFC-7386-style merge patch (null deletes)."""
    out = copy.deepcopy(base)
    for k, val in patch.items():
        if val is None:
            out.pop(k, None)
        elif isinstance(val, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], val)
        else:
            out[k] = copy.deepcopy(val)
    return out


def set_config(patch, base_version, actor, note=""):
    """The one write path. Returns {'status': 'ok'|'conflict'|'invalid', ...}."""
    if actor not in ACTORS:
        return {"status": "invalid", "violations": [f"unknown actor '{actor}'"]}
    current = get_config()
    if current["config_version"] != base_version:
        return {"status": "conflict", "current_version": current["config_version"]}

    candidate = copy.deepcopy(current)
    candidate["params"] = _merge(current["params"], patch)
    candidate["config_version"] = current["config_version"] + 1
    candidate["updated"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    candidate["updated_by"] = actor

    violations = validate(candidate)
    if violations:
        return {"status": "invalid", "violations": violations}

    _atomic_write(CONFIG_PATH, candidate)
    with open(JOURNAL_PATH, "a") as f:
        f.write(json.dumps({
            "ts": candidate["updated"], "actor": actor,
            "base_version": base_version, "new_version": candidate["config_version"],
            "patch": patch, "note": note,
        }) + "\n")
    return {"status": "ok", "new_version": candidate["config_version"]}
