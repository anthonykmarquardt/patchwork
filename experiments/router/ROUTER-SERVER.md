# Patchwork Dynamic Router — Server Usage Guide

The router is now available as both a library and a standalone OpenAI-compatible inference server. Choose the integration path that fits your workflow.

---

## Quick Start (30 seconds)

```bash
cd experiments/router

# Terminal 1: start the router server (+ live gauge board on a TTY)
uv sync   # first time only — pinned env (.venv) via uv.lock
uv run darkcore serve
#   --headless for plain logs; or `spark darkcore-router` for supervision.
#   (Old form `uv run python -m darkcore.server --port 8000` still works, headless.)

# Terminal 2: test it (in another terminal)
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "patchwork-dynamic-router",
    "messages": [{"role": "user", "content": "What is 2+2?"}]
  }' | python3 -m json.tool
```

The router will classify the query, route to the appropriate tier (T0/T1/T2), cascade/verify as needed, and return the answer in OpenAI format — with full conversation context honored, real token `usage`, an `X-Patchwork-Route-Id` header + `patchwork` trace object, SSE streaming via `"stream": true`, and `/health?deep=1` for state (the 2026-07-17 seam contract; see QUICKSTART.md).

---

## Usage Paths

### Path 1: Standalone Server (Direct Calls)

**Best for:** Quick testing, prototyping, single agent harness.

```bash
# Start the server
cd experiments/router
uv sync   # first time only — pinned env (.venv) via uv.lock
uv run python -m darkcore.server --port 8000 --host 127.0.0.1
```

**Output:**
```
Loading weights: 100%|██████████| 199/199 [00:00<?, ?it/s]
INFO:     Started server process [12345]
INFO:     Application startup complete.
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
```

**Health check:**
```bash
curl http://localhost:8000/health
# Response: {"status": "ok", "model": "patchwork-dynamic-router"}
```

**List available models:**
```bash
curl http://localhost:8000/v1/models | python3 -m json.tool
```

**Make a completion request:**
```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "patchwork-dynamic-router",
    "messages": [
      {"role": "user", "content": "Solve this: 7 * 8"}
    ],
    "temperature": 0.7,
    "max_tokens": 100
  }' | python3 -m json.tool
```

**Response:**
```json
{
  "id": "chatcmpl-abc123xyz",
  "object": "chat.completion",
  "created": 1721234567,
  "model": "patchwork-dynamic-router",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "7 * 8 = 56"
      },
      "finish_reason": "stop"
    }
  ],
  "usage": {
    "prompt_tokens": 12,
    "completion_tokens": 5,
    "total_tokens": 17
  }
}
```

---

### Path 2: Via Spark Relay (Recommended for Production)

**Best for:** Production deployments, multi-agent harnesses, unified model management.

Spark's relay backend proxies requests to the router transparently. Your agent harness talks to spark normally; spark handles the routing.

#### Setup

**1. Ensure spark relay config exists:**
```bash
cat ../spark/config/runtimes/relay.toml
```

The config should point to the router:
```toml
[server]
relay_base_url = "http://127.0.0.1:8000"
relay_health_endpoint = "/health"
```

**2. Register a model that uses relay in spark:**

Create or edit `~/.local/share/spark/models/my-router.toml`:
```toml
[model]
id = "my-router"
description = "Patchwork dynamic router (via relay)"
model_format = "any"
path = ""
backend = "relay"
quant = "none"
params = 0.0
research_status = "registered"

[server]
relay_base_url = "http://127.0.0.1:8000"
relay_health_endpoint = "/health"
```

Or use the CLI to set it up:
```bash
# Create a minimal config
mkdir -p ~/.local/share/spark/models
cat > ~/.local/share/spark/models/my-router.toml << 'EOF'
id = "my-router"
description = "Patchwork dynamic router"
model_format = "any"
backend = "relay"
research_status = "registered"

[server]
relay_base_url = "http://127.0.0.1:8000"
relay_health_endpoint = "/health"
EOF

# Verify
spark list | grep router
```

#### Usage

**Terminal 1: Start the router server**
```bash
cd experiments/router
uv sync   # first time only — pinned env (.venv) via uv.lock
uv run python -m darkcore.server --port 8000
```

**Terminal 2: Start spark (pointing to the router)**
```bash
spark my-router
```

This tells spark to attach to the relay backend (never spawns a local process). Spark verifies the router is healthy at http://localhost:8000/health, then proxies requests.

**Terminal 3: Query via spark (from agent harness perspective)**
```bash
# Agent harness calls spark like any other OpenAI endpoint
curl -X POST http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "patchwork-dynamic-router",
    "messages": [{"role": "user", "content": "Is this an emotional query?"}]
  }' | python3 -m json.tool
```

Spark relays the request to http://localhost:8000/v1/chat/completions (the router), gets the response, and returns it to the caller. The caller sees the same OpenAI format, completely transparent.

---

### Path 3: Python Library (For Agent Harnesses)

**Best for:** Programmatic control, custom routing logic, debugging.

```python
from darkcore.router import Router

# Initialize the router (loads config, exemplars, models)
router = Router()

# Make a routing decision
result = router.route("What were your weaknesses in your last job?")

print(result["answer"])           # The final answer
print(result["tier"])             # Which tier answered (T0/T1/T2)
print(result["escalations"])      # Number of times it escalated
print(result["trace"])            # Full routing decision trace
```

For agent harnesses with live status:
```python
def on_status(event, **fields):
    """Called as the query climbs the cascade."""
    print(f"[{event}] {fields}")

result = router.route(
    "Design a machine learning system for fraud detection",
    on_event=on_status
)
```

Output as it routes:
```
[routing_decision] class=agentic start_tier=T0 floor=T0 ...
[tier_dispatched] tier=T0 attempt=1 ...
[verifier_result] rung=0 verdict=fail ...
[escalation] attempting_next_tier=T1 ...
[tier_dispatched] tier=T1 attempt=2 ...
[verifier_result] rung=1 verdict=pass ...
[route_completed] final_tier=T1 escalations=1 ...
```

---

## Query Types & Expected Routing

The router classifies queries into three classes and routes accordingly:

| Class | Detection | Default Tier | Why |
|-------|-----------|---|---|
| **Agentic** | Contains tool list or code fences | T0 start | Structural rules catch tool semantics |
| **Reasoning** | Asks for analysis, logic, traps | T0 start | Checkable via ground-truth plugins |
| **Emotional** | First-person affective language | T1 floor | Requires nuance; T0 often cold/dismissive |
| **Default** | Everything else | T0 start | Try T0 first; escalate if needed |

**Examples:**
```
Query: "What are my weaknesses?" 
→ Class: emotional (first-person + affective)
→ Floor: T1 (skip T0, too risky)
→ Result: Routed directly to T1 for thoughtful answer

Query: "Get the contents of https://example.com"
→ Class: agentic (tool invocation)
→ Start: T0
→ Result: T0 attempts; rung-0 checks if it's a real HTTP endpoint
         → Passes, answer emitted from T0

Query: "Why do birds fly south for winter?"
→ Class: reasoning (analytical)
→ Start: T0
→ Result: T0 attempts; rung-1 checks answer against world knowledge
         → Fails (T0 made something up)
         → Escalate to T1; T1 provides verified answer
```

---

## Configuration

### Router Server Options

```bash
uv run python -m darkcore.server --help
```

```
--port PORT              Port to listen on (default 8000)
--host HOST              Host to bind to (default 127.0.0.1)
--workers N              Number of worker processes (default 1)
```

### Router Config (Control Surface)

The router reads `config.json` at startup. Hot-reload happens on version change.

Key settings:
- **predictor_enabled** — whether to use class-prior embeddings (default true if exemplars exist)
- **exemplar_store_ref** — points to `exemplars/v1/` snapshot (n=21 currently)
- **prefilter_rules** — deterministic rules for agentic/reasoning/emotional signals
- **class_start_map** — where each class starts in the cascade (T0, T1, T2)
- **class_floor** — minimum tier for safety (emotional: T1, others: T0)
- **judge_token_caps** — how many completion tokens each tier's judge gets

See `specs/0001-tiered-cascade-router/control-surface.md` for the full schema.

---

## Monitoring & Telemetry

All routing decisions are logged to `logs/router/YYYY-MM-DD.jsonl`:

```bash
# Watch live routing telemetry
tail -f logs/router/$(date +%Y-%m-%d).jsonl | jq '.event' -r | sort | uniq -c

# Analyze a single route
tail -1 logs/router/$(date +%Y-%m-%d).jsonl | jq '.routing_decision'
```

Key events:
- **routing_decision** — initial classification (class, start tier, floor)
- **tier_dispatched** — a tier was invoked
- **verifier_result** — certificate passed/failed
- **escalation** — moving to next tier
- **route_completed** — final result (final_tier, escalations, total_ms)
- **prior_rewarmed** — embedder was paged back in (only if T2 was used)

---

## Troubleshooting

### Server won't start

```bash
# Check if port is already in use
lsof -i :8000

# Free it if needed
pkill -f "darkcore.server"

# Try a different port
uv run python -m darkcore.server --port 8001
```

### Query returns an error

```
{"error": {"message": "Router error: ...", "type": "Exception"}}
```

Check the server logs:
```bash
# The server prints to stderr; check for model loading issues
# or config parse errors

# If config is invalid, it falls back to defaults
# Check config.json in the experiments/router/ directory
```

### Slow responses

First request after a model load (~30s): embedder warming up.
Subsequent requests: <5s typical for T0, <30s for T1, <60s for T2.

If a query is taking much longer than expected:
- Check if it escalated multiple times (`escalations` in the trace)
- Look at `total_ms` breakdown in telemetry (swap cost? verify cost? generation cost?)
- Check if the 27B was loaded (T2 residency pages out the embedder, first query after T2 pays rewarm cost)

---

## Next Steps

- **Experiment:** Run the router with different queries and watch the TUI (`uv run darkcore board --replay`)
- **Integrate:** Wire your agent harness to call the router (direct or via spark relay)
- **Iterate:** As you get production queries, exemplars grow and the router gets better
- **Tune:** The tuner (spec 0002) will automate exemplar curation and λ calibration

For details on the routing internals, see `docs/routing-architecture.md` and `specs/0001-tiered-cascade-router/journal.md`.
