# Anti-Drift Procedure

> **Purpose:** Keep patchwork's docs and code from silently diverging.
> **Location:** `../patchwork/`
> **Principle:** Every design decision should be findable, and every findable
> decision should still be true.

---

## The Problem

Bootstrap documents (AGENTS.md, MEMORY.md, plans/index.md) go stale when:
- Files are moved/renamed but doc references aren't updated
- Architecture decisions change but aren't recorded
- Investigations complete but the checklist isn't checked off

A stale bootstrap is worse than none — it actively misleads a fresh agent into
working on wrong assumptions.

---

## The Enforcement

| Layer | Tool | When |
|-------|------|------|
| **Reference validation** | `update-agents.py` | Every session start; after editing bootstrap docs; pre-commit |
| **Freshness bump** | `update-memory.py --state` | Daily cron via `memory-maintenance.sh` |
| **Session handoff** | CONTINUE.md overwrite | Every session end |

---

## The Ritual

### Before Committing

```bash
python scripts/agent-tools/update-agents.py --report
```

If any backtick-quoted file path in AGENTS.md, MEMORY.md, CONTINUE.md, or
plans/index.md resolves to nothing, fix it. The script exits 1 if broken.

The pre-commit hook (`scripts/hooks/pre-commit`) does this automatically on
every commit (the repo root is patchwork, so all staged files count). Install it:

```bash
# From the patchwork repo root:
git config core.hooksPath scripts/hooks
```

### After Any Design Decision

If you made a choice between alternatives that involved trade-offs:
1. Add it to `plans/index.md` §6 Design Decision Log (D-box format)
2. Update `MEMORY.md`'s Design Decisions section
3. Log with `update-memory.py --change "Decision: chose X over Y because Z"`

### After Investigation Completes

1. Write findings to `research/`
2. Check off the investigation in `plans/index.md` §5 Agent Handoff (§2 checklist)
3. Update any affected sections of `plans/index.md`
4. Run `python scripts/agent-tools/update-agents.py --report` to validate refs
5. Run `python scripts/agent-tools/update-memory.py --change "Completed Inv X"`

---

## What Counts as Drift

- A backtick-quoted path in any bootstrap doc points to a file that doesn't exist
- MEMORY.md's "Last updated" is older than 30 days (flagged by staleness check)
- CONTINUE.md's bootstrap sequence commands fail (detected by `--verify`)
- An investigation in `plans/index.md` is complete but not checked off
- A decision in `plans/index.md` §6 is inconsistent with what was actually built
