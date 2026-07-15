#!/usr/bin/env python3
"""update-agents.py — Validate that AGENTS.md file references still resolve.

Scans AGENTS.md (and other bootstrap files below) for backtick-quoted file
paths and checks each one still exists on disk. A bootstrap doc that points
at a moved/renamed file is actively misleading to a fresh agent.

Usage:
    python scripts/agent-tools/update-agents.py            # validate, print report
    python scripts/agent-tools/update-agents.py --report   # same (explicit)

Exit code 0 = all references valid; 1 = at least one missing.

Agent-agnostic: no model calls, no network, read-only.
Part of the patchwork self-maintenance toolkit.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

DOC_FILES = [
    PROJECT_ROOT / "AGENTS.md",
    PROJECT_ROOT / "MEMORY.md",
    PROJECT_ROOT / "CONTINUE.md",
    PROJECT_ROOT / "plans" / "index.md",
]

REF_PATTERN = re.compile(r"`([^`]+)`")


def _looks_like_path(ref: str) -> bool:
    if not ("/" in ref or ref.startswith("~/")):
        return False
    if len(ref) > 100:
        return False
    if ref.startswith(("├", "│", "└", "─")):
        return False
    if "|" in ref or "->" in ref or "→" in ref:
        return False
    if any(c in ref for c in "<>*"):
        return False
    if any(ord(c) > 127 for c in ref):
        return False
    if ref.rstrip("/").startswith("logs/"):
        return False
    if " " in ref.strip():
        return False
    if ref.startswith("./") and ref.count("/") <= 2:  # tool/command refs like ./quantize, not file paths
        return False
    return True


def _resolve(ref: str) -> Path | None:
    if ref.startswith("~/"):
        p = Path.home() / ref[2:]
        return p if p.exists() else None
    if ref.startswith("/"):
        p = Path(ref)
        return p if p.exists() else None

    rel = ref.rstrip("/")
    if rel == PROJECT_ROOT.name:
        return PROJECT_ROOT
    for candidate in (PROJECT_ROOT / rel, PROJECT_ROOT / rel.removeprefix("patchwork/")):
        if candidate.exists():
            return candidate
    return None


def validate() -> dict[str, dict]:
    results: dict[str, dict] = {}
    for path in DOC_FILES:
        entry = {"exists": path.exists(), "missing_refs": []}
        if path.exists():
            content = path.read_text()
            refs = [m.group(1) for m in REF_PATTERN.finditer(content)]
            entry["missing_refs"] = sorted(
                {r for r in refs if _looks_like_path(r) and _resolve(r) is None}
            )
        results[str(path.relative_to(PROJECT_ROOT))] = entry
    return results


def print_report(results: dict[str, dict]) -> int:
    total_missing = 0
    for name, data in results.items():
        print(f"\n{'=' * 56}\n  {name}\n{'=' * 56}")
        if not data["exists"]:
            print("  ❌ MISSING")
            total_missing += 1
            continue
        if data["missing_refs"]:
            print(f"  ⚠️  {len(data['missing_refs'])} unresolved reference(s):")
            for ref in data["missing_refs"]:
                print(f"      - {ref}")
            total_missing += len(data["missing_refs"])
        else:
            print("  ✅ all references valid")
    print(f"\n{'=' * 56}\nSUMMARY: {total_missing} issue(s)\n")
    return total_missing


def main() -> None:
    total = print_report(validate())
    sys.exit(1 if total else 0)


if __name__ == "__main__":
    main()
