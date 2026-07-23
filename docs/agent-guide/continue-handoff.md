# CONTINUE.md Handoff Procedure

> **Purpose:** How operators and agents use CONTINUE.md as a handoff mechanism.
> **Location:** `./CONTINUE.md`
> **Rule:** OVERWRITE at end of session. Never append. Snapshot, not history.

---

## Why It Exists

CONTINUE.md answers one question: **"What's the immediate next step?"**

When a project spans multiple sessions — context compaction, days between sessions,
multiple agents — both the operator and a fresh agent need to pick up exactly where
work stopped, without re-reading the entire conversation history.

CONTINUE.md is NOT:
- A changelog (that's `git log`)
- A project tracker (that's `MEMORY.md`'s state table)
- A todo list (that's the `todo` tool)

---

## Lifecycle

### At Session End (Agent)

1. **Gather current state** — what phase, what was built, what broke
2. **Update `What's Next`** — prioritise next steps
3. **Record gotchas** — non-obvious lessons a fresh agent won't know
4. **Update decision log** — new architecture choices
5. **Overwrite CONTINUE.md** — replace all stale content

```bash
python scripts/agent-tools/update-continue.py --new
```

### At Session Start (Agent)

1. **Open CONTINUE.md first** — before AGENTS.md, before MEMORY.md
2. **Run the bootstrap sequence** — verify environment matches snapshot
3. **If anything diverges → STOP** — tell the operator
4. **If everything matches → begin work** — `What's Next` tells you what to do

```bash
python scripts/agent-tools/update-continue.py --verify
python scripts/agent-tools/update-agents.py --report
```

### Between Sessions (Operator)

When asking "where were we?", read CONTINUE.md. The `What's Next` section answers
it without scrolling through session history.

---

## How to Write a Good Snapshot

- **Be specific** — "Phase 0: run Investigation 0a" not "keep working"
- **Prioritise** — Tier 1 (spec'd, needs build) > Tier 2 (needs design) > Quick Wins
- **Include gotchas** — a 45-minute debug is a 2-minute fix if written down
- **Keep bootstrap current** — stale bootstrap is worse than none

---

## Integration with Other Docs

| Document | Relationship to CONTINUE.md |
|----------|---------------------------|
| **AGENTS.md** | Mission + architecture. CONTINUE.md = immediate next step within that mission. |
| **MEMORY.md** | Durable state. CONTINUE.md = next TASK, not current state. |
| **plans/index.md** | Design space + investigation checklist. CONTINUE.md = which investigation to run. |

---

## Template Structure

See `scripts/agent-tools/update-continue.py` TEMPLATE for the full structure.
Required sections:
- Bootstrap Sequence
- Current Status
- What's Next (Prioritized)
- Open Questions / Blockers
- Gotchas
- Key File Paths
- Key Decisions Made
- Agent Handoff Checklist

---

## Pitfalls

### Appending Instead of Overwriting
CONTINUE.md is not a log. Append and a fresh agent must read 10 stale sessions
to find the current one. Overwrite completely.

### Stale Bootstrap Sequence
If startup commands change and the bootstrap sequence isn't updated, the agent
fails on step 1. Fix: update bootstrap in the same commit as the change.

### Gotchas That Go Unwritten
The cost is highest for a fresh agent. Write gotchas in the session that
discovers them. A 45-minute debug is a 2-minute fix if documented.

### Missing CONTINUE.md in the Workflow
If AGENTS.md doesn't list CONTINUE.md as the first file to read, it's invisible.
Patchwork's AGENTS.md lists it as step 0.
