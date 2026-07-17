# Patchwork — MEMORY

> **Purpose:** Durable facts about the project — decisions, known issues, resolved questions, and current state. Not a session handoff (that's `CONTINUE.md`).
> **Rule:** AUTO-marked sections are refreshable by script. Manual sections are hand-edited and never touched by tooling.

Last updated: 2026-07-16

---

## Design Decisions

<!-- AUTO:decisions — manual table, refreshed by --change when decisions change -->

| ID | Decision | Status | Date | Rationale |
|----|----------|--------|------|-----------|
| D001 | Qwen2.5 family as primary model candidate | Tentative | 2026-07-14 | Architecture uniformity, shared tokenizer, strong ecosystem |
| D002 | IQ4_XS via GGUF as quantisation baseline | Tentative | 2026-07-14 | Best quality/ratio for available RAM; colibrì also uses int4 |
| D003 | Prototype path: Stack → Ensemble → MoE → Adaptive | Tentative | 2026-07-14 | Stack is fastest to working prototype; reveals bridge behaviour early |
| D004 | Bridge training post-hoc on cached representations | Tentative | 2026-07-14 | Cheapest to experiment with; end-to-end is a refinement (latent-bridge thread) |
| D005 | Routing pillar = data plane (dumb router) + control plane (tuner+orchestrator), decoupled via a hard control surface | Adopted | 2026-07-16 | Difficulty is not cheaply predictable (P1); put intelligence in supervision, not the guess. See docs/routing-architecture.md |
| D006 | Cascade (verify-and-escalate) is the routing spine; verifiers indexed by certificate cost (rungs 0–5); organize classes by verifiability, not topic | Adopted | 2026-07-16 | The confidently-wrong small tier needs a safety net; cascade is efficient only where a cheap certificate exists |
| D007 | Governance is firm-based/hierarchical (quorum is a separate project) | Adopted | 2026-07-16 | Orchestrator supervises subordinate workers |
| D008 | Router models = Bonsai ternary 1.7B/8B/27B on stock mlx_lm (M2 dev); supersedes the Qwen2.5/IQ4_XS candidacy for the routing thread | Adopted | 2026-07-16 | Established by the spark eval work (MODEL-EVAL, bake-offs) |

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
- 2026-07-16 — Routing pillar architected (specs 0001–0003 + docs/routing-architecture.md): data/control-plane split, cascade spine, certificate-rung verifiers, empirical closure (P1 confirmed). Nothing built yet; all specs draft.
- 2026-07-16 — Repo hygiene pass: router experiment README + fixture renames; plans/index.md re-scoped to the (paused) latent-bridge thread.

<!-- /AUTO:changes -->

---

## Architecture Notes (Manual)

- **Two threads under the composition thesis (routing + bridging + tiering):**
  (1) the **routing pillar** — *active*, spec-driven (`specs/0001–0003`,
  `docs/routing-architecture.md`), decisions D005–D008 adopted; (2) the
  **latent-bridge** thread — *paused*, planned in `plans/index.md`, decisions
  D001–D004 tentative. Don't read D001–D004 as current for the routing work.
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
