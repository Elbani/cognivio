from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def _make_key(client, auth_headers, org_id, scopes):
    r = await client.post(
        f"/api/orgs/{org_id}/keys", json={"name": "agent", "scopes": scopes}, headers=auth_headers
    )
    assert r.status_code == 201
    return r.json()["key"]


async def test_edit_snapshots_and_restore(client, auth_headers, workspace) -> None:
    team = workspace["team_id"]
    created = await client.post(
        f"/api/teams/{team}/memories",
        json={"title": "Doc", "type": "note", "content": "v1 content"}, headers=auth_headers,
    )
    mid = created.json()["id"]

    # no versions until the first edit
    v0 = await client.get(f"/api/memories/{mid}/versions", headers=auth_headers)
    assert v0.json()["versions"] == []

    # edit twice → two snapshots of the prior states
    await client.patch(f"/api/memories/{mid}", json={"content": "v2 content"}, headers=auth_headers)
    await client.patch(f"/api/memories/{mid}", json={"content": "v3 content"}, headers=auth_headers)

    versions = (await client.get(f"/api/memories/{mid}/versions", headers=auth_headers)).json()["versions"]
    assert len(versions) == 2  # snapshots of v1 and v2 (newest first)

    # newest snapshot holds the v2 content; oldest holds v1
    newest = await client.get(f"/api/memories/{mid}/versions/{versions[0]['id']}", headers=auth_headers)
    assert newest.json()["content"] == "v2 content"
    oldest = await client.get(f"/api/memories/{mid}/versions/{versions[1]['id']}", headers=auth_headers)
    assert oldest.json()["content"] == "v1 content"

    # restore v1 → current content reverts, and the restore snapshots v3
    restored = await client.post(
        f"/api/memories/{mid}/versions/{versions[1]['id']}/restore", headers=auth_headers
    )
    assert restored.json()["content"] == "v1 content"
    after = (await client.get(f"/api/memories/{mid}/versions", headers=auth_headers)).json()["versions"]
    assert len(after) == 3
    assert (await client.get(f"/api/memories/{mid}/versions/{after[0]['id']}", headers=auth_headers)).json()["content"] == "v3 content"


async def test_agent_upsert_snapshots(client, auth_headers, workspace) -> None:
    """An agent re-writing an existing title snapshots the prior content."""
    team, org = workspace["team_id"], workspace["org_id"]
    await client.post(
        f"/api/teams/{team}/memories",
        json={"title": "Shared", "type": "note", "content": "human version"}, headers=auth_headers,
    )
    key = await _make_key(client, auth_headers, org, ["memory:write"])
    H = {"Authorization": f"Bearer {key}"}
    upserted = await client.post(
        f"/api/v1/teams/{team}/memories",
        json={"title": "Shared", "type": "note", "content": "agent rewrite"}, headers=H,
    )
    mid = upserted.json()["id"]
    versions = (await client.get(f"/api/memories/{mid}/versions", headers=auth_headers)).json()["versions"]
    assert len(versions) == 1
    v = await client.get(f"/api/memories/{mid}/versions/{versions[0]['id']}", headers=auth_headers)
    assert v.json()["content"] == "human version"
