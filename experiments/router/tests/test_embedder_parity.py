"""Embedder parity — mlx port vs frozen torch reference vectors.

Opt-in (loads the 33M bge-small model — the default suite stays model-free):

    DARKCORE_PARITY=1 uv run pytest tests/test_embedder_parity.py -v

The frozen reference (fixtures/embedder-parity/torch.npy) was captured by
`embedder_parity.py capture` on 2026-07-18 with torch 2.13 — regenerating it
requires reinstalling torch, so treat it as immutable.
"""
import json
import os

import numpy as np
import pytest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PARITY = os.path.join(HERE, "fixtures", "embedder-parity")

pytestmark = pytest.mark.skipif(
    os.environ.get("DARKCORE_PARITY") != "1",
    reason="model-loading test; set DARKCORE_PARITY=1 to run",
)


@pytest.fixture(scope="module")
def vectors():
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    from darkcore.embedder_mlx import MlxEmbedder

    ref = np.load(os.path.join(PARITY, "torch.npy"))
    meta = json.load(open(os.path.join(PARITY, "texts.json")))
    emb = MlxEmbedder("BAAI/bge-small-en-v1.5").warm()
    E = np.stack([emb.embed(t) for t in meta["texts"]]).astype(np.float32)
    return ref, E


def test_cosine_agreement(vectors):
    ref, E = vectors
    cos = (E * ref).sum(axis=1)
    assert cos.min() >= 0.9999


def test_knn_ordering_identical(vectors):
    ref, E = vectors
    for i in range(len(ref)):
        assert np.array_equal(
            np.argsort(-(ref @ ref[i])), np.argsort(-(E @ E[i])))


def test_unit_norm(vectors):
    _, E = vectors
    assert np.allclose(np.linalg.norm(E, axis=1), 1.0, atol=1e-5)
