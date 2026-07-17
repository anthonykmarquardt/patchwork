"""Layer 1 — deterministic prefilter. No model calls, side-effect free.

Rules come from the control surface (`prefilter_rules`, ordered,
first-match-sets-class); this module implements the signal registry.
Known-brittle by design (P-class in decisions.md): class detection may move
to the predictor once the exemplar store grows. Never the final gate — the
cascade is.
"""
import re

_TOOL_ROSTER = re.compile(r"\btools?\b[^.\n]*?\w+\s*/\s*\w+|\btool calls?\b", re.I)
_AFFECTIVE = [
    "i feel", "i felt", "i'm feeling", "i keep", "i needed to say",
    "passed away", "died", "grief", "grieving", "heartbroken",
    "i hate", "i love", "i'm happy", "i'm sad", "i'm angry", "anxious",
    "my dad", "my mom", "my mother", "my father", "my best friend",
    "broke up", "break up", "divorce", "lonely",
]
_REASONING = [
    "how many", "calculate", "solve", "prove", "what is wrong",
    "why is", "explain the reasoning", "logic", "puzzle", "riddle",
]


def _sig_tool_roster_present(q):
    return bool(_TOOL_ROSTER.search(q))


def _sig_code_fence_present(q):
    return "```" in q


def _sig_affective_first_person(q):
    ql = q.lower()
    return any(cue in ql for cue in _AFFECTIVE)


def _sig_reasoning_shape(q):
    ql = q.lower()
    return any(cue in ql for cue in _REASONING) or (any(c.isdigit() for c in q) and "?" in q)


SIGNALS = {
    "tool_roster_present": _sig_tool_roster_present,
    "code_fence_present": _sig_code_fence_present,
    "affective_first_person": _sig_affective_first_person,
    "reasoning_shape": _sig_reasoning_shape,
}

_TOOL_NAMES = re.compile(r"(?i)\btools?\b[:\s]+((?:\w+\s*/\s*)+\w+)")


def tool_names(q):
    """Tool roster named in the query (for the rung-0 agentic verifier)."""
    m = _TOOL_NAMES.search(q)
    if not m:
        return []
    return [t.strip() for t in m.group(1).split("/") if t.strip()]


def run(query, rules):
    """Apply ordered rules; first match sets class. Returns the prefilter verdict."""
    for rule in rules:
        fn = SIGNALS.get(rule["signal"])
        if fn and fn(query):
            return {
                "class": rule["set"].get("class", "default"),
                "matched_rule": rule["id"],
                "reason": rule["signal"],
            }
    return {"class": "default", "matched_rule": None, "reason": "no_signal"}
