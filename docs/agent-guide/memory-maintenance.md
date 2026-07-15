# Memory Maintenance Procedure

> **Purpose:** How to update MEMORY.md after changes.
> **Location:** `../patchwork/MEMORY.md`
> **Rule:** The AUTO-marked sections are refreshable by script. Manual sections are
> hand-edited and never touched by tooling.

---

## Structure

MEMORY.md uses `<!-- AUTO:<name> -->` and `<!-- /AUTO:<name> -->` markers to
define refreshable regions:

| Marker | Content | Refresh Method |
|--------|---------|---------------|
| `AUTO:state` | Last-updated timestamp | `--state` flag |
| `AUTO:changes` | Dated bullet list of changes | `--change "desc"` flag |
| `AUTO:issues` | Known issues with status | `--issue "desc" "status"` flag |

Everything outside AUTO markers is manual — architecture notes, conventions,
cross-agent notes. These are hand-edited and preserved by the script.

---

## When to Run

### After Any Significant Change

```bash
python scripts/agent-tools/update-memory.py --change "Implemented latent bridge prototype"
```

This appends a dated entry to the Recent Changes list (deduped — running it twice
with the same description produces one entry).

### When a New Issue Surfaces

```bash
python scripts/agent-tools/update-memory.py --issue "Bridge quality at IQ4_XS degraded" "Open"
```

This adds/updates the issue with the given status. Re-running with the same
description updates the status in-place.

### To Bump Freshness (Daily Cron or Ad Hoc)

```bash
python scripts/agent-tools/update-memory.py --state
```

This updates only the "Last updated:" line. The cron wrapper
(`scripts/agent-tools/memory-maintenance.sh`) does this plus validates references.

---

## What Goes Where

### In MEMORY.md (the right home):
- Current system state and phase
- Architecture decisions (why was X designed this way?)
- Key patterns and conventions
- Known issues and their status
- Recent changes (last few days)
- Cross-agent coordination notes

### NOT in MEMORY.md (use other tools):
- Task progress / TODO lists → `todo` tool or session_search
- Temporary state stale in 7 days → not worth documenting
- Error messages from failed builds → transient
- Personal user preferences → Hermes memory
