# Patchwork — CONTINUE.md

> **Handoff snapshot.** Read this first when resuming work in a new session.
> **Rule:** Overwrite at end of session. Never append. This is a snapshot, not a history.

---

## Bootstrap Sequence (Do This First, In Order)

```bash
cd ../patchwork
git status                              # expected: (clean)
git log --oneline -5                    # expected: e9845a7... (initial commit on vibes)

python3 scripts/agent-tools/update-continue.py --verify   # Validate handoff
python3 scripts/agent-tools/update-agents.py --report     # Validate doc refs
```

---

## Current Status

**Phase:** 0 (Foundations — early exploration)
**Completed:** Workspace bootstrapped with full project-agent-interface (v1.3.0 patterns).
- AGENTS.md, MEMORY.md, CONTINUE.md, plans/index.md — all written
- Scripts: update-continue.py, update-memory.py, update-agents.py, memory-maintenance.sh — all built and verified
- Agent-guide: continue-handoff.md, memory-maintenance.md, anti-drift.md — all written
- Pre-commit hook installed (subtree-scoped, no-op unless patchwork/ staged)
- Project-agent-interface skill amended to v1.3.0 with 6 new patterns from quorum

---

## What Was Last Built / Decided

- [x] Project scoped (modular model composition runtime, Qwen2.5 family, IQ4_XS, 16 GB target)
- [x] Directory structure created (scripts/agent-tools/, scripts/hooks/, docs/agent-guide/)
- [x] AGENTS.md — workspace bootstrap with open questions and workflow
- [x] plans/index.md — 18k-word master planning document with design alternatives, 12 investigations, risk assessment
- [x] update-continue.py — CONTINUE.md scaffold/verify with test -f exit-code fix
- [x] update-memory.py — idempotent AUTO marker MEMORY.md updater (borrowed from quorum)
- [x] update-agents.py — file reference validator
- [x] memory-maintenance.sh — cron wrapper
- [x] pre-commit hook — subtree-scoped commit gate
- [x] Agent-guide docs (continue-handoff, memory-maintenance, anti-drift)
- [x] Skill amend: project-agent-interface → v1.3.0 with Pattern E (check-drift.py), Pattern F (pre-commit hook), AUTO marker convention, DESIGN_LOG.md supplement, quorum-interface-patterns.md reference
- [x] Template fix: update-continue.py now handles test -f exit-code-based bootstrap checks

---

## What's Next (Prioritized)

### Tier 1 — Already Spec'd, Just Needs Building
Pick any unchecked Phase 0 investigation from plans/index.md §5:

- [ ] 0a: Verify Qwen2.5 family compatibility — download 1.5B variants, run CKA
- [ ] 0b: Measure cold-swap latency for Qwen2.5-7B GGUF from NVMe
- [ ] 0c: Survey existing cross-model inference frameworks (llama.cpp, MLX, MergeKit, FrankenMoE)
- [ ] 0d: Evaluate tokenizer compatibility across model families
- [ ] 0e: Measure representation similarity between Qwen2.5 base/coder/instruct (CKA)

### Tier 2 — High Value, Needs Design
- Phase 1: Latent bridge prototype (requires 0a/0b/0c first)
- Phase 2: Routing prototype

### Quick Wins (30 min or less)
- Install the pre-commit hook: `git config core.hooksPath patchwork/scripts/hooks`

---

## Open Questions / Blockers

None currently. Every Phase 0 investigation is unstarted.

## Gotchas

- `test -f X` commands in bootstrap sequences signal via exit code, not stdout. update-continue.py's `_bootstrap_check_ok()` handles this — the template was fixed in the skill with this same pattern.
- Model downloads from HuggingFace need `huggingface-cli login`.
- IQ4_XS quantization requires llama.cpp's `./quantize` or equivalent MLX path.
- The quorum project (`../quorum/`) is the reference implementation for all these patterns — consult its check-drift.py, DESIGN_LOG.md, and ARCHITECTURE.md.

## Key File Paths

| Path | Purpose | When |
|------|---------|------|
| `AGENTS.md` | Workspace bootstrap | First read |
| `plans/index.md` | Master planning doc | Before any investigation |
| `MEMORY.md` | Project state | Every session |
| `CONTINUE.md` | Handoff snapshot | Every session start/end |
| `docs/references.md` | External papers/projects | As needed |
| `scripts/agent-tools/` | Maintenance tools | Session end ritual |

## Key Decisions Made (and Why)

| ID | Decision | Status |
|----|----------|--------|
| D001 | Qwen2.5 family as primary model candidate | Tentative |
| D002 | IQ4_XS via GGUF as quantisation baseline | Tentative |
| D003 | Prototype path: Stack → Ensemble → MoE → Adaptive | Tentative |
| D004 | Bridge training post-hoc on cached representations | Tentative |

## Agent Handoff Checklist

- [x] Update `What's Next` with next steps
- [x] Log completion in `What Was Last Built`
- [x] Record new gotchas
- [x] Run `python scripts/agent-tools/update-agents.py --report` (0 issues)
- [x] Run `python scripts/agent-tools/update-continue.py --verify` (all pass)
- [x] **Overwrite this file** — not append
