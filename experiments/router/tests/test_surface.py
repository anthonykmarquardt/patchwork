"""Control-surface invariants I1-I10 + the set_config write protocol.

This is the contract spec 0002's tuner writes through — every rejection here
is a patch that can never corrupt a running router."""
import copy
import json

from darkcore import surface


def _cfg(**param_over):
    cfg = copy.deepcopy(surface.DEFAULTS)
    cfg["params"].update(param_over)
    return cfg


def _violating(cfg, tag):
    v = surface.validate(cfg)
    assert any(tag in s for s in v), f"expected {tag} violation, got {v}"


def test_defaults_validate_clean():
    assert surface.validate(surface.DEFAULTS) == []


def test_i1_roster():
    _violating(_cfg(tier_roster=[]), "I1")
    _violating(_cfg(tier_roster=[{"id": "T0", "model": "m", "max_tokens": 8},
                                 {"id": "T0", "model": "m", "max_tokens": 8}]), "I1")
    _violating(_cfg(tier_roster=[{"id": "T0", "model": "", "max_tokens": 8}]), "I1")
    _violating(_cfg(tier_roster=[{"id": "T0", "model": "m", "max_tokens": 0}]), "I1")


def test_i2_unknown_tier_references():
    _violating(_cfg(class_start_map={"default": "T9"}), "I2")
    _violating(_cfg(class_floor={"default": "T9"}), "I2")
    _violating(_cfg(escalation_overrides={"emotional": "T9"}), "I2")


def test_i3_default_required():
    _violating(_cfg(class_start_map={"agentic": "T0"}), "I3")
    _violating(_cfg(class_floor={"emotional": "T1"}), "I3")


def test_i4_start_below_floor():
    _violating(_cfg(class_start_map={"emotional": "T0", "default": "T0"},
                    class_floor={"emotional": "T1", "default": "T0"}), "I4")


def test_i5_lambda_bounds():
    _violating(_cfg(lambda_by_class={"default": -0.1}), "I5")
    _violating(_cfg(lambda_by_class={"default": 2.5}), "I5")
    _violating(_cfg(lambda_by_class={"default": "high"}), "I5")


def test_i6_verifier_config():
    _violating(_cfg(verifier_config={"default": {"rung": 7, "verifier": None}}), "I6")
    # rung 5 <=> verifier null, both directions
    _violating(_cfg(verifier_config={"default": {"rung": 5, "verifier": "next_tier_judge"}}), "I6")
    _violating(_cfg(verifier_config={"default": {"rung": 1, "verifier": "made_up"}}), "I6")


def test_i7_prefilter_rules():
    _violating(_cfg(prefilter_rules=[{"id": "x", "signal": "code_fence_present", "set": {}},
                                     {"id": "x", "signal": "code_fence_present", "set": {}}]), "I7")
    _violating(_cfg(prefilter_rules=[{"id": "x", "signal": "nope", "set": {}}]), "I7")
    _violating(_cfg(prefilter_rules=[{"id": "x", "signal": "code_fence_present",
                                      "set": {"model": "T2"}}]), "I7")


def test_i8_predictor_store_coupling(tmp_path):
    _violating(_cfg(predictor_enabled=True,
                    exemplar_store_ref={"uri": None, "index_version": 0}), "I8")
    _violating(_cfg(exemplar_store_ref={"uri": "/nope/nowhere", "index_version": 1}), "I8")
    ok = _cfg(predictor_enabled=True,
              exemplar_store_ref={"uri": str(tmp_path), "index_version": 1})
    assert surface.validate(ok) == []


def test_i9_cascade_policy():
    base = surface.DEFAULTS["params"]["cascade_policy"]
    _violating(_cfg(cascade_policy={**base, "max_tiers_per_query": 0}), "I9")
    _violating(_cfg(cascade_policy={**base, "max_tiers_per_query": 4}), "I9")
    _violating(_cfg(cascade_policy={**base, "per_query_ms_budget": 0}), "I9")
    _violating(_cfg(cascade_policy={**base, "retry_policy": "yolo"}), "I9")
    _violating(_cfg(cascade_policy={**base, "terminal_failure": "silent_drop"}), "I9")


def test_i10_surface_version_pinned():
    cfg = copy.deepcopy(surface.DEFAULTS)
    cfg["surface_version"] = 2
    _violating(cfg, "I10")


# ------------------------------------------------------- set_config protocol
def test_set_config_ok_bumps_version_and_journals(isolated_surface):
    res = surface.set_config({"lambda_by_class": {"default": 0.5}},
                             base_version=0, actor="tuner", note="test")
    assert res["status"] == "ok" and res["new_version"] == 1
    on_disk = json.loads(isolated_surface["config"].read_text())
    assert on_disk["params"]["lambda_by_class"]["default"] == 0.5
    assert on_disk["updated_by"] == "tuner"
    lines = isolated_surface["journal"].read_text().splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["actor"] == "tuner" and entry["new_version"] == 1
    assert entry["note"] == "test"


def test_set_config_conflict_on_stale_base(isolated_surface):
    assert surface.set_config({}, 0, "operator")["status"] == "ok"
    res = surface.set_config({"predictor_enabled": False}, 0, "tuner")
    assert res["status"] == "conflict" and res["current_version"] == 1


def test_set_config_invalid_writes_nothing(isolated_surface):
    res = surface.set_config({"lambda_by_class": {"default": 99}}, 0, "tuner")
    assert res["status"] == "invalid"
    assert any("I5" in s for s in res["violations"])
    assert not isolated_surface["config"].exists()      # zero partial application
    assert not isolated_surface["journal"].exists()


def test_set_config_unknown_actor_rejected(isolated_surface):
    assert surface.set_config({}, 0, "intruder")["status"] == "invalid"


# -------------------------------------------------------- dark-operable load
def test_load_missing_file_falls_back_to_defaults(isolated_surface):
    cfg, violations = surface.load_config()
    assert violations == [] and cfg["config_version"] == 0


def test_load_corrupt_file_degrades_never_dies(isolated_surface):
    isolated_surface["config"].write_text("{not json")
    cfg, violations = surface.load_config()
    assert cfg["config_version"] == 0            # defaults
    assert violations and "unparseable" in violations[0]


def test_load_invalid_content_degrades_with_violations(isolated_surface):
    bad = copy.deepcopy(surface.DEFAULTS)
    bad["params"]["tier_roster"] = []
    isolated_surface["config"].write_text(json.dumps(bad))
    cfg, violations = surface.load_config()
    assert cfg["config_version"] == 0
    assert any("I1" in s for s in violations)
