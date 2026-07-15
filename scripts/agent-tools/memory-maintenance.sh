#!/bin/bash
# memory-maintenance.sh — periodic MEMORY.md freshness pass for patchwork.
# Bumps the "Last updated" line so a stale state table is visible at a glance.
# Silent on success; surfaces errors only. Safe to run from cron.
#
# Profile: any (reads/writes project files, no API calls, no network).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

cd "$PROJECT_ROOT" || { echo "error: patchwork project root not found"; exit 1; }

PY="$(command -v python3 || command -v python)" || { echo "error: no python found"; exit 1; }

"$PY" scripts/agent-tools/update-memory.py --state 2>&1 || {
    echo "update-memory.py failed"
    exit 1
}

# Validate bootstrap references; non-fatal (report only).
"$PY" scripts/agent-tools/update-agents.py --report >/dev/null 2>&1 || {
    echo "warning: doc references unresolved — run update-agents.py"
}

echo "patchwork memory state refreshed."
