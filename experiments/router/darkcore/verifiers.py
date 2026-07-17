"""Verifier registry — indexed by certificate rung (design.md §3, Exp 2).

  nested_tool_check   rung 0  structural; catches T0's nested tool calls
  plugback_or_judge   rung 1  ground-truth check when the caller supplies one
                              (bench mode / checkable tasks), else next-tier judge
  next_tier_judge     rung 4  verdict-only pass by the escalation target; its
                              load cost folds into the escalation it precedes
  (emotional)         rung 5  NO verifier — D5 fixed policy, floor at T1

Verdicts: (passed: bool, detail: dict). detail is telemetry-safe (no content).
An unparseable judge verdict counts as FAIL — escalate conservatively.
"""
import re

from . import prefilter

_DEFAULT_TOOLS = ["run_shell", "read_file", "http_get", "send_slack"]
_PASS = re.compile(r"(?i)\bPASS\b")
_FAIL = re.compile(r"(?i)\bFAIL\b")

JUDGE_MAX_TOKENS = 512  # T2 thinks; leave room for the verdict after the think

# ---- rung-0 argument-shape table (bench v0.1, BENCH-REPORT rec #1) ----------
# The v0 S1 failure: T0 emitted `http_get /etc/nginx/nginx.conf` — well-formed,
# semantically absurd. Shape classes let rung 0 catch CLEAR tool/argument
# mismatches while staying deterministic and model-free. Unknown tools are
# unconstrained. (Candidate control-surface data for the tuner later.)
_ARG_SHAPE = {
    "http_get": "url", "curl": "url",
    "read_file": "path",
    "dig": "host",
}
_LOOKS_URL = re.compile(r"^['\"]?\w+://")
_LOOKS_PATH = re.compile(r"^['\"]?/[\w.\-/]*")


def _shape_violation(tool, arg):
    shape = _ARG_SHAPE.get(tool)
    arg = arg.strip()
    if not shape or not arg:
        return None
    if shape == "url" and _LOOKS_PATH.match(arg) and not _LOOKS_URL.match(arg):
        return f"{tool} given filesystem path"
    if shape in ("path", "host") and _LOOKS_URL.match(arg):
        return f"{tool} given URL"
    return None


def nested_tool_check(query, answer, pool, tier, ctx):
    """Rung 0, two structural checks:
    (a) nesting — a tool call inside another call's arguments, the original
        T0 signature (run_shell("http_get(...)"));
    (b) argument shape — a tool fed an argument class it cannot accept, in
        either call syntax `tool(arg)` or command syntax `tool arg`."""
    tools = prefilter.tool_names(query) or _DEFAULT_TOOLS
    alts = "|".join(map(re.escape, tools))
    nested, shape_viols = 0, []
    for m in re.finditer(r"(%s)\s*\(([^)]*)\)" % alts, answer):
        if any(f"{t}(" in m.group(2) for t in tools):
            nested += 1
        v = _shape_violation(m.group(1), m.group(2))
        if v:
            shape_viols.append(v)
    for m in re.finditer(r"(?m)^\s*(%s)\s+(\S+)" % alts, answer):
        v = _shape_violation(m.group(1), m.group(2))
        if v:
            shape_viols.append(v)
    ok = nested == 0 and not shape_viols
    return ok, {"rung": 0, "check": "nested_tool+arg_shape",
                "nested_calls": nested, "shape_violations": len(shape_viols),
                "shape_detail": shape_viols[:4], "verify_ms": 0.0}


def plugback(query, answer, pool, tier, ctx):
    """Rung 1: caller-supplied ground truth (expected substrings, all required)."""
    expected = ctx.get("expected") or []
    missing = [i for i, e in enumerate(expected) if e.lower() not in answer.lower()]
    return not missing, {"rung": 1, "check": "plugback",
                         "expected_n": len(expected), "missing_n": len(missing),
                         "verify_ms": 0.0}


def next_tier_judge(query, answer, pool, tier, ctx):
    """Rung 4: verdict-only pass by the next tier up. If there is no next tier
    we're terminal anyway — auto-pass (the cascade handles terminal failure)."""
    judge = pool.next_tier(tier)
    if judge is None:
        return True, {"rung": 4, "check": "judge", "judge_tier": None,
                      "note": "terminal_tier_no_judge", "verify_ms": 0.0}
    prompt = (
        "You are a strict verifier. Judge whether the ANSWER below correctly and "
        "adequately resolves the QUESTION. Respond with exactly one word: "
        "PASS or FAIL.\n\n"
        f"QUESTION:\n{query}\n\nANSWER:\n{answer}\n\nVerdict (PASS or FAIL):"
    )
    r = pool.generate(judge, prompt, max_tokens=JUDGE_MAX_TOKENS)
    text = r["answer"]
    if _PASS.search(text) and not _FAIL.search(text):
        verdict = True
    elif _FAIL.search(text):
        verdict = False
    else:
        verdict = False  # unparseable -> conservative escalate
    return verdict, {"rung": 4, "check": "judge", "judge_tier": judge,
                     "judge_tokens": r["tokens"], "judge_load_ms": r["load_ms"],
                     "verify_ms": r["load_ms"] + r["gen_ms"],
                     "parseable": bool(_PASS.search(text) or _FAIL.search(text))}


def plugback_or_judge(query, answer, pool, tier, ctx):
    if ctx.get("expected"):
        return plugback(query, answer, pool, tier, ctx)
    return next_tier_judge(query, answer, pool, tier, ctx)


REGISTRY = {
    "nested_tool_check": nested_tool_check,
    "plugback_or_judge": plugback_or_judge,
    "next_tier_judge": next_tier_judge,
}
