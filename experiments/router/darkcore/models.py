"""Swap-aware model pool — the residency policy Exp 4 paid for.

Measured (specs/0001/results.md §Exp 4, M2 16 GB):
  T0+T1 co-reside at 2.93 GB Metal peak with ZERO throughput penalty;
  T2 (7.86 GB) is the only tier that needs the box to itself.
So: loading T0/T1 evicts only T2; loading T2 evicts everything.
Every load/evict is telemetered (swap latency is part of the cost model).
"""
import gc
import re
import time

from . import telemetry

CORESIDENT = {"T0", "T1"}  # empirically safe together (Exp 4)
_THINK = re.compile(r"<think>.*?</think>\s*", re.S)


class TierUnavailable(Exception):
    pass


class ModelPool:
    def __init__(self, roster):
        self.roster = {t["id"]: t for t in roster}
        self.order = [t["id"] for t in roster]
        self._live = {}  # tier_id -> (model, tokenizer)
        # Set when an exclusive (non-coresident) tier is loaded: its memory
        # footprint pages out other residents (e.g. the class-prior embedder —
        # measured 197 ms page-fault classify after a T2 climb). The router
        # re-warms dependents at the end of the route that caused it.
        self.exclusive_used = False

    def _evict(self, tier_id, reason):
        if tier_id in self._live:
            t0 = time.perf_counter()
            del self._live[tier_id]
            gc.collect()
            try:
                import mlx.core as mx
                mx.clear_cache()
            except ImportError:
                pass
            telemetry.emit("model_evicted", tier=tier_id, reason=reason,
                           evict_ms=round((time.perf_counter() - t0) * 1000, 1))

    def acquire(self, tier_id):
        """Return (model, tokenizer, load_ms). load_ms=0 when already resident."""
        if tier_id in self._live:
            return (*self._live[tier_id], 0.0)

        # residency policy (Exp 4)
        if tier_id not in CORESIDENT:
            self.exclusive_used = True
            for other in list(self._live):
                self._evict(other, f"exclusive_load_{tier_id}")
        else:
            for other in list(self._live):
                if other not in CORESIDENT:
                    self._evict(other, f"coresident_load_{tier_id}")

        spec = self.roster[tier_id]
        t0 = time.perf_counter()
        try:
            from mlx_lm import load
            model, tokenizer = load(spec["model"])
        except Exception as e:
            telemetry.emit("tier_unavailable", level="error", tier=tier_id,
                           error_type=type(e).__name__, message=str(e)[:200])
            raise TierUnavailable(tier_id) from e
        load_ms = round((time.perf_counter() - t0) * 1000, 1)
        self._live[tier_id] = (model, tokenizer)
        telemetry.emit("model_loaded", tier=tier_id, model=spec["model"],
                       load_ms=load_ms)
        return model, tokenizer, load_ms

    def generate(self, tier_id, user_text, max_tokens=None, messages=None):
        """Run one generation on a tier. Returns a result dict (content stays
        in-process; telemetry sees only numbers).

        `messages` (optional): full conversation [{role, content}, ...] — the
        seam-1 contract: the router *routes* on the last user message but
        *generates* with the whole context (system + history)."""
        from mlx_lm import stream_generate
        model, tokenizer, load_ms = self.acquire(tier_id)
        spec = self.roster[tier_id]
        max_tokens = max_tokens or spec["max_tokens"]

        convo = messages or [{"role": "user", "content": user_text}]
        if tokenizer.chat_template is not None:
            prompt = tokenizer.apply_chat_template(
                convo, tokenize=False, add_generation_prompt=True)
        else:
            prompt = ("\n\n".join(f'{m["role"]}: {m["content"]}' for m in convo)
                      if messages else user_text)

        t0 = time.perf_counter()
        ttft_ms, n_tok, chunks, last = None, 0, [], None
        for resp in stream_generate(model, tokenizer, prompt, max_tokens=max_tokens):
            if ttft_ms is None:
                ttft_ms = round((time.perf_counter() - t0) * 1000, 1)
            chunks.append(resp.text)
            n_tok += 1
            last = resp
        gen_ms = round((time.perf_counter() - t0) * 1000, 1)

        raw = "".join(chunks)
        answer = _THINK.sub("", raw)
        # Bonsai-27B CoT-as-prose leak: narrates reasoning with NO opening
        # <think>, then closes it — everything before the last bare </think>
        # is chain-of-thought, not answer (CONTINUE.md residual seam #6).
        if "</think>" in answer:
            answer = answer.rsplit("</think>", 1)[1]
        answer = answer.strip() or raw.strip()  # never emit empty; keep raw as last resort
        return {
            "answer": answer,
            "tier": tier_id,
            "load_ms": load_ms,
            "ttft_ms": ttft_ms or 0.0,
            "gen_ms": gen_ms,
            "tokens": n_tok,
            "prompt_tokens": int(getattr(last, "prompt_tokens", 0) or 0) if last else 0,
            "tps": round(getattr(last, "generation_tps", 0.0), 2) if last else 0.0,
        }

    def next_tier(self, tier_id):
        i = self.order.index(tier_id)
        return self.order[i + 1] if i + 1 < len(self.order) else None
