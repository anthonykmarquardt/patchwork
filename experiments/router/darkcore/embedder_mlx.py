"""MLX port of the bge-small embedder — replaces the torch/transformers
query-path dependency (CONTINUE.md backlog item 5; parity gated by
embedder_parity.py).

Functional BERT encoder over the raw HF safetensors weights, fp32 throughout:
at 33M params the fp16 speedup is irrelevant and kNN class votes ride on
cosine *ordering*, so no precision is traded. Contract matches the torch
path exactly: CLS pooling, L2 normalize, np.float32 (384,) out.

Single-text embed only (the query path) — no padding, so no attention mask.
Tokenization via `tokenizers` (transitive dep); no transformers import.
"""
import glob
import math
import os

import mlx.core as mx
import numpy as np

MAX_LENGTH = 512


def _snapshot_dir(model_id):
    """Resolve the local HF cache snapshot (offline-first, like the router)."""
    pat = os.path.join(
        os.path.expanduser(os.environ.get("HF_HOME", "~/.cache/huggingface")),
        "hub", "models--" + model_id.replace("/", "--"), "snapshots", "*")
    hits = sorted(glob.glob(pat), key=os.path.getmtime)
    if not hits:
        raise FileNotFoundError(
            f"{model_id} not in HF cache — fetch it once without HF_HUB_OFFLINE")
    return hits[-1]


class MlxEmbedder:
    """Drop-in for the predictor's embed path: MlxEmbedder(id).warm().embed(t)."""

    def __init__(self, model_id):
        self.model_id = model_id
        self._w = None
        self._tok = None

    def warm(self):
        if self._w is None:
            from tokenizers import Tokenizer
            snap = _snapshot_dir(self.model_id)
            self._tok = Tokenizer.from_file(os.path.join(snap, "tokenizer.json"))
            self._tok.enable_truncation(max_length=MAX_LENGTH)
            self._tok.no_padding()
            w = mx.load(os.path.join(snap, "model.safetensors"))
            self._w = {k: v.astype(mx.float32) for k, v in w.items()}
            self._n_layers = 1 + max(
                int(k.split(".")[2]) for k in self._w if k.startswith("encoder.layer."))
            self._n_heads = 12  # bge-small (BertConfig num_attention_heads)
            self.embed("warmup")  # build kernels/cache at init, not first query
        return self

    # -- forward pieces (functional, over the raw weight dict) ----------------

    def _ln(self, x, prefix):
        return mx.fast.layer_norm(
            x, self._w[f"{prefix}.weight"], self._w[f"{prefix}.bias"], eps=1e-12)

    def _dense(self, x, prefix):
        return x @ self._w[f"{prefix}.weight"].T + self._w[f"{prefix}.bias"]

    def _layer(self, x, i):
        p = f"encoder.layer.{i}"
        L, D = x.shape
        H = self._n_heads
        hd = D // H
        # (L, D) -> (H, L, hd)
        q, k, v = (
            self._dense(x, f"{p}.attention.self.{n}")
            .reshape(L, H, hd).transpose(1, 0, 2)
            for n in ("query", "key", "value"))
        a = mx.softmax((q @ k.transpose(0, 2, 1)) / math.sqrt(hd), axis=-1)
        ctx = (a @ v).transpose(1, 0, 2).reshape(L, D)
        x = self._ln(x + self._dense(ctx, f"{p}.attention.output.dense"),
                     f"{p}.attention.output.LayerNorm")
        h = self._dense(x, f"{p}.intermediate.dense")
        h = h * (1 + mx.erf(h / math.sqrt(2))) / 2  # exact (erf) gelu, HF "gelu"
        return self._ln(x + self._dense(h, f"{p}.output.dense"),
                        f"{p}.output.LayerNorm")

    def embed(self, text):
        self.warm()
        ids = mx.array(self._tok.encode(text).ids)
        x = (self._w["embeddings.word_embeddings.weight"][ids]
             + self._w["embeddings.position_embeddings.weight"][: len(ids)]
             + self._w["embeddings.token_type_embeddings.weight"][0])
        x = self._ln(x, "embeddings.LayerNorm")
        for i in range(self._n_layers):
            x = self._layer(x, i)
        cls = x[0]
        cls = cls / mx.sqrt((cls * cls).sum())
        return np.array(cls, dtype=np.float32)
