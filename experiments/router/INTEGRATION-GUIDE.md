# Router Server + Spark — End-to-End Integration Guide

Your agent harness can reach the patchwork dynamic router three ways:
directly as a standalone server (Path A), through spark's relay backend for
remote routers (Path B), or spawned and supervised BY spark (Path C — local
default).

**Interface contract (seams, 2026-07-17):** full conversation context is
honored (route on last user message, generate with system + history); every
response carries `X-Patchwork-Route-Id` + a `patchwork` trace object; `usage`
is real token counts; `"stream": true` gives SSE with escalation-progress
comments and verified-only content; `/health?deep=1` reports config/predictor/
tier state. Details: QUICKSTART.md §"The seam contract".

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                       AGENT HARNESS                             │
│                                                                 │
│    (spark client lib, Python requests, curl, etc.)             │
└──────────────┬────────────────────────────────┬────────────────┘
               │                                │
        ┌──────▼─────┐                   ┌──────▼────────┐
        │  PATH A    │                   │   PATH B      │
        │ (Direct)   │                   │   (via Spark) │
        └──────┬─────┘                   └──────┬────────┘
               │                                │
         ┌─────▼──────────────────────────────────▼────┐
         │  PATCHWORK DYNAMIC ROUTER                   │
         │  (OpenAI-compatible endpoint)              │
         │  localhost:8000/v1/chat/completions       │
         └─────┬──────────────────────────────────────┘
               │
         ┌─────▼─────────────────────────────────────┐
         │  ROUTING CASCADE                          │
         │                                           │
         │  1. Classify query (prefilter + embedder)│
         │  2. Select tier (T0 / T1 / T2)           │
         │  3. Run model + verify                   │
         │  4. Escalate if needed                   │
         │  5. Return answer in OpenAI format       │
         └─────┬─────────────────────────────────────┘
               │
         ┌─────▼────────────────────────────┐
         │  MODELS                          │
         │  T0: Bonsai 1.7B  (fast/cheap)  │
         │  T1: Bonsai 8B    (balanced)    │
         │  T2: Bonsai 27B   (capable)     │
         └──────────────────────────────────┘
```

---

## Path A: Direct (Standalone Server)

**Use when:** Testing, prototyping, or single agent harness.

### Setup (30 seconds)

```bash
cd ../patchwork/experiments/router

# Start the server in a terminal
uv sync   # first time only — pinned env (.venv) via uv.lock
uv run python -m darkcore.server --port 8000 --host 127.0.0.1
```

You'll see:
```
Loading weights: 100%|██████████| 199/199 [00:00<?, ?it/s]
INFO:     Started server process [12345]
INFO:     Application startup complete.
INFO:     Uvicorn running on http://127.0.0.1:8000
```

### Usage

Your agent harness calls the router directly:

```python
import requests

def ask_router(query: str) -> str:
    response = requests.post(
        "http://localhost:8000/v1/chat/completions",
        json={
            "model": "patchwork-dynamic-router",
            "messages": [{"role": "user", "content": query}]
        }
    )
    return response.json()["choices"][0]["message"]["content"]

# Use it
answer = ask_router("What are the key components of a transformer?")
print(answer)
```

Or with curl:
```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "patchwork-dynamic-router",
    "messages": [{"role": "user", "content": "Explain backpropagation"}]
  }' | jq '.choices[0].message.content'
```

**Pros:**
- Minimal setup
- Direct control
- Easy debugging

**Cons:**
- Agent harness must know the router's port/address
- Can't easily swap between multiple inference backends

---

## Path C: Spark-Owned Child (Recommended for Local — seam 5, 2026-07-17)

**Use when:** You want spark to OWN the router's lifecycle — spawn,
health-wait, bounded restart on crash, graceful shutdown. The relay (Path B)
can only *watch* an already-running router; this path manages it.

```bash
spark darkcore-router      # spawns `python -m darkcore.server` supervised
# ready in seconds if the page cache is warm; Ctrl-C reaps the child
```

Backed by `spark/config/runtimes/darkcore.toml` (pure TOML, generic
backend): the binary is the router project's own `.venv` python
(experiments/router is a standalone uv project; `uv sync` there first).
Registry entry: `~/.local/share/spark/models/darkcore-router.toml`.
NB spark's memory gate cannot see the router's internal tier weights (worst
case ~8 GB when T2 loads) — run it with the box to itself.

---

## Path B: Via Spark Relay (for Remote/External Routers)

**Use when:** The router runs somewhere spark can't spawn it (another host,
another owner) and you only need attach + health-watch + URL handoff.

### Setup (2 minutes)

**Step 1: Register a relay model in spark**

Create `~/.local/share/spark/models/patchwork-router.toml`:

```toml
id = "patchwork-router"
description = "Patchwork dynamic router (T0/T1/T2 cascade)"
model_format = "any"
backend = "relay"
research_status = "registered"

[server]
relay_base_url = "http://127.0.0.1:8000"
relay_health_endpoint = "/health"
```

Verify:
```bash
spark list | grep patchwork-router
```

**Step 2: Start the router server**

```bash
cd ../patchwork/experiments/router
uv sync   # first time only — pinned env (.venv) via uv.lock
uv run python -m darkcore.server --port 8000
```

**Step 3: Start spark**

In a new terminal:
```bash
spark patchwork-router
```

Spark will verify the router is healthy, then enter attach mode (never spawns a local process). Your agent harness now calls spark normally.

### Usage

Your agent harness calls spark's OpenAI endpoint (just like any model):

```python
import openai

# Point to spark instead of the router directly
openai.api_base = "http://localhost:8080/v1"

response = openai.ChatCompletion.create(
    model="patchwork-dynamic-router",
    messages=[{"role": "user", "content": "What is a neural network?"}]
)
print(response.choices[0].message.content)
```

Or curl:
```bash
curl -X POST http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "patchwork-dynamic-router",
    "messages": [{"role": "user", "content": "Explain optimization"}]
  }' | jq '.choices[0].message.content'
```

**Data flow:**
```
Agent harness → spark (8080) → relay → router (8000) → answer
                                ▲
                          (spark proxies)
```

**Pros:**
- Agent harness sees spark, not the router (clean separation)
- Easy to switch backends (register a new model, point `relay_base_url` elsewhere)
- Spark handles health checks, retries, logging
- Production-friendly (can scale spark separately)

**Cons:**
- Extra hop (negligible latency, ~1ms)
- Requires spark to be running

---

## Choosing Your Path

| Criterion | Path A (Direct) | Path B (Relay) | Path C (Spark-owned) |
|-----------|---|---|---|
| **Who starts the router** | you | you | spark |
| **Restart on crash** | ❌ No | ❌ No (watch only) | ✅ Supervisor |
| **Live gauge board** | ✅ `darkcore serve` | ❌ | ❌ (headless child) |
| **Remote router** | ✓ | ✅ Ideal | ❌ Local only |
| **Minimal setup** | ✅ Fastest | ✓ 2 min | ✓ Registered already |
| **Monitoring** | JSONL + board | JSONL + spark telemetry | JSONL + spark telemetry |

**Default recommendation:** Path A (`darkcore serve`) while iterating — you
get the live board. Path C (`spark darkcore-router`) when the router should
just *be up* like any other spark model. Path B only for routers spark
can't own.

---

## Query Examples

All examples work on both paths. Just change the endpoint from `http://localhost:8000` to `http://localhost:8080` for the relay path.

### Mechanical queries (T0 answers these)
```
"What is 7 * 8?"
→ Class: reasoning
→ Start tier: T0
→ Result: T0 solves it, rung-1 verifies answer
```

### Agentic queries (T0 tries, often escalates)
```
"Fetch the current weather from https://weather.api.com and summarize it."
→ Class: agentic (contains URL + request)
→ Start tier: T0
→ Result: T0 attempts; rung-0 validates tool syntax
         → If valid, passes; if invalid, escalates to T1
```

### Emotional/nuanced queries (T1+ answers these)
```
"I'm afraid of failure. How do I overcome this?"
→ Class: emotional (first-person + affective)
→ Start tier: T1 (skips T0, too risky)
→ Result: T1 provides empathetic, nuanced answer
```

### Complex reasoning (T2 handles this)
```
"Design a system that scales to 1 million users. Consider latency, consistency, cost."
→ Class: reasoning
→ Start tier: T0
→ Result: T0 attempts; rung-1 checks quality
         → Lacks strategic depth; escalates to T1
         → T1 is better; if budget allows, escalates to T2
         → T2 returns comprehensive design
```

---

## Monitoring & Debugging

### Path A (Direct)

Server logs flow to stdout. Check the terminal where you started the router:
```
INFO:     Started server process
INFO:     Application startup complete.
```

Routing telemetry lives in:
```bash
tail -f experiments/router/logs/router/$(date +%Y-%m-%d).jsonl | jq '.'
```

### Path B (Relay)

Spark logs:
```bash
tail -f ~/.local/share/spark/logs/supervisor/$(date +%Y-%m-%d).jsonl | jq '.event'
```

Router telemetry (same as Path A):
```bash
tail -f experiments/router/logs/router/$(date +%Y-%m-%d).jsonl | jq '.'
```

### Trace a single query

```bash
# From Path A direct output
curl -X POST http://localhost:8000/v1/chat/completions ... | jq '.choices[0]'

# From Path B via spark
curl -X POST http://localhost:8080/v1/chat/completions ... | jq '.choices[0]'

# Then look at the route_id in telemetry
grep "route_id=abc123" experiments/router/logs/router/$(date +%Y-%m-%d).jsonl | jq '.'
```

---

## Troubleshooting

### "Connection refused" on port 8000

The router server isn't running. Start it:
```bash
cd ../patchwork/experiments/router
uv sync   # first time only — pinned env (.venv) via uv.lock
uv run python -m darkcore.server --port 8000
```

### "Health check failed" (spark relay)

Spark can't reach the router at the configured URL. Check:
```bash
curl http://127.0.0.1:8000/health
# Should return: {"status": "ok", "model": "patchwork-dynamic-router"}

# If that works, check your model config:
cat ~/.local/share/spark/models/patchwork-router.toml | grep relay_base_url
```

### Slow first request (~30s)

The router is warming up the embedder (bge-small). This happens once per server start. Subsequent requests: <5s for T0, <30s for T1, <60s for T2.

### Queries returning wrong tier

Check the routing decision in telemetry:
```bash
tail -1 experiments/router/logs/router/$(date +%Y-%m-%d).jsonl | jq '.routing_decision'
```

Look for:
- `class` — detected query class
- `start_tier` — where it started
- `floor` — minimum tier for safety

If classification is wrong, it's because:
1. Prefilter missed a signal (see `prefilter` field in log)
2. Embedder had low confidence (see `predictor.confidence` in log)

---

## Next: Agent Harness Integration

See the detailed guides:
- **Path A (direct):** `experiments/router/ROUTER-SERVER.md` → "Path 1: Standalone Server"
- **Path B (relay):** `../spark/RELAY-USAGE.md`

Your agent harness should be calling one of these endpoints by tomorrow. As you do, production queries get logged, exemplars grow, and the router improves.
