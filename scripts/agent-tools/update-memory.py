#!/usr/bin/env python3
"""update-memory.py — Idempotent, section-scoped updater for MEMORY.md.

Operates only on the regions between `<!-- AUTO:<name> -->` and
`<!-- /AUTO:<name> -->` markers. Never rewrites the whole file and never
touches manual sections. Running the same command twice produces the same
result.

Usage:
    python scripts/agent-tools/update-memory.py --change "Built X: desc"
    python scripts/agent-tools/update-memory.py --issue "Bug Y: desc" "Open"
    python scripts/agent-tools/update-memory.py --state          # refresh timestamp

Sections:
    AUTO:changes  — dated bullet list, newest appended (deduped)
    AUTO:issues   — one bullet per issue; re-running with same issue updates status
    AUTO:state    — only the "Last updated" line is auto-bumped here

Pattern from quorum — agent-agnostic, no model calls, no network.
"""

from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MEMORY = PROJECT_ROOT / "MEMORY.md"


def _today() -> str:
    return dt.date.today().isoformat()


def _replace_section(text: str, name: str, new_body: str) -> str:
    open_m = f"<!-- AUTO:{name}"
    close_m = f"<!-- /AUTO:{name} -->"
    pattern = re.compile(
        re.escape(open_m) + r".*?-->\n(.*?)\n" + re.escape(close_m),
        re.DOTALL,
    )
    if not pattern.search(text):
        raise SystemExit(f"error: AUTO:{name} markers not found in MEMORY.md")

    def _sub(m: re.Match) -> str:
        head = m.group(0).split("-->", 1)[0] + "-->"
        return f"{head}\n{new_body}\n{close_m}"

    return pattern.sub(_sub, text, count=1)


def _section_body(text: str, name: str) -> str:
    m = re.search(
        re.escape(f"<!-- AUTO:{name}") + r".*?-->\n(.*?)\n" + re.escape(f"<!-- /AUTO:{name} -->"),
        text,
        re.DOTALL,
    )
    return m.group(1) if m else ""


def _bump_timestamp(text: str) -> str:
    return re.sub(r"(?m)^Last updated: .*$", f"Last updated: {_today()}", text, count=1)


def add_change(text: str, desc: str) -> str:
    line = f"- {_today()} — {desc}"
    body = _section_body(text, "changes").strip()
    existing = [ln for ln in body.splitlines() if ln.strip()]
    if line in existing:
        return text
    existing = [ln for ln in existing if not ln.strip().startswith("_")]
    existing.append(line)
    return _bump_timestamp(_replace_section(text, "changes", "\n".join(existing)))


def add_issue(text: str, desc: str, status: str) -> str:
    body = _section_body(text, "issues").strip()
    lines = [ln for ln in body.splitlines() if ln.strip() and not ln.strip().startswith("_")]
    prefix = f"- {desc} — "
    lines = [ln for ln in lines if not ln.startswith(prefix)]
    lines.append(f"{prefix}**{status}**")
    return _bump_timestamp(_replace_section(text, "issues", "\n".join(sorted(lines))))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--change", metavar="DESC", help="append a dated Recent Changes line")
    ap.add_argument("--issue", nargs=2, metavar=("DESC", "STATUS"), help="add/update a known issue")
    ap.add_argument("--state", action="store_true", help="bump the Last updated line")
    args = ap.parse_args()

    if not (args.change or args.issue or args.state):
        ap.print_help()
        sys.exit(2)

    text = MEMORY.read_text()
    if args.change:
        text = add_change(text, args.change)
    if args.issue:
        text = add_issue(text, args.issue[0], args.issue[1])
    if args.state:
        text = _bump_timestamp(text)

    MEMORY.write_text(text)
    print(f"✅ MEMORY.md updated ({_today()}).")


if __name__ == "__main__":
    main()
