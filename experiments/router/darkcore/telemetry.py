"""Telemetry — repo Runtime Logging standard, PII rule enforced at the sink.

Every event: ts/level/component/event/session_id/pid (+ event fields).
HARD RULE: no raw query or completion content ever enters a log line —
query_hash + derived features only (emotional queries carry disclosures).
Sink: logs/router/<YYYY-MM-DD>.jsonl
"""
import hashlib
import json
import os
import time
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
# DARKCORE_LOG_DIR overrides the in-repo default — required when the package
# is installed outside the patchwork checkout (graduation/spark ownership),
# and used by the test suite for isolation.
LOG_DIR = os.environ.get("DARKCORE_LOG_DIR") or os.path.join(REPO, "logs", "router")

SESSION = uuid.uuid4().hex[:12]
_FORBIDDEN_KEYS = {"query", "prompt", "answer", "completion", "text", "content"}


def query_hash(text):
    return hashlib.sha256(text.encode()).hexdigest()[:12]


def derived_features(text):
    """The only representation of a query that may be logged."""
    return {
        "n_chars": len(text),
        "n_words": len(text.split()),
        "q_marks": text.count("?"),
        "has_code_fence": "```" in text,
        "has_digits": any(ch.isdigit() for ch in text),
    }


def _log_path():
    os.makedirs(LOG_DIR, exist_ok=True)
    return os.path.join(LOG_DIR, time.strftime("%Y-%m-%d") + ".jsonl")


def emit(event, level="info", **fields):
    assert not (_FORBIDDEN_KEYS & set(fields)), \
        f"PII rule: refusing to log content keys {_FORBIDDEN_KEYS & set(fields)}"
    rec = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S")
              + f".{int(time.time() * 1000) % 1000:03d}",
        "level": level,
        "component": "darkcore",
        "event": event,
        "session_id": SESSION,
        "pid": os.getpid(),
        **fields,
    }
    with open(_log_path(), "a") as f:
        f.write(json.dumps(rec) + "\n")
    return rec


def new_route_id():
    return uuid.uuid4().hex[:12]
