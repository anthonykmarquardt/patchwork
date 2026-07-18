# Router Server — Quickstart (TL;DR)

## 30-Second Setup

```bash
cd ../patchwork/experiments/router
MLXPY=$HOME/.local/share/uv/tools/mlx-lm/bin/python
$MLXPY -m darkcore serve            # server + live gauge board (default on a TTY)
# $MLXPY -m darkcore serve --headless   # plain uvicorn logs
# spark darkcore-router                 # spark-supervised (restart on crash)
```

The router is now listening at `http://localhost:8000`. Old form
`$MLXPY -m darkcore.server --port 8000` still works (always headless).

Also new: `$MLXPY -m darkcore status` (config/tiers/rollup at a glance),
`$MLXPY -m darkcore route "query"` (one-shot with climb trace),
`$MLXPY -m darkcore board --live` (gauge board alone).

## One-Line Query

```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model": "patchwork-dynamic-router", "messages": [{"role": "user", "content": "What is 2+2?"}]}' | jq '.choices[0].message.content'
```

Response: `"2+2 = 4"`

## For Your Agent Harness

**Python:**
```python
import requests

def query_router(prompt: str) -> str:
    r = requests.post("http://localhost:8000/v1/chat/completions", json={
        "model": "patchwork-dynamic-router",
        "messages": [{"role": "user", "content": prompt}]
    })
    return r.json()["choices"][0]["message"]["content"]

print(query_router("Explain backpropagation"))
```

**JavaScript:**
```javascript
async function queryRouter(prompt) {
    const response = await fetch("http://localhost:8000/v1/chat/completions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
            model: "patchwork-dynamic-router",
            messages: [{ role: "user", content: prompt }]
        })
    });
    const data = await response.json();
    return data.choices[0].message.content;
}

queryRouter("What is a neural network?").then(console.log);
```

**Go:**
```go
import "github.com/sashabaranov/go-openai"

client := openai.NewClient("dummy-key")
client.BaseURL = "http://localhost:8000/v1"

resp, _ := client.CreateChatCompletion(ctx, openai.ChatCompletionRequest{
    Model: "patchwork-dynamic-router",
    Messages: []openai.ChatCompletionMessage{
        {Role: "user", Content: "Explain optimization"},
    },
})
fmt.Println(resp.Choices[0].Message.Content)
```

## Using Spark (Production)

**Step 1:** Register router in spark
```bash
cat > ~/.local/share/spark/models/patchwork-router.toml << 'EOF'
id = "patchwork-router"
backend = "relay"
research_status = "registered"
[server]
relay_base_url = "http://127.0.0.1:8000"
relay_health_endpoint = "/health"
EOF
```

**Step 2:** Start spark
```bash
spark patchwork-router
```

**Step 3:** Query via spark (same endpoints)
```bash
curl -X POST http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model": "patchwork-dynamic-router", "messages": [{"role": "user", "content": "What is a transformer?"}]}'
```

## What It Does

1. **Classifies** your query (agentic? reasoning? emotional?)
2. **Routes** to the cheapest tier that can handle it (T0 < T1 < T2)
3. **Verifies** the answer (catches wrong outputs)
4. **Escalates** if needed (T0 fails → try T1, etc.)
5. **Returns** the answer in OpenAI format

## What You'll See

```
Routing decision:
- Your query is "agentic" (contains a tool call)
- Starting at T0 (cheapest)
- Floor is T0 (no safety restrictions)

Attempt 1 (T0):
- Model generates tool call
- Verifier checks: is it real HTTP? is the endpoint correct?
- Result: PASS ✓

Answer returned in OpenAI format
```

Or:

```
Routing decision:
- Your query is "emotional" (affective first-person)
- Starting at T1 (T0 too risky)

Attempt 1 (T1):
- Model generates thoughtful answer
- Verifier checks: does it address the emotional content?
- Result: PASS ✓

Answer returned
```

Or:

```
Routing decision:
- Your query is "reasoning" (analytical)
- Starting at T0

Attempt 1 (T0):
- Model attempts analysis
- Verifier checks: can we verify this with ground truth?
- Result: FAIL ✗ (T0 made something up)

Escalating to T1...

Attempt 2 (T1):
- Model provides better analysis
- Verifier checks quality
- Result: PASS ✓

Answer returned from T1
```

## Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/health` | GET | Liveness (`?deep=1` adds config version, predictor/store, tier residency, busy flag) |
| `/v1/models` | GET | List available models |
| `/v1/chat/completions` | POST | OpenAI-compatible; `"stream": true` for SSE |

## The seam contract (2026-07-17)

- **Full context honored:** the router routes/verifies on the *last user
  message*; the winning tier generates with the whole conversation
  (system + history). Telemetry sees message counts only, never content.
- **Trace handle:** every response carries `X-Patchwork-Route-Id` and a
  `patchwork` object (`route_id`, `tier`, `routed_class`, `escalations`,
  `flagged`, `total_generation_tokens`, per-attempt tokens) — join any
  answer to `logs/router/<date>.jsonl`.
- **Real usage:** `usage` is true token counts from the winning attempt;
  total spend across attempts is in `patchwork`.
- **Streaming:** `"stream": true` → SSE. Escalation progress arrives as
  comment lines (`: ◉ T1 answering …` — spec-compliant keep-alives; OpenAI
  SDKs ignore them). Content chunks stream only after the verifier accepts:
  unverified tokens never leave the process.
- One route at a time (route lock); `/health` stays responsive during
  minutes-long T2 climbs.

## Server Options

```bash
$MLXPY -m darkcore serve --port 8000 --host 127.0.0.1 [--headless]
```

| Flag | Default | Notes |
|------|---------|-------|
| `--port` | 8000 | Port to listen on |
| `--host` | 127.0.0.1 | Host to bind to (loopback by default, safe) |
| `--headless` | off | Plain uvicorn logs; auto when stderr is not a TTY |

## Monitoring

Watch routing decisions in real-time:
```bash
tail -f experiments/router/logs/router/$(date +%Y-%m-%d).jsonl | jq '.event'
```

Or use the TUI:
```bash
MLXPY=$HOME/.local/share/uv/tools/mlx-lm/bin/python
cd experiments/router
$MLXPY -m darkcore.tui --replay --speed 30
```

## Docs

- **Full server guide:** `ROUTER-SERVER.md`
- **Integration guide:** `INTEGRATION-GUIDE.md`
- **Spark relay guide:** `../spark/RELAY-USAGE.md`
- **Architecture:** `docs/routing-architecture.md`
- **Journal (research notes):** `specs/0001-tiered-cascade-router/journal.md`

## Troubleshooting

**Server won't start:** Check port
```bash
lsof -i :8000
pkill -f "darkcore.server"  # kill if stuck
```

**Slow first request:** Normal (embedder warming up, ~30s)

**Wrong answer type:** Check telemetry
```bash
tail -1 experiments/router/logs/router/$(date +%Y-%m-%d).jsonl | jq '.class, .final_tier'
```

## Next Steps

1. Start the server (above)
2. Wire your agent harness to call it
3. Watch the telemetry as real queries flow through
4. Exemplars grow → router improves
5. Eventually tune via spec 0002 (tuner)

That's it. The router handles the rest.
