"""The seam contract (server.py), pinned via TestClient + a stub router.

Seam 1: route on last user message, generate with full context.
Seam 2: X-Patchwork-Route-Id header + patchwork extension object.
Seam 3: real usage from the winning attempt; total spend in the extension.
Seam 4: SSE — progress as comments, content only after verification, [DONE].
Seam 6: /health?deep=1 state report."""
import json

from fastapi.testclient import TestClient

from darkcore.server import create_app


def trace(attempts, tier="T1", klass="reasoning", escalations=1, flagged=False):
    return {
        "route_id": "r0ute1d000000", "qhash": "abc", "class": klass,
        "prefilter": {}, "predictor": {}, "start_tier": "T0", "floor": "T0",
        "attempts": attempts, "total_ms": 42.0, "router_overhead_ms": 0.5,
        "config_version": 3,
    }


ATTEMPTS = [
    {"tier": "T0", "outcome": "fail", "tokens": 13, "prompt_tokens": 10,
     "gen_ms": 5.0, "load_ms": 0, "ttft_ms": 1, "tps": 1, "verify_ms": 0.1, "rung": 1},
    {"tier": "T1", "outcome": "pass", "tokens": 40, "prompt_tokens": 66,
     "gen_ms": 9.0, "load_ms": 0, "ttft_ms": 1, "tps": 1, "verify_ms": 0.1, "rung": 1},
]


class StubRouter:
    def __init__(self, answer="the answer", attempts=ATTEMPTS, events=(), exc=None):
        self.exc = exc
        self.events = list(events)
        self.result = {
            "answer": answer, "tier": "T1", "escalations": 1, "flagged": False,
            "trace": trace(attempts),
        }
        self.calls = []
        # deep-health internals contract
        self._config = {"config_version": 3, "updated_by": "operator",
                        "params": {"tier_roster": [
                            {"id": "T0", "model": "m0"}, {"id": "T1", "model": "m1"}]}}
        self._prior = None

        class _Pool:
            _live = {"T1": object()}
        self._pool = _Pool()

    def route(self, query, expected=None, on_event=None, messages=None):
        self.calls.append({"query": query, "messages": messages})
        if self.exc:
            raise self.exc
        if on_event:
            for name, fields in self.events:
                on_event(name, **fields)
        return self.result


def client(stub):
    return TestClient(create_app(router=stub), raise_server_exceptions=False)


CONVO = [
    {"role": "system", "content": "be terse"},
    {"role": "user", "content": "first question"},
    {"role": "assistant", "content": "first answer"},
    {"role": "user", "content": "second question"},
]


# ------------------------------------------------------------------- seam 1
def test_routes_on_last_user_generates_with_full_context():
    stub = StubRouter()
    r = client(stub).post("/v1/chat/completions", json={"messages": CONVO})
    assert r.status_code == 200
    call = stub.calls[0]
    assert call["query"] == "second question"
    assert call["messages"] == CONVO                     # nothing dropped


def test_unknown_roles_and_empty_content_filtered():
    stub = StubRouter()
    messages = [{"role": "tool", "content": "x"},
                {"role": "user", "content": ""},
                {"role": "user", "content": "real"}]
    client(stub).post("/v1/chat/completions", json={"messages": messages})
    assert stub.calls[0]["messages"] == [{"role": "user", "content": "real"}]


def test_400_when_no_user_message():
    r = client(StubRouter()).post(
        "/v1/chat/completions",
        json={"messages": [{"role": "system", "content": "s"}]})
    assert r.status_code == 400


# --------------------------------------------------------------- seams 2 + 3
def test_route_id_in_header_and_body():
    r = client(StubRouter()).post("/v1/chat/completions",
                                  json={"messages": CONVO})
    body = r.json()
    assert r.headers["x-patchwork-route-id"] == "r0ute1d000000"
    assert body["patchwork"]["route_id"] == "r0ute1d000000"
    assert body["patchwork"]["tier"] == "T1"
    assert body["patchwork"]["routed_class"] == "reasoning"


def test_usage_is_winning_attempt_ext_is_total_spend():
    r = client(StubRouter()).post("/v1/chat/completions",
                                  json={"messages": CONVO})
    body = r.json()
    assert body["usage"] == {"prompt_tokens": 66, "completion_tokens": 40,
                             "total_tokens": 106}
    assert body["patchwork"]["total_generation_tokens"] == 53   # 13 + 40
    assert [a["tier"] for a in body["patchwork"]["attempts"]] == ["T0", "T1"]


def test_unavailable_attempts_excluded_from_usage():
    attempts = [{"tier": "T0", "outcome": "unavailable"}] + ATTEMPTS[1:]
    r = client(StubRouter(attempts=attempts)).post(
        "/v1/chat/completions", json={"messages": CONVO})
    body = r.json()
    assert body["usage"]["completion_tokens"] == 40
    assert body["patchwork"]["total_generation_tokens"] == 40


def test_router_error_is_500_with_detail():
    r = client(StubRouter(exc=RuntimeError("boom"))).post(
        "/v1/chat/completions", json={"messages": CONVO})
    assert r.status_code == 500
    assert "boom" in r.text


# ------------------------------------------------------------------- seam 4
def _sse_parts(text):
    datas, comments = [], []
    for block in text.split("\n\n"):
        block = block.strip()
        if block.startswith("data: "):
            datas.append(block[len("data: "):])
        elif block.startswith(":"):
            comments.append(block)
    return datas, comments


def test_stream_progress_then_verified_content_then_done():
    stub = StubRouter(answer="A" * 200,
                      events=[("dispatch", {"tier": "T0", "attempt": 1}),
                              ("verdict", {"tier": "T0", "passed": False}),
                              ("escalation", {"from_tier": "T0", "to_tier": "T1"})])
    r = client(stub).post("/v1/chat/completions",
                          json={"messages": CONVO, "stream": True})
    assert r.headers["content-type"].startswith("text/event-stream")
    datas, comments = _sse_parts(r.text)

    assert any("T0 answering" in c for c in comments)
    assert any("escalating T0 → T1" in c for c in comments)

    assert datas[-1] == "[DONE]"
    chunks = [json.loads(d) for d in datas[:-1]]
    assert chunks[0]["choices"][0]["delta"] == {"role": "assistant"}
    content = "".join(c["choices"][0]["delta"].get("content", "") for c in chunks)
    assert content == "A" * 200                          # verified answer, complete
    final = chunks[-1]
    assert final["choices"][0]["finish_reason"] == "stop"
    assert final["usage"]["completion_tokens"] == 40
    assert final["patchwork"]["route_id"] == "r0ute1d000000"


def test_stream_error_yields_error_object_then_done():
    r = client(StubRouter(exc=RuntimeError("mid-climb crash"))).post(
        "/v1/chat/completions", json={"messages": CONVO, "stream": True})
    datas, _ = _sse_parts(r.text)
    assert datas[-1] == "[DONE]"
    err = json.loads(datas[-2])
    assert err["error"]["type"] == "RuntimeError"


# ------------------------------------------------------------------- seam 6
def test_health_shallow_and_deep():
    c = client(StubRouter())
    shallow = c.get("/health").json()
    assert shallow["status"] == "ok" and "config_version" not in shallow
    deep = c.get("/health?deep=1").json()
    assert deep["config_version"] == 3
    assert deep["predictor"] == {"enabled": False}
    assert deep["tiers"] == [{"id": "T0", "model": "m0", "resident": False},
                             {"id": "T1", "model": "m1", "resident": True}]
    assert deep["busy"] is False


def test_models_endpoint_single_model():
    data = client(StubRouter()).get("/v1/models").json()
    assert [m["id"] for m in data["data"]] == ["patchwork-dynamic-router"]
