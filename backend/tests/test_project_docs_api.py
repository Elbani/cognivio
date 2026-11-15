"""Project documentation: agent publishes versioned snapshots, humans read/diff them.

Covers the round trip, the agent (ak_ key) publishes via /api/v1, each publish becomes a
new version with exactly one "current", and the human REST surface returns the current doc,
the version history, and a section diff. Also asserts the hard separation invariant: project
docs never leak into agent retrieval (context_pack / search).
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


async def _make_key(client, auth_headers, org_id, scopes):
    resp = await client.post(
        f"/api/orgs/{org_id}/keys", json={"name": "agent", "scopes": scopes}, headers=auth_headers
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["key"]


def _sections(overview: str, arch: str):
    return [
        {"slug": "overview", "title": "Overview", "order": 0, "content": overview},
        {"slug": "architecture", "title": "Architecture", "order": 1, "content": arch},
    ]


async def test_publish_versions_and_diff(
    client: AsyncClient, auth_headers, workspace
) -> None:
    org_id, team_id = workspace["org_id"], workspace["team_id"]
    key = await _make_key(client, auth_headers, org_id, ["memory:read", "memory:write"])
    H = {"Authorization": f"Bearer {key}"}

    # The plan endpoint works before anything is published.
    plan = await client.get(f"/api/v1/teams/{team_id}/project-docs/plan", headers=H)
    assert plan.status_code == 200, plan.text
    assert plan.json()["hasDocs"] is False
    assert any(s["slug"] == "overview" for s in plan.json()["recommendedSections"])

    # First publish → version 1, current.
    pub1 = await client.post(
        f"/api/v1/teams/{team_id}/project-docs",
        json={"summary": "initial", "sections": _sections("Hello world.", "Two services.")},
        headers=H,
    )
    assert pub1.status_code == 201, pub1.text
    assert pub1.json()["version"] == 1 and pub1.json()["status"] == "current"

    # Second publish → version 2; the prior becomes archived (only one current).
    pub2 = await client.post(
        f"/api/v1/teams/{team_id}/project-docs",
        json={"summary": "expand arch", "sections": _sections("Hello world.", "Three services now.")},
        headers=H,
    )
    assert pub2.status_code == 201
    assert pub2.json()["version"] == 2

    # Human surface: current is v2.
    cur = await client.get(f"/api/teams/{team_id}/project-docs", headers=auth_headers)
    assert cur.status_code == 200, cur.text
    body = cur.json()
    assert body["hasDocs"] is True
    assert body["current"]["version"] == 2
    assert body["versionCount"] == 2
    arch = next(s for s in body["current"]["sections"] if s["slug"] == "architecture")
    assert arch["content"] == "Three services now."

    # Version history lists both, newest first, without bodies.
    vers = await client.get(f"/api/teams/{team_id}/project-docs/versions", headers=auth_headers)
    nums = [v["version"] for v in vers.json()["versions"]]
    assert nums == [2, 1]

    # Diff v1 → v2: architecture changed, overview unchanged.
    diff = await client.get(
        f"/api/teams/{team_id}/project-docs/diff", params={"from": 1, "to": 2}, headers=auth_headers
    )
    assert diff.status_code == 200, diff.text
    by_slug = {s["slug"]: s for s in diff.json()["sections"]}
    assert by_slug["architecture"]["status"] == "changed"
    assert "Three services now." in by_slug["architecture"]["diff"]
    assert by_slug["overview"]["status"] == "unchanged"


async def test_project_docs_never_in_agent_retrieval(
    client: AsyncClient, auth_headers, workspace
) -> None:
    """The defining invariant: published project docs must not surface via context_pack
    or memory search, they're a separate human surface."""
    org_id, team_id = workspace["org_id"], workspace["team_id"]
    key = await _make_key(client, auth_headers, org_id, ["memory:read", "memory:write"])
    H = {"Authorization": f"Bearer {key}"}

    marker = "zzqquux distinctive documentation phrase"
    await client.post(
        f"/api/v1/teams/{team_id}/project-docs",
        json={"summary": "x", "sections": [
            {"slug": "overview", "title": "Overview", "order": 0, "content": marker},
        ]},
        headers=H,
    )

    ctx = await client.get("/api/v1/context", params={"q": marker}, headers=H)
    assert ctx.status_code == 200
    assert all(marker not in (r.get("excerpt") or "") for r in ctx.json()["results"])

    search = await client.get(f"/api/v1/teams/{team_id}/memories", params={"q": marker}, headers=H)
    assert search.status_code == 200
    assert search.json().get("memories", []) == []


async def test_publish_requires_write_scope(
    client: AsyncClient, auth_headers, workspace
) -> None:
    org_id, team_id = workspace["org_id"], workspace["team_id"]
    read_only = await _make_key(client, auth_headers, org_id, ["memory:read"])
    resp = await client.post(
        f"/api/v1/teams/{team_id}/project-docs",
        json={"summary": "x", "sections": _sections("a", "b")},
        headers={"Authorization": f"Bearer {read_only}"},
    )
    assert resp.status_code == 403
