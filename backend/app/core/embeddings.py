"""Self-hosted text embeddings for semantic / hybrid retrieval.

Uses `fastembed` (ONNX runtime, no PyTorch) with a small CPU model so KB/code content
never leaves the server, consistent with the "no third-party model calls on KB content"
stance (analytics is server-side-only; seeding is agent-side). Everything here degrades
gracefully: if the library or model can't load (or under TESTING), `embeddings_enabled()`
is False and every function is a no-op / returns None, so retrieval falls back to lexical.

Vectors are L2-normalized at store and query time, so cosine similarity is a plain dot
product (`cosine`). Embeddings are stored on each memory doc (`embedding`, `embeddingModel`)
and never returned by the API.
"""

from __future__ import annotations

import asyncio
import logging
import math
import os

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.core.config import settings

logger = logging.getLogger("app.embeddings")

# Chars of content fed to the embedder. bge-small handles ~512 tokens; this keeps the
# encode bounded and dominated by the most relevant top-of-doc text.
_DOC_TEXT_CAP = 8000

_model = None
_load_attempted = False


def embeddings_enabled() -> bool:
    """Embeddings are on only when configured AND not running tests. Tests must stay
    offline/fast and deterministic, so we never load a model under TESTING."""
    return settings.embeddings_enabled and not os.getenv("TESTING")


def _get_model():
    """Lazy-load the model once. Any failure (lib missing, download/init error) disables
    embeddings for the process rather than raising, callers fall back to lexical."""
    global _model, _load_attempted
    if _load_attempted:
        return _model
    _load_attempted = True
    if not embeddings_enabled():
        return None
    try:
        from fastembed import TextEmbedding

        _model = TextEmbedding(
            model_name=settings.embedding_model,
            cache_dir=settings.embedding_cache_dir or None,
        )
        logger.info("Embedding model loaded: %s", settings.embedding_model)
    except Exception as exc:  # noqa: BLE001 - lib missing / model load failure → degrade
        logger.warning(
            "Embeddings disabled (could not load %s): %s", settings.embedding_model, exc
        )
        _model = None
    return _model


def active_model_name() -> str | None:
    return settings.embedding_model if _get_model() is not None else None


def warm() -> None:
    """Trigger the (slow) first model load. Call in a background task at startup so the
    first real request doesn't pay the download/init cost."""
    _get_model()


def _normalize(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / norm for x in vec]


def _embed_sync(texts: list[str]) -> list[list[float]] | None:
    model = _get_model()
    if model is None:
        return None
    return [_normalize([float(x) for x in v]) for v in model.embed(texts)]


async def embed_texts(texts: list[str]) -> list[list[float]] | None:
    """Embed a batch off the event loop (encoding is CPU-bound). None when disabled."""
    if not texts or not embeddings_enabled():
        return None
    return await asyncio.to_thread(_embed_sync, texts)


async def embed_query(q: str) -> list[float] | None:
    if not q or not q.strip():
        return None
    res = await embed_texts([q.strip()])
    return res[0] if res else None


def _doc_text(title: str, content: str, tags: list[str]) -> str:
    parts = [title or ""]
    if tags:
        parts.append(" ".join(tags))
    parts.append((content or "")[:_DOC_TEXT_CAP])
    return "\n\n".join(p for p in parts if p)


async def embed_document(title: str, content: str, tags: list[str]) -> list[float] | None:
    res = await embed_texts([_doc_text(title, content, tags)])
    return res[0] if res else None


async def embed_and_store(
    db: AsyncIOMotorDatabase, memory_id: str, title: str, content: str, tags: list[str]
) -> None:
    """Compute and persist a memory's embedding. No-op when embeddings are disabled, so
    every write path can call it unconditionally."""
    vec = await embed_document(title, content, tags)
    if vec is None:
        return
    await db.memories.update_one(
        {"_id": memory_id},
        {"$set": {"embedding": vec, "embeddingModel": settings.embedding_model}},
    )


def cosine(a: list[float] | None, b: list[float] | None) -> float:
    """Cosine similarity. Inputs are L2-normalized at store/query time, so this is just a
    dot product. Returns 0.0 for missing/mismatched vectors."""
    if not a or not b or len(a) != len(b):
        return 0.0
    return sum(x * y for x, y in zip(a, b))
