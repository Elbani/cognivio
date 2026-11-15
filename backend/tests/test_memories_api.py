from __future__ import annotations

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


def _mem_url(ws: dict) -> str:
    return f"/api/teams/{ws['team_id']}/memories"


async def test_create_memory_defaults_to_note(client: AsyncClient, auth_headers, workspace) -> None:
    resp = await client.post(
        _mem_url(workspace),
        json={"title": "First memory", "content": "Hello world", "tags": ["demo"]},
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["title"] == "First memory"
    assert data["type"] == "note"
    assert data["status"] == "active"
    assert data["source"] == "manual"
    assert data["tags"] == ["demo"]
    assert data["linkedMemoryIds"] == []
    assert data["teamId"] == workspace["team_id"]
    assert data["lastVerifiedAt"] is not None


async def test_create_typed_memory(client: AsyncClient, auth_headers, workspace) -> None:
    resp = await client.post(
        _mem_url(workspace),
        json={"title": "Upgrade Playbook", "type": "playbook", "content": "steps"},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    assert resp.json()["type"] == "playbook"


async def test_list_excludes_content(client: AsyncClient, auth_headers, workspace) -> None:
    await client.post(
        _mem_url(workspace),
        json={"title": "Memo A", "content": "should not appear in list"},
        headers=auth_headers,
    )
    resp = await client.get(_mem_url(workspace), headers=auth_headers)
    assert resp.status_code == 200
    memories = resp.json()["memories"]
    assert len(memories) >= 1
    for m in memories:
        assert "content" not in m


async def test_filter_by_type(client: AsyncClient, auth_headers, workspace) -> None:
    await client.post(
        _mem_url(workspace), json={"title": "Arch Doc", "type": "architecture"}, headers=auth_headers
    )
    await client.post(
        _mem_url(workspace), json={"title": "A Note", "type": "note"}, headers=auth_headers
    )
    resp = await client.get(f"{_mem_url(workspace)}?type=architecture", headers=auth_headers)
    titles = [m["title"] for m in resp.json()["memories"]]
    assert "Arch Doc" in titles
    assert "A Note" not in titles


async def test_get_includes_content(client: AsyncClient, auth_headers, workspace) -> None:
    create = await client.post(
        _mem_url(workspace), json={"title": "Detail", "content": "Full content"}, headers=auth_headers
    )
    mid = create.json()["id"]
    resp = await client.get(f"/api/memories/{mid}", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["content"] == "Full content"


async def test_update_content_refreshes_links(client: AsyncClient, auth_headers, workspace) -> None:
    target = await client.post(
        _mem_url(workspace), json={"title": "Target", "content": ""}, headers=auth_headers
    )
    target_id = target.json()["id"]
    source = await client.post(
        _mem_url(workspace), json={"title": "Source", "content": "no links"}, headers=auth_headers
    )
    source_id = source.json()["id"]

    resp = await client.patch(
        f"/api/memories/{source_id}",
        json={"content": "Link to [[Target]]"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert target_id in resp.json()["linkedMemoryIds"]


async def test_unresolved_wiki_links(client: AsyncClient, auth_headers, workspace) -> None:
    resp = await client.post(
        _mem_url(workspace),
        json={"title": "Broken", "content": "See [[Nonexistent]]"},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    assert "Nonexistent" in resp.json()["unresolvedLinks"]
    assert resp.json()["linkedMemoryIds"] == []


async def test_verify_endpoint(client: AsyncClient, auth_headers, workspace) -> None:
    create = await client.post(
        _mem_url(workspace), json={"title": "Verify me"}, headers=auth_headers
    )
    mid = create.json()["id"]
    resp = await client.post(f"/api/memories/{mid}/verify", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["lastVerifiedAt"] is not None
    assert resp.json()["verifiedBy"] is not None


async def test_trash_and_restore(client: AsyncClient, auth_headers, workspace) -> None:
    create = await client.post(_mem_url(workspace), json={"title": "Trashable"}, headers=auth_headers)
    mid = create.json()["id"]

    assert (await client.delete(f"/api/memories/{mid}", headers=auth_headers)).status_code == 204

    listed = await client.get(_mem_url(workspace), headers=auth_headers)
    assert mid not in [m["id"] for m in listed.json()["memories"]]

    trash = await client.get(f"{_mem_url(workspace)}/trash", headers=auth_headers)
    assert mid in [m["id"] for m in trash.json()["memories"]]

    restored = await client.post(f"/api/memories/{mid}/restore", headers=auth_headers)
    assert restored.status_code == 200
    assert restored.json()["deletedAt"] is None


async def test_permanent_delete(client: AsyncClient, auth_headers, workspace) -> None:
    create = await client.post(_mem_url(workspace), json={"title": "Deletable"}, headers=auth_headers)
    mid = create.json()["id"]
    await client.delete(f"/api/memories/{mid}", headers=auth_headers)
    perm = await client.delete(f"/api/memories/{mid}/permanent", headers=auth_headers)
    assert perm.status_code == 204


async def test_move_memory_to_project(client: AsyncClient, auth_headers, workspace) -> None:
    folder = await client.post(
        f"/api/teams/{workspace['team_id']}/folders", json={"name": "Work"}, headers=auth_headers
    )
    folder_id = folder.json()["id"]
    mem = await client.post(_mem_url(workspace), json={"title": "Filed"}, headers=auth_headers)
    mid = mem.json()["id"]

    update = await client.patch(
        f"/api/memories/{mid}", json={"folderId": folder_id}, headers=auth_headers
    )
    assert update.status_code == 200
    assert update.json()["folderId"] == folder_id


async def test_search_matches_content(client: AsyncClient, auth_headers, workspace) -> None:
    await client.post(
        _mem_url(workspace),
        json={"title": "Grocery", "content": "Buy quinoa"},
        headers=auth_headers,
    )
    resp = await client.get(f"{_mem_url(workspace)}?q=quinoa", headers=auth_headers)
    titles = [m["title"] for m in resp.json()["memories"]]
    assert "Grocery" in titles


async def test_tag_normalization(client: AsyncClient, auth_headers, workspace) -> None:
    resp = await client.post(
        _mem_url(workspace),
        json={"title": "Tags", "tags": ["  Research ", "DEMO", "demo"]},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    assert resp.json()["tags"] == ["research", "demo"]


async def test_unauthorized_returns_401(client: AsyncClient, workspace) -> None:
    resp = await client.get(_mem_url(workspace))
    assert resp.status_code == 401


async def test_team_map_endpoint(client: AsyncClient, auth_headers, workspace) -> None:
    arch = await client.post(
        _mem_url(workspace),
        json={"title": "Architecture", "type": "architecture"},
        headers=auth_headers,
    )
    await client.post(
        _mem_url(workspace),
        json={"title": "Team Map", "type": "map", "content": "Start at [[Architecture]]"},
        headers=auth_headers,
    )
    resp = await client.get(f"/api/teams/{workspace['team_id']}/map", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["mapMemory"]["title"] == "Team Map"
    assert any(e["target"] == arch.json()["id"] for e in data["edges"])
    assert len(data["nodes"]) >= 2


async def test_non_member_forbidden(client: AsyncClient, workspace) -> None:
    await client.post(
        "/api/auth/register",
        json={"email": "outsider@example.com", "password": "password123", "name": "Outsider"},
    )
    tok = (
        await client.post(
            "/api/auth/login",
            json={"email": "outsider@example.com", "password": "password123"},
        )
    ).json()["accessToken"]
    headers = {"Authorization": f"Bearer {tok}"}
    resp = await client.get(_mem_url(workspace), headers=headers)
    assert resp.status_code == 403
