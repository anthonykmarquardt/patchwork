# Patchwork — MEMORY

> **Purpose:** Durable facts about the project — decisions, known issues, resolved questions, and current state. Not a session handoff (that's `CONTINUE.md`).
> **Rule:** AUTO-marked sections are refreshable by script. Manual sections are hand-edited and never touched by tooling.

Last updated: 2026-07-14

---

## Design Decisions

<!-- AUTO:decisions — manual table, refreshed by --change when decisions change -->

| ID | Decision | Status | Date | Rationale |
|----|----------|--------|------|-----------|
| D001 | Qwen2.5 family as primary model candidate | Tentative | 2026-07-14 | Architecture uniformity, shared tokenizer, strong ecosystem |
| D002 | IQ4_XS via GGUF as quantisation baseline | Tentative | 2026-07-14 | Best quality/ratio for available RAM; colibrì also uses int4 |
| D003 | Prototype path: Stack → Ensemble → MoE → Adaptive | Tentative | 2026-07-14 | Stack is fastest to working prototype; reveals bridge behaviour early |
| D004 | Bridge training post-hoc on cached representations | Tentative | 2026-07-14 | Cheapest to experiment with; end-to-end is a refinement |

<!-- /AUTO:decisions -->

---

## Known Issues

<!-- AUTO:issues — refreshable by scripts/agent-tools/update-memory.py --issue -->

- *(none yet — project is new)*

<!-- /AUTO:issues -->

---

## Recent Changes

<!-- AUTO:changes — appended by scripts/agent-tools/update-memory.py --change -->

- 2026-07-14 — Project scaffolded: AGENTS.md, MEMORY.md, CONTINUE.md, plans/index.md
- 2026-07-14 — Agent interface built: agent-tools scripts (update-continue, update-memory, update-agents, memory-maintenance), agent-guide docs (continue-handoff, memory-maintenance, anti-drift), pre-commit hook

<!-- /AUTO:changes -->

---

## Architecture Notes (Manual)

- **Project is Phase 0** — early exploration, model selection, research. No architecture decisions locked in beyond tentative D001-D004.
- **Parent workspace:** `../` — inherits vibes-level AGENTS.md conventions.
- **Cross-reference:** quorum (`../quorum/`) is a sibling project with a very similar agent-interface implementation. Consult its DESIGN_LOG.md and anti-drift patterns.
- **Three-layer model for composition:** Routing (what dispatches), Bridge (how state flows between models), Tiering (which modules are loaded).

## Key Conventions

- Agent-facing docs in `docs/agent-guide/` — never operator runbooks
- Maintenance scripts in `scripts/agent-tools/` — agent-agnostic, stdlib only
- Research findings in `research/` — negative results are valuable
- Prototypes in `experiments/` — documented via README
- All model downloads from HuggingFace — may need `huggingface-cli login`
- IQ4_XS quantisation via llama.cpp `./quantize` or equivalent MLX path
