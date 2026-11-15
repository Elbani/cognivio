from __future__ import annotations

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


async def _make_key(client, auth_headers, org_id, scopes, team_id=None):
    body = {"name": "agent", "scopes": scopes}
    if team_id:
        body["teamId"] = team_id
    resp = await client.post(f"/api/orgs/{org_id}/keys", json=body, headers=auth_headers)
    assert resp.status_code == 201, resp.text
    return resp.json()["key"]


async def test_create_key_returns_full_key_once(client, auth_headers, workspace) -> None:
    resp = await client.post(
        f"/api/orgs/{workspace['org_id']}/keys",
        json={"name": "ci", "scopes": ["memory:read"]},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["key"].startswith("ak_")
    assert data["prefix"].startswith("ak_")
    # listing must never expose the secret
    listing = await client.get(f"/api/orgs/{workspace['org_id']}/keys", headers=auth_headers)
    for k in listing.json():
        assert "key" not in k
        assert "keyHash" not in k


async def test_agent_whoami_and_teams(client, auth_headers, workspace) -> None:
    key = await _make_key(client, auth_headers, workspace["org_id"], ["memory:read"])
    H = {"Authorization": f"Bearer {key}"}

    who = await client.get("/api/v1/whoami", headers=H)
    assert who.status_code == 200
    assert who.json()["scopes"] == ["memory:read"]

    teams = await client.get("/api/v1/teams", headers=H)
    assert teams.status_code == 200
    assert workspace["team_id"] in [t["id"] for t in teams.json()]


async def test_agent_rule_returns_per_editor_file(client, auth_headers, workspace) -> None:
    key = await _make_key(client, auth_headers, workspace["org_id"], ["memory:read"])
    H = {"Authorization": f"Bearer {key}"}

    # Cursor MUST get the always-applied frontmatter, without it the rule isn't loaded
    # every turn, which is the whole reason this endpoint exists.
    cur = await client.get("/api/v1/agent-rule", params={"tool": "cursor"}, headers=H)
    assert cur.status_code == 200, cur.text
    body = cur.json()
    assert body["path"] == ".cursor/rules/cognivio.mdc"
    assert body["append"] is False
    assert body["content"].startswith("---\n")
    assert "alwaysApply: true" in body["content"]
    assert "prime_context" in body["content"] and "write_memory" in body["content"]
    assert "instructions" in body

    # Claude Code / Codex get a plain Markdown section meant to be appended.
    claude = (await client.get("/api/v1/agent-rule", params={"tool": "claude"}, headers=H)).json()
    assert claude["path"] == "CLAUDE.md" and claude["append"] is True
    assert "alwaysApply" not in claude["content"]

    bad = await client.get("/api/v1/agent-rule", params={"tool": "nano"}, headers=H)
    assert bad.status_code == 400


async def test_agent_reads_map(client, auth_headers, workspace) -> None:
    # seed a map memory + a linked playbook
    arch = await client.post(
        f"/api/teams/{workspace['team_id']}/memories",
        json={"title": "System Architecture", "type": "architecture"},
        headers=auth_headers,
    )
    await client.post(
        f"/api/teams/{workspace['team_id']}/memories",
        json={"title": "Team Map", "type": "map", "content": "See [[System Architecture]]"},
        headers=auth_headers,
    )

    key = await _make_key(client, auth_headers, workspace["org_id"], ["map:read", "memory:read"])
    H = {"Authorization": f"Bearer {key}"}
    resp = await client.get(f"/api/v1/teams/{workspace['team_id']}/map", headers=H)
    assert resp.status_code == 200
    data = resp.json()
    assert data["mapMemory"]["title"] == "Team Map"
    assert any(e["target"] == arch.json()["id"] for e in data["edges"])


async def test_agent_search_and_get(client, auth_headers, workspace) -> None:
    created = await client.post(
        f"/api/teams/{workspace['team_id']}/memories",
        json={"title": "Searchable Playbook", "type": "playbook", "content": "rollback steps"},
        headers=auth_headers,
    )
    mid = created.json()["id"]
    key = await _make_key(client, auth_headers, workspace["org_id"], ["memory:read"])
    H = {"Authorization": f"Bearer {key}"}

    found = await client.get(
        f"/api/v1/teams/{workspace['team_id']}/memories?q=rollback", headers=H
    )
    assert mid in [m["id"] for m in found.json()["memories"]]

    one = await client.get(f"/api/v1/memories/{mid}", headers=H)
    assert one.status_code == 200
    assert one.json()["content"] == "rollback steps"


async def test_agent_write_back_requires_scope(client, auth_headers, workspace) -> None:
    ro_key = await _make_key(client, auth_headers, workspace["org_id"], ["memory:read"])
    H = {"Authorization": f"Bearer {ro_key}"}
    denied = await client.post(
        f"/api/v1/teams/{workspace['team_id']}/memories",
        json={"title": "nope", "type": "lesson"},
        headers=H,
    )
    assert denied.status_code == 403

    rw_key = await _make_key(client, auth_headers, workspace["org_id"], ["memory:write"])
    H2 = {"Authorization": f"Bearer {rw_key}"}
    ok = await client.post(
        f"/api/v1/teams/{workspace['team_id']}/memories",
        json={"title": "Lesson from incident", "type": "lesson", "content": "always check the map"},
        headers=H2,
    )
    assert ok.status_code == 201
    assert ok.json()["source"] == "agent"


async def test_revoked_key_rejected(client, auth_headers, workspace) -> None:
    resp = await client.post(
        f"/api/orgs/{workspace['org_id']}/keys",
        json={"name": "temp", "scopes": ["memory:read"]},
        headers=auth_headers,
    )
    key_id = resp.json()["id"]
    key = resp.json()["key"]
    H = {"Authorization": f"Bearer {key}"}
    assert (await client.get("/api/v1/whoami", headers=H)).status_code == 200

    await client.delete(f"/api/orgs/{workspace['org_id']}/keys/{key_id}", headers=auth_headers)
    assert (await client.get("/api/v1/whoami", headers=H)).status_code == 401


async def test_team_restricted_key_cannot_cross_teams(client, auth_headers, enterprise_workspace) -> None:
    workspace = enterprise_workspace  # a second team is an Enterprise feature
    other = await client.post(
        f"/api/orgs/{workspace['org_id']}/teams", json={"name": "Other Team"}, headers=auth_headers
    )
    other_id = other.json()["id"]

    key = await _make_key(
        client, auth_headers, workspace["org_id"], ["memory:read"], team_id=workspace["team_id"]
    )
    H = {"Authorization": f"Bearer {key}"}
    denied = await client.get(f"/api/v1/teams/{other_id}/memories", headers=H)
    assert denied.status_code == 403

    teams = await client.get("/api/v1/teams", headers=H)
    assert [t["id"] for t in teams.json()] == [workspace["team_id"]]


async def test_agent_related_returns_neighbors(client, auth_headers, workspace) -> None:
    target = await client.post(
        f"/api/teams/{workspace['team_id']}/memories",
        json={"title": "Hub", "type": "architecture"},
        headers=auth_headers,
    )
    target_id = target.json()["id"]
    source = await client.post(
        f"/api/teams/{workspace['team_id']}/memories",
        json={"title": "Spoke", "type": "playbook", "content": "depends on [[Hub]]"},
        headers=auth_headers,
    )
    source_id = source.json()["id"]

    key = await _make_key(client, auth_headers, workspace["org_id"], ["memory:read"])
    H = {"Authorization": f"Bearer {key}"}

    # outbound: Spoke -> Hub
    fwd = await client.get(f"/api/v1/memories/{source_id}/related", headers=H)
    assert target_id in [m["id"] for m in fwd.json()["memories"]]
    # backlink: Hub <- Spoke
    back = await client.get(f"/api/v1/memories/{target_id}/related", headers=H)
    assert source_id in [m["id"] for m in back.json()["memories"]]


async def test_human_activity_feed_reflects_agent(client, auth_headers, workspace) -> None:
    key = await _make_key(client, auth_headers, workspace["org_id"], ["map:read", "memory:read"])
    H = {"Authorization": f"Bearer {key}"}
    await client.get(f"/api/v1/teams/{workspace['team_id']}/map", headers=H)
    await client.get(f"/api/v1/teams/{workspace['team_id']}/memories?q=anything", headers=H)

    feed = await client.get(f"/api/teams/{workspace['team_id']}/activity", headers=auth_headers)
    assert feed.status_code == 200
    actions = [e["action"] for e in feed.json()["entries"]]
    assert "map.read" in actions
    assert "memory.search" in actions


async def test_invalid_key_rejected(client) -> None:
    resp = await client.get("/api/v1/whoami", headers={"Authorization": "Bearer ak_not_real"})
    assert resp.status_code == 401


async def test_memory_templates_available(client) -> None:
    resp = await client.get("/api/memory-templates")
    assert resp.status_code == 200
    data = resp.json()
    assert "playbook" in data and "map" in data and "incident" in data
