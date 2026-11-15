"""Backfill semantic embeddings onto existing memories.

Embeddings are computed on every write going forward (see app.core.embeddings), so this
is a one-time pass for docs that predate the feature, or a re-embed when the model
changes. Idempotent: skips docs already embedded with the current model unless --force.

Run from the backend directory (with embeddings enabled and the model available):

    python -m scripts.backfill_embeddings            # only docs missing/stale embeddings
    python -m scripts.backfill_embeddings --force    # re-embed everything
"""

from __future__ import annotations

import argparse
import asyncio

from motor.motor_asyncio import AsyncIOMotorClient

from app.core.config import settings
from app.core.embeddings import active_model_name, embeddings_enabled, embed_document


async def run(force: bool) -> None:
    if not embeddings_enabled():
        raise SystemExit(
            "Embeddings are disabled (EMBEDDINGS_ENABLED/TESTING) or the model could not "
            "load. Enable them and ensure fastembed + the model are available, then re-run."
        )
    model = active_model_name()
    if model is None:
        raise SystemExit("Embedding model failed to load; aborting.")

    client = AsyncIOMotorClient(settings.mongo_uri, tz_aware=True)
    db = client[settings.mongo_db]

    query: dict = {"deletedAt": None}
    if not force:
        query["$or"] = [{"embedding": {"$exists": False}}, {"embeddingModel": {"$ne": model}}]

    total = await db.memories.count_documents(query)
    print(f"Embedding {total} memories with {model}{' (force)' if force else ''}…")

    done = 0
    async for m in db.memories.find(query, {"title": 1, "content": 1, "tags": 1}):
        vec = await embed_document(m.get("title", ""), m.get("content", ""), m.get("tags", []))
        if vec is not None:
            await db.memories.update_one(
                {"_id": m["_id"]}, {"$set": {"embedding": vec, "embeddingModel": model}}
            )
        done += 1
        if done % 50 == 0:
            print(f"  {done}/{total}")

    print(f"Done. Embedded {done} docs.")
    client.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="re-embed all docs")
    asyncio.run(run(parser.parse_args().force))
