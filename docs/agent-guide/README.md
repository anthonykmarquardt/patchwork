# Agent-Guide — Index

> Agent-facing procedure documents. Each file is self-contained — an agent reads
> only the one relevant to its current task. No cross-document dependencies.
>
> These are for AGENTS, not operators. If a procedure expects a human to run it,
> it belongs in a different document.

| Document | Answers | When to Read |
|----------|---------|-------------|
| `continue-handoff.md` | "What's the next step?" | Every session start and end |
| `memory-maintenance.md` | "How do I update MEMORY.md?" | Before and after any significant change |
| `anti-drift.md` | "How do I keep docs and code from diverging?" | Before committing changes |

---

## Quick Reference

```bash
# Session end ritual:
python scripts/agent-tools/update-memory.py --change "Implemented X"
python scripts/agent-tools/update-agents.py --report    # validate refs
python scripts/agent-tools/update-continue.py --new     # scaffold handoff

# Session start ritual:
python scripts/agent-tools/update-continue.py --verify  # validate handoff
python scripts/agent-tools/update-agents.py --report    # validate refs
```
