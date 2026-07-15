# scripts/agent-tools — patchwork self-maintenance

Agent-agnostic tooling for keeping the patchwork project's own docs healthy.
No model calls, no network, read-mostly. Any agent (or the operator) runs these.

| Tool | Does | Run when |
|------|------|----------|
| `update-continue.py` | Scaffold/refresh/verify CONTINUE.md handoff snapshot | Session end; session start |
| `update-memory.py` | Idempotent section-scoped updates to MEMORY.md (`--change`, `--issue`, `--state`) | After any significant change |
| `update-agents.py` | Validates every backtick file path in bootstrap docs still resolves | After editing bootstrap docs; on session start |
| `memory-maintenance.sh` | Cron wrapper: bumps MEMORY.md freshness + validates refs | Daily (cron), or ad hoc |

```bash
# Create a fresh handoff snapshot
python scripts/agent-tools/update-continue.py --new

# Validate references
python scripts/agent-tools/update-agents.py --report

# Record a change / an issue
python scripts/agent-tools/update-memory.py --change "Completed Investigation 0a"
python scripts/agent-tools/update-memory.py --issue "Bridge quality at IQ4_XS degraded" "Open"

# Freshness pass (what cron runs)
bash scripts/agent-tools/memory-maintenance.sh
```

**Design constraints** (match the parent project conventions):
- Scripts resolve the project root from their own location — runnable from any cwd.
- `update-memory.py` is idempotent and edits only between `<!-- AUTO:* -->` markers; manual MEMORY.md sections are never rewritten.
- Standard library only — no third-party deps, nothing to `pip install`.
