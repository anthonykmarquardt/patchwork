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


def _issue_entries(body: str) -> list[list[str]]:
    """Split the issues body into atomic entries: a top-level '- ' bullet plus
    its indented continuation lines. Blank/placeholder lines between entries
    are dropped; continuation lines are never separated from their bullet
    (the 2026-07-18 regression: line-level handling + sorted() shredded every
    multi-line entry)."""
    entries: list[list[str]] = []
    cur: list[str] = []
    for ln in body.splitlines():
        if ln.startswith("- "):
            if cur:
                entries.append(cur)
            cur = [ln]
        elif cur and ln.strip() and not ln.strip().startswith("_"):
            cur.append(ln)
    if cur:
        entries.append(cur)
    return entries


def _norm(s: str) -> str:
    return re.sub(r"[*_`]", "", s).lower().strip()


def add_issue(text: str, desc: str, status: str) -> str:
    """Add `- desc — **status**`, or replace the whole entry whose bullet
    starts with desc (markdown emphasis ignored). Entry order is preserved;
    entries this call doesn't match are untouched."""
    entries = _issue_entries(_section_body(text, "issues"))
    new_entry = [f"- {desc} — **{status}**"]
    key = _norm(f"- {desc}")
    replaced = False
    out: list[list[str]] = []
    for e in entries:
        if not replaced and _norm(e[0]).startswith(key):
            out.append(new_entry)
            replaced = True
        else:
            out.append(e)
    if not replaced:
        out.append(new_entry)
    new_body = "\n".join("\n".join(e) for e in out)
    return _bump_timestamp(_replace_section(text, "issues", new_body))


_SELFTEST_DOC = """Last updated: 2000-01-01

<!-- AUTO:issues — refreshable -->

- **B-issue (multi-line) — OPEN:** first line of prose
  continuation line one (indented)
  continuation line two. `path/to/file.py`.
- **A-issue — FIXED:** alphabetically earlier; must stay SECOND.
  its continuation line.

<!-- /AUTO:issues -->
"""


def selftest() -> None:
    out = add_issue(_SELFTEST_DOC, "C-issue", "Open")
    entries = _issue_entries(_section_body(out, "issues"))
    assert [e[0].split(" ")[1] for e in entries] == ["**B-issue", "**A-issue", "C-issue"], \
        "order not preserved (sorted regression?)"
    assert len(entries[0]) == 3 and len(entries[1]) == 2, "continuation lines lost"
    out2 = add_issue(out, "C-issue", "Open")
    assert _section_body(out2, "issues") == _section_body(out, "issues"), "not idempotent"
    out3 = add_issue(out, "B-issue (multi-line)", "Closed")
    entries3 = _issue_entries(_section_body(out3, "issues"))
    assert entries3[0] == ["- B-issue (multi-line) — **Closed**"], "in-place update failed"
    assert entries3[1][0].startswith("- **A-issue"), "neighbor entry disturbed"
    print("✅ selftest passed.")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--change", metavar="DESC", help="append a dated Recent Changes line")
    ap.add_argument("--issue", nargs=2, metavar=("DESC", "STATUS"), help="add/update a known issue")
    ap.add_argument("--state", action="store_true", help="bump the Last updated line")
    ap.add_argument("--selftest", action="store_true",
                    help="run the multi-line-entry regression checks and exit")
    args = ap.parse_args()

    if args.selftest:
        selftest()
        sys.exit(0)

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
