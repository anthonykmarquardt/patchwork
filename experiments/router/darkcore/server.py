"""OpenAI-compatible inference endpoint for the dark-core router.

Exposes /v1/chat/completions (blocking + SSE streaming), /v1/models, and
/health (?deep=1). Dark-operable: works standalone with zero external config.
The router manages T0/T1/T2 lifecycle; this server translates HTTP to
route() calls.

The seam contract (2026-07-17):
  - Routing/verification happen on the LAST USER MESSAGE; generation gets the
    full conversation (system + history) — seam 1.
  - Every response carries the route_id (X-Patchwork-Route-Id header + a
    `patchwork` extension object) so callers can join telemetry — seam 2.
  - `usage` is real token counts from the winning attempt; the extension
    carries total spend across all attempts — seam 3.
  - `stream: true` returns SSE: escalation progress as comment lines (spec-
    compliant keep-alives; OpenAI SDKs ignore them), then the VERIFIED answer
    as content chunks. Unverified tokens are never streamed — an answer that
    might be rejected must not leave the process — seam 4.
  - /health?deep=1 reports config/predictor/tier residency — seam 6.

Generation runs in the threadpool (sync endpoints), serialized by a route
lock — honest capacity on this box is one route at a time (Exp 4), and
/health must stay responsive during a minutes-long T2 climb.

Run: python -m darkcore serve  (CLI, live gauge board)
     python -m darkcore.server [--port 8000]  (headless, back-compat)
"""
import argparse
import json
import queue
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Optional

try:
    from fastapi import FastAPI, HTTPException, Request, Response
    from fastapi.responses import JSONResponse, StreamingResponse
    from pydantic import BaseModel
except ImportError:
    raise ImportError(
        "FastAPI required for server mode. Install: pip install fastapi uvicorn"
    )

from . import __version__
from . import router as router_module

MODEL_ID = "patchwork-dynamic-router"
STREAM_CHUNK_CHARS = 120     # verified-answer chunking for SSE
STREAM_PING_S = 15           # comment keep-alive cadence while the cascade climbs


# OpenAI-compatible request/response models
class ChatMessage(BaseModel):
    role: str  # "system", "user", "assistant"
    content: str


class ChatCompletionRequest(BaseModel):
    model: str = MODEL_ID
    messages: list[ChatMessage]
    stream: Optional[bool] = False
    # Accepted for OpenAI compatibility; generation params are owned by the
    # router's control surface (per-tier max_tokens), not the caller.
    temperature: Optional[float] = 0.7
    max_tokens: Optional[int] = None
    top_p: Optional[float] = 1.0
    frequency_penalty: Optional[float] = 0.0
    presence_penalty: Optional[float] = 0.0


class Choice(BaseModel):
    index: int
    message: ChatMessage
    finish_reason: str


class Usage(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class PatchworkExt(BaseModel):
    """Non-OpenAI extension: the telemetry join key + route economics.
    OpenAI SDKs tolerate (and expose) unknown response fields."""
    route_id: str
    tier: str
    routed_class: str
    escalations: int
    flagged: bool
    config_version: int
    total_generation_tokens: int   # spend across ALL attempts, not just the winner
    attempts: list[dict]           # [{tier, outcome, tokens}]


class ChatCompletionResponse(BaseModel):
    id: str
    object: str = "chat.completion"
    created: int
    model: str
    choices: list[Choice]
    usage: Usage
    patchwork: PatchworkExt


def split_messages(messages: list[ChatMessage]):
    """Seam-1 contract: (routing query, full conversation).

    Routing query = last user message. Conversation = every well-formed turn,
    in order, for the winning tier's chat template."""
    convo = [{"role": m.role, "content": m.content}
             for m in messages
             if m.role in ("system", "user", "assistant") and m.content]
    query = next((m["content"] for m in reversed(convo) if m["role"] == "user"), None)
    if query is None:
        raise ValueError("No user message found in request")
    return query, convo


def _usage_and_ext(result) -> tuple[Usage, PatchworkExt]:
    """Seams 2+3: real counts from the trace + the telemetry join key."""
    tr = result["trace"]
    gen_attempts = [a for a in tr["attempts"] if a.get("outcome") != "unavailable"]
    final = gen_attempts[-1] if gen_attempts else {}
    usage = Usage(
        prompt_tokens=final.get("prompt_tokens", 0),
        completion_tokens=final.get("tokens", 0),
        total_tokens=final.get("prompt_tokens", 0) + final.get("tokens", 0),
    )
    ext = PatchworkExt(
        route_id=tr["route_id"],
        tier=result["tier"],
        routed_class=tr["class"],
        escalations=result["escalations"],
        flagged=result["flagged"],
        config_version=tr["config_version"],
        total_generation_tokens=sum(a.get("tokens", 0) for a in gen_attempts),
        attempts=[{"tier": a["tier"], "outcome": a.get("outcome"),
                   "tokens": a.get("tokens", 0)} for a in tr["attempts"]],
    )
    return usage, ext


def _progress_line(name, f):
    """Human-readable climb progress for SSE comments (mirrors the CLI glyphs)."""
    return {
        "dispatch": lambda: f"◉ {f['tier']} answering (attempt {f['attempt']})",
        "verdict": lambda: (f"{'✓' if f['passed'] else '✗'} {f['tier']} "
                            f"{'accepted' if f['passed'] else 'rejected'}"),
        "escalation": lambda: f"➜ escalating {f['from_tier']} → {f['to_tier']}",
        "terminal_failure": lambda: f"⚑ {f['tier']} failed — emitting flagged answer",
    }.get(name, lambda: name)()


def create_app():
    """Assemble the FastAPI app with dark-core router."""
    app = FastAPI(title="Patchwork Dynamic Router", version=__version__)
    router_singleton = router_module.Router()
    route_lock = threading.Lock()   # one route at a time (Exp 4: honest capacity)
    stats = {"started": time.time(), "routes_served": 0}

    @app.get("/health")
    async def health(deep: int = 0):
        """Liveness probe; ?deep=1 adds config/predictor/tier state (seam 6)."""
        shallow = {"status": "ok", "model": MODEL_ID, "version": __version__}
        if not deep:
            return shallow
        cfg = router_singleton._config
        prior = router_singleton._prior
        pool = router_singleton._pool
        return {
            **shallow,
            "uptime_s": round(time.time() - stats["started"], 1),
            "routes_served": stats["routes_served"],
            "busy": route_lock.locked(),
            "config_version": cfg["config_version"],
            "updated_by": cfg.get("updated_by"),
            "predictor": ({"enabled": True, "embedder": prior.embedder_id,
                           "store_version": prior.index_version,
                           "n_exemplars": len(prior.ids)}
                          if prior is not None else {"enabled": False}),
            "tiers": [{"id": t["id"], "model": t["model"],
                       "resident": t["id"] in pool._live}
                      for t in cfg["params"]["tier_roster"]],
        }

    @app.get("/v1/models")
    async def list_models():
        """OpenAI-compatible model listing."""
        return {
            "object": "list",
            "data": [{"id": MODEL_ID, "object": "model", "owned_by": "patchwork",
                      "created": int(stats["started"])}],
        }

    def _run_route(query, convo, on_event=None):
        with route_lock:
            result = router_singleton.route(query, messages=convo, on_event=on_event)
        stats["routes_served"] += 1
        return result

    def _stream_response(query, convo, completion_id, created):
        """SSE: progress comments while the cascade climbs, then the verified
        answer as content chunks. Comments double as keep-alives."""
        def chunk(delta, finish=None, extra=None):
            obj = {"id": completion_id, "object": "chat.completion.chunk",
                   "created": created, "model": MODEL_ID,
                   "choices": [{"index": 0, "delta": delta,
                                "finish_reason": finish}]}
            if extra:
                obj.update(extra)
            return f"data: {json.dumps(obj)}\n\n"

        q: queue.Queue = queue.Queue()
        holder = {}

        def on_event(name, **fields):
            q.put(("progress", name, fields))

        def work():
            try:
                holder["result"] = _run_route(query, convo, on_event=on_event)
            except Exception as e:  # noqa: BLE001 — surfaced to the stream below
                holder["error"] = e
            q.put(("done", None, None))

        threading.Thread(target=work, daemon=True).start()
        yield chunk({"role": "assistant"})
        while True:
            try:
                kind, name, fields = q.get(timeout=STREAM_PING_S)
            except queue.Empty:
                yield ": ping\n\n"
                continue
            if kind == "done":
                break
            yield f": {_progress_line(name, fields)}\n\n"

        if "error" in holder:
            err = holder["error"]
            payload = json.dumps({"error": {"message": str(err)[:200],
                                            "type": type(err).__name__}})
            yield f"data: {payload}\n\n"
            yield "data: [DONE]\n\n"
            return

        result = holder["result"]
        usage, ext = _usage_and_ext(result)
        answer = result["answer"]
        for i in range(0, len(answer), STREAM_CHUNK_CHARS):
            yield chunk({"content": answer[i:i + STREAM_CHUNK_CHARS]})
        yield chunk({}, finish="stop",
                    extra={"usage": usage.model_dump(),
                           "patchwork": ext.model_dump()})
        yield "data: [DONE]\n\n"

    @app.post("/v1/chat/completions")
    def chat_completions(req: ChatCompletionRequest, response: Response):
        """OpenAI-compatible chat completion (sync def → threadpool: /health
        stays responsive during minutes-long climbs).

        The router handles classification, escalation, and verification; the
        `patchwork` field + X-Patchwork-Route-Id header join the response to
        its telemetry trace."""
        try:
            query, convo = split_messages(req.messages)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

        completion_id = f"chatcmpl-{uuid.uuid4().hex[:24]}"
        created = int(datetime.now(timezone.utc).timestamp())

        if req.stream:
            return StreamingResponse(
                _stream_response(query, convo, completion_id, created),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
            )

        try:
            result = _run_route(query, convo)
        except Exception as e:  # noqa: BLE001 — translated to HTTP 500
            raise HTTPException(
                status_code=500,
                detail=f"Router error: {type(e).__name__}: {str(e)[:200]}",
            )

        usage, ext = _usage_and_ext(result)
        response.headers["X-Patchwork-Route-Id"] = ext.route_id
        return ChatCompletionResponse(
            id=completion_id,
            created=created,
            model=MODEL_ID,
            choices=[Choice(index=0,
                            message=ChatMessage(role="assistant",
                                                content=result["answer"]),
                            finish_reason="stop")],
            usage=usage,
            patchwork=ext,
        )

    @app.exception_handler(Exception)
    async def exception_handler(request: Request, exc: Exception):
        """Global error handler."""
        return JSONResponse(
            status_code=500,
            content={"error": {"message": str(exc)[:200],
                               "type": type(exc).__name__,
                               "param": None, "code": None}},
        )

    return app


def main():
    """Headless entry point (back-compat). Prefer `python -m darkcore serve`."""
    parser = argparse.ArgumentParser(
        description="Patchwork Dynamic Router — OpenAI-compatible inference server"
    )
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--host", type=str, default="127.0.0.1")
    args = parser.parse_args()

    app = create_app()
    try:
        import uvicorn
    except ImportError:
        raise ImportError("uvicorn required to run the server. Install: pip install uvicorn")

    print(f"Starting Patchwork Dynamic Router on {args.host}:{args.port}")
    print(f"  Health check: GET http://{args.host}:{args.port}/health  (?deep=1)")
    print(f"  Completions: POST http://{args.host}:{args.port}/v1/chat/completions")
    print(f"  Models: GET http://{args.host}:{args.port}/v1/models")
    print()
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
