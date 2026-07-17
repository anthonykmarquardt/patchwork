"""OpenAI-compatible inference endpoint for the dark-core router.

Exposes /v1/chat/completions, /v1/models, /health. Dark-operable:
works standalone with zero external config. The router manages T0/T1/T2
lifecycle; this server translates HTTP requests to route() calls.

Run: python -m darkcore.server [--port 8000] [--host 127.0.0.1]
"""
import argparse
import json
import time
import uuid
from datetime import datetime, timezone
from typing import Optional

try:
    from fastapi import FastAPI, HTTPException, Request
    from fastapi.responses import JSONResponse
    from pydantic import BaseModel
except ImportError:
    raise ImportError(
        "FastAPI required for server mode. Install: pip install fastapi uvicorn"
    )

from . import router as router_module


# OpenAI-compatible request/response models
class ChatMessage(BaseModel):
    role: str  # "system", "user", "assistant"
    content: str


class ChatCompletionRequest(BaseModel):
    model: str = "patchwork-dynamic-router"
    messages: list[ChatMessage]
    temperature: Optional[float] = 0.7
    max_tokens: Optional[int] = None
    top_p: Optional[float] = 1.0
    frequency_penalty: Optional[float] = 0.0
    presence_penalty: Optional[float] = 0.0


class ChoiceDelta(BaseModel):
    role: Optional[str] = None
    content: Optional[str] = None


class Choice(BaseModel):
    index: int
    message: ChatMessage
    finish_reason: str


class Usage(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class ChatCompletionResponse(BaseModel):
    id: str
    object: str = "chat.completion"
    created: int
    model: str
    choices: list[Choice]
    usage: Usage


class ErrorResponse(BaseModel):
    error: dict


def create_app():
    """Assemble the FastAPI app with dark-core router."""
    app = FastAPI(title="Patchwork Dynamic Router", version="0.2")
    router_singleton = router_module.Router()

    def extract_user_message(messages: list[ChatMessage]) -> str:
        """Extract the last user message as the query."""
        for msg in reversed(messages):
            if msg.role == "user":
                return msg.content
        raise ValueError("No user message found in request")

    @app.get("/health")
    async def health():
        """Liveness probe (kubernetes, load balancers)."""
        return {"status": "ok", "model": "patchwork-dynamic-router"}

    @app.get("/v1/models")
    async def list_models():
        """OpenAI-compatible model listing."""
        return {
            "object": "list",
            "data": [
                {
                    "id": "patchwork-dynamic-router",
                    "object": "model",
                    "owned_by": "patchwork",
                    "permission": [
                        {
                            "id": "modelperm-0",
                            "object": "model_permission",
                            "created": int(time.time()),
                            "allow_create_engine": False,
                            "allow_sampling": True,
                            "allow_logprobs": False,
                            "allow_search_indices": False,
                            "allow_view": True,
                            "allow_fine_tuning": False,
                            "organization": "*",
                            "group_id": None,
                            "is_blocking": False,
                        }
                    ],
                }
            ],
        }

    @app.post("/v1/chat/completions")
    async def chat_completions(req: ChatCompletionRequest) -> ChatCompletionResponse:
        """OpenAI-compatible chat completion endpoint.

        The router handles all classification, escalation, and verification.
        Caller is transparent to which tier answered (trace is in telemetry only).
        """
        try:
            query = extract_user_message(req.messages)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

        # Call the dark-core router
        try:
            result = router_singleton.route(query)
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Router error: {type(e).__name__}: {str(e)[:200]}",
            )

        # Translate to OpenAI response
        completion_id = f"chatcmpl-{uuid.uuid4().hex[:24]}"
        now = int(datetime.now(timezone.utc).timestamp())

        # Token counting: rough approximation (real would call the model)
        prompt_tokens = len(query.split()) + 10  # rough
        completion_tokens = len(result["answer"].split()) + 5

        return ChatCompletionResponse(
            id=completion_id,
            created=now,
            model="patchwork-dynamic-router",
            choices=[
                Choice(
                    index=0,
                    message=ChatMessage(role="assistant", content=result["answer"]),
                    finish_reason="stop",
                )
            ],
            usage=Usage(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=prompt_tokens + completion_tokens,
            ),
        )

    @app.exception_handler(Exception)
    async def exception_handler(request: Request, exc: Exception):
        """Global error handler."""
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "message": str(exc)[:200],
                    "type": type(exc).__name__,
                    "param": None,
                    "code": None,
                }
            },
        )

    return app


def main():
    parser = argparse.ArgumentParser(
        description="Patchwork Dynamic Router — OpenAI-compatible inference server"
    )
    parser.add_argument(
        "--port", type=int, default=8000, help="Port to listen on (default 8000)"
    )
    parser.add_argument(
        "--host",
        type=str,
        default="127.0.0.1",
        help="Host to bind to (default 127.0.0.1)",
    )
    parser.add_argument(
        "--workers", type=int, default=1, help="Number of worker processes (default 1)"
    )
    args = parser.parse_args()

    app = create_app()

    try:
        import uvicorn

        print(f"Starting Patchwork Dynamic Router on {args.host}:{args.port}")
        print(f"  Health check: GET http://{args.host}:{args.port}/health")
        print(f"  Completions: POST http://{args.host}:{args.port}/v1/chat/completions")
        print(f"  Models: GET http://{args.host}:{args.port}/v1/models")
        print()

        uvicorn.run(
            app,
            host=args.host,
            port=args.port,
            workers=args.workers,
            log_level="info",
        )
    except ImportError:
        raise ImportError("uvicorn required to run the server. Install: pip install uvicorn")


if __name__ == "__main__":
    main()
