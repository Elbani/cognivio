"""Hybrid retrieval: semantic similarity blends with lexical scoring in context_pack.

Embeddings are disabled under TESTING (no model is loaded), so these tests inject vectors
directly, patching the query embedder and writing doc `embedding` fields, to exercise the
blend/qualify logic deterministically without downloading or running a model.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.core.embeddings import cosine

pytestmark = pytest.mark.asyncio


async def _make_key(client, auth_headers, org_id, scopes):
    resp = await client.post(
        f"/api/orgs/{org_id}/keys", json={"name": "agent", "scopes": scopes}, headers=auth_headers
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["key"]


async def test_cosine_normalized_vectors() -> None:
    assert cosine([1.0, 0.0, 0.0], [1.0, 0.0, 0.0]) == pytest.approx(1.0)
    assert cosine([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)
    assert cosine(None, [1.0]) == 0.0
    assert cosine([1.0, 0.0], [1.0]) == 0.0  # dimension mismatch → 0


async def test_semantic_surfaces_a_lexical_miss(
    client: AsyncClient, auth_headers, workspace, mongo_db, monkeypatch
) -> None:
    """A doc that shares NO query words still surfaces when its embedding is close to the
    query vector, proving semantic recall, not just lexical."""
    org_id, team_id = workspace["org_id"], workspace["team_id"]

    # Two docs whose text does NOT contain the query terms.
    lexical_miss = await client.post(
        f"/api/teams/{team_id}/memories",
        json={"title": "Photosynthesis primer", "type": "note", "content": "chlorophyll and sunlight"},
        headers=auth_headers,
    )
    unrelated = await client.post(
        f"/api/teams/{team_id}/memories",
        json={"title": "Knitting patterns", "type": "note", "content": "purl and casting on"},
        headers=auth_headers,
    )
    hit_id, miss_id = lexical_miss.json()["id"], unrelated.json()["id"]

    # Inject embeddings: the query vector matches `hit_id` exactly, is orthogonal to the other.
    qvec = [1.0, 0.0, 0.0, 0.0]
    await mongo_db.memories.update_one({"_id": hit_id}, {"$set": {"embedding": [1.0, 0.0, 0.0, 0.0]}})
    await mongo_db.memories.update_one({"_id": miss_id}, {"$set": {"embedding": [0.0, 1.0, 0.0, 0.0]}})

    async def fake_embed_query(_q):
        return qvec

    monkeypatch.setattr("app.api.agent.embed_query", fake_embed_query)

    key = await _make_key(client, auth_headers, org_id, ["memory:read"])
    H = {"Authorization": f"Bearer {key}"}
    # A query that lexically matches NEITHER doc.
    ctx = await client.get("/api/v1/context", params={"q": "xyzzy unrelated terms"}, headers=H)
    body = ctx.json()
    ids = [r["id"] for r in body["results"]]

    assert body["retrievalMode"] == "hybrid"
    assert hit_id in ids          # surfaced purely on semantic similarity
    assert miss_id not in ids     # orthogonal embedding + no lexical match → excluded
    # Quality signals are present on each result.
    hit = next(r for r in body["results"] if r["id"] == hit_id)
    assert "stale" in hit and "helpful" in hit and "lastVerifiedAt" in hit


async def test_disabled_embeddings_keep_lexical_mode(
    client: AsyncClient, auth_headers, workspace
) -> None:
    """With embeddings off (the TESTING default), retrieval reports lexical mode and a
    lexical query still works."""
    org_id, team_id = workspace["org_id"], workspace["team_id"]
    await client.post(
        f"/api/teams/{team_id}/memories",
        json={"title": "Caching strategy", "type": "note", "content": "redis cache layer"},
        headers=auth_headers,
    )
    key = await _make_key(client, auth_headers, org_id, ["memory:read"])
    H = {"Authorization": f"Bearer {key}"}
    ctx = await client.get("/api/v1/context", params={"q": "caching strategy"}, headers=H)
    body = ctx.json()
    assert body["retrievalMode"] == "lexical"
    assert any(r["title"] == "Caching strategy" for r in body["results"])
