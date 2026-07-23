# Patchwork — MEMORY

> **Purpose:** Durable facts about the project — decisions, known issues, resolved questions, and current state. Not a session handoff (that's `CONTINUE.md`).
> **Rule:** AUTO-marked sections are refreshable by script. Manual sections are hand-edited and never touched by tooling.

Last updated: 2026-07-19

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
| D009 | Require a project-entry GitHub authentication preflight for `anthony-mqdt-labs`; keep commit identity repository-local | Adopted | 2026-07-20 | Prevents the shared GitHub CLI session and Git author identity from leaking across sibling projects |

<!-- /AUTO:decisions -->

---

## Known Issues

<!-- AUTO:issues — refreshable by scripts/agent-tools/update-memory.py --issue -->

- **V-struct (S1 gap) — FIXED in bench v0.1:** rung-0 gained an argument-shape
  table; A1 now escalates T0✗→T1✓ and **all five spec thresholds pass**
  (quality 0.900, speedup 1.72×). Residual: rung-0 stays blind to *strategy*
  (A4) — by design. `experiments/router/BENCH-REPORT.md`.
- **P-class lexicon brittleness — FIXED in v0.2:** class detection moved to
  the embedder (class-prior, 12/12 incl. E3); rules keep precedence when they
  fire; low confidence abstains.
- **S4 overhead budget — RESOLVED 2026-07-17 (option b):** S4 gates on
  overhead < 1% of route cost (worst measured 0.122%); 20 ms absolute kept as
  aspirational, reported non-gating by `verify.py` every run. Spec 0001
  flipped to `ready`; all 5 thresholds pass. ~~mlx port of the bge-small
  embedder is a planned backlog item~~ — ported 2026-07-18.
- **Bonsai-27B CoT leak — FIXED 2026-07-17:** answer extraction handles bare
  `</think>` (`experiments/router/darkcore/models.py`); unit-tested 4/4.
  Unblocks 0002 label admission. Residual: thinking-tier T2 still narrates
  CoT as prose upstream — the fix is at extraction, not generation.
- **27B evicts co-resident embedder (page cache) — OPEN:** the 2026-07-18
  mlx port did NOT fix it (mmap is mmap — the 27B's residency reclaims the
  embedder's pages regardless of runtime; worst overhead 22.31 ms vs torch's
  22.36). Mitigated by rewarm-at-the-evicting-route's-tail; S4 passes with
  margin. Journal Episode 9.

<!-- /AUTO:issues -->

---

## Recent Changes

<!-- AUTO:changes — appended by scripts/agent-tools/update-memory.py --change -->
- 2026-07-14 — Project scaffolded: AGENTS.md, MEMORY.md, CONTINUE.md, plans/index.md
- 2026-07-14 — Agent interface built: agent-tools scripts (update-continue, update-memory, update-agents, memory-maintenance), agent-guide docs (continue-handoff, memory-maintenance, anti-drift), pre-commit hook
- 2026-07-16 — Routing pillar architected (specs 0001–0003 + docs/routing-architecture.md): data/control-plane split, cascade spine, certificate-rung verifiers, empirical closure (P1 confirmed). Nothing built yet; all specs draft.
- 2026-07-16 — Repo hygiene pass: router experiment README + fixture renames; plans/index.md re-scoped to the (paused) latent-bridge thread.
- 2026-07-17 — **dark-core v0.2 + server + spark relay** (final): predictor live in class-prior mode via control-surface-published exemplar snapshot (config v3); rung-0 inconclusive→judge; judge caps + skip_start; caller-visible escalation stream. Bench ×3: class 12/12, quality 0.900, **1.90× vs T2-only**; S4 fails by 2.36 ms (paging; operator decision pending). Discovered: T2 residency evicts co-resident torch components — rewarm at the evicting route's tail. **Router server** (`experiments/router/darkcore/server.py`): standalone OpenAI-compatible inference endpoint, manages T0/T1/T2 lifecycle, dark-operable. **Spark relay** (`../spark/src/spark/runtimes/relay.py`): new backend type that proxies requests to external OpenAI services (tested ✓). Agent harness can call router directly or via spark transparently.
- 2026-07-16 — **journal.md added to spec 0001**: the narrative evidence→decision→next-step record (incl. the meta-method: predict failures in writing → falsify first → bench → fix one variable → let surviving failures rank the backlog). Read it to understand WHY the backlog is ordered as it is.
- 2026-07-16 — **dark-core v0 built + benched** (`experiments/router/darkcore/`): control surface firmed v1 + implemented; Exp 4 swap economics measured (cascade viable, T0+T1 co-resident); bench 1.66× vs T2-only at 83% ≤T1, S2/S3/S4/S5 pass, S1 fails on V-struct; gauge-board TUI (Catppuccin Frappé). Specs 0002/0003 unblocked.
- 2026-07-18 — Idea-stage plan documented: generalized router interface boundaries (experiments/router/plans/generalized-router-interfaces.md) — Enricher/Tier/Verifier protocols, cascade stays the fixed spine; open question: uniform vs per-plugin config schema
- 2026-07-18 — Doc-drift pass per agent-guide: fixed broken refs in AGENTS.md/MEMORY.md/CONTINUE.md/plans/index.md; MEMORY.md known issues updated (S4 resolved option b, CoT leak fixed)
- 2026-07-18 — mlx embedder port shipped (embedder_mlx.py, fp32, zero new deps): parity EXACT vs frozen torch reference, snapshot v2 (runtime: mlx-fp32) as config v4, torch+transformers dropped from pyproject, bench all-5-PASS. Finding: 27B still evicts the mlx embedder (22.31ms worst) — rewarm pattern stays. Journal Episode 9.
- 2026-07-19 — Cross-repo: spark spec 0001 model-fleet-api opened (wip-research, 6 spikes; embedder promoted to first fleet tenant S6); patchwork side tracked in generalized-router-interfaces plan (Tier/Enricher = first customer). GitHub remote renamed to anthony-mqdt-labs; commit email switched to noreply.
- 2026-07-20 — Added mandatory project-entry GitHub account preflight: verify `gh api user` is `anthony-mqdt-labs` before work; stop and direct the user to switch/login when it is not. Git identity remains repository-local.
<!-- /AUTO:changes -->

---

## Architecture Notes (Manual)

- **Two threads under the composition thesis (routing + bridging + tiering):**
  (1) the **routing pillar** — *active*, spec-driven (`specs/0001–0003`,
  `docs/routing-architecture.md`), decisions D005–D008 adopted; (2) the
  **latent-bridge** thread — *paused*, planned in `plans/index.md`, decisions
  D001–D004 tentative. Don't read D001–D004 as current for the routing work.
- **Parent workspace:** `..` — inherits vibes-level AGENTS.md conventions.
- **Cross-reference:** quorum (`../quorum/`) is a sibling project with a very similar agent-interface implementation. Consult its DESIGN_LOG.md and anti-drift patterns.
- **Three-layer model for composition:** Routing (what dispatches), Bridge (how state flows between models), Tiering (which modules are loaded).

## Key Conventions

- Agent-facing docs in `docs/agent-guide/` — never operator runbooks
- Maintenance scripts in `scripts/agent-tools/` — agent-agnostic, stdlib only
- Research findings in `research/` — negative results are valuable
- Prototypes in `experiments/` — documented via README
- All model downloads from HuggingFace — may need `huggingface-cli login`
- IQ4_XS quantisation via llama.cpp `./quantize` or equivalent MLX path
