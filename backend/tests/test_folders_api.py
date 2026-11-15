from __future__ import annotations

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


def _folders_url(ws: dict) -> str:
    return f"/api/teams/{ws['team_id']}/folders"


async def test_create_folder(client: AsyncClient, auth_headers, workspace) -> None:
    resp = await client.post(_folders_url(workspace), json={"name": "Projects"}, headers=auth_headers)
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "Projects"
    assert data["parentId"] is None
    assert data["teamId"] == workspace["team_id"]


async def test_create_subfolder(client: AsyncClient, auth_headers, workspace) -> None:
    parent = await client.post(_folders_url(workspace), json={"name": "Parent"}, headers=auth_headers)
    parent_id = parent.json()["id"]
    child = await client.post(
        _folders_url(workspace), json={"name": "Child", "parentId": parent_id}, headers=auth_headers
    )
    assert child.status_code == 201
    assert child.json()["parentId"] == parent_id


async def test_list_folders(client: AsyncClient, auth_headers, enterprise_workspace) -> None:
    workspace = enterprise_workspace  # two top-level projects = an Enterprise feature
    await client.post(_folders_url(workspace), json={"name": "Alpha"}, headers=auth_headers)
    await client.post(_folders_url(workspace), json={"name": "Beta"}, headers=auth_headers)
    resp = await client.get(_folders_url(workspace), headers=auth_headers)
    assert resp.status_code == 200
    names = [f["name"] for f in resp.json()]
    assert "Alpha" in names and "Beta" in names


async def test_rename_folder(client: AsyncClient, auth_headers, workspace) -> None:
    create = await client.post(_folders_url(workspace), json={"name": "Old Name"}, headers=auth_headers)
    folder_id = create.json()["id"]
    resp = await client.patch(
        f"/api/folders/{folder_id}", json={"name": "New Name"}, headers=auth_headers
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "New Name"


async def test_delete_folder_moves_memories_to_root(client: AsyncClient, auth_headers, workspace) -> None:
    folder = await client.post(_folders_url(workspace), json={"name": "Temp"}, headers=auth_headers)
    folder_id = folder.json()["id"]
    mem = await client.post(
        f"/api/teams/{workspace['team_id']}/memories",
        json={"title": "Filed", "folderId": folder_id},
        headers=auth_headers,
    )
    mid = mem.json()["id"]

    del_resp = await client.delete(f"/api/folders/{folder_id}", headers=auth_headers)
    assert del_resp.status_code == 204

    mem_resp = await client.get(f"/api/memories/{mid}", headers=auth_headers)
    assert mem_resp.json()["folderId"] is None


async def test_delete_folder_with_children_fails(client: AsyncClient, auth_headers, workspace) -> None:
    parent = await client.post(_folders_url(workspace), json={"name": "Parent"}, headers=auth_headers)
    parent_id = parent.json()["id"]
    await client.post(
        _folders_url(workspace), json={"name": "Child", "parentId": parent_id}, headers=auth_headers
    )
    resp = await client.delete(f"/api/folders/{parent_id}", headers=auth_headers)
    assert resp.status_code == 409


async def test_duplicate_folder_name_same_parent_fails(client: AsyncClient, auth_headers, enterprise_workspace) -> None:
    workspace = enterprise_workspace  # needs two top-level folders to hit the name clash
    assert (
        await client.post(_folders_url(workspace), json={"name": "Unique"}, headers=auth_headers)
    ).status_code == 201
    assert (
        await client.post(_folders_url(workspace), json={"name": "Unique"}, headers=auth_headers)
    ).status_code == 409


async def test_folder_cannot_be_its_own_parent(client: AsyncClient, auth_headers, workspace) -> None:
    folder = await client.post(_folders_url(workspace), json={"name": "Self"}, headers=auth_headers)
    folder_id = folder.json()["id"]
    resp = await client.patch(
        f"/api/folders/{folder_id}", json={"parentId": folder_id}, headers=auth_headers
    )
    assert resp.status_code == 400
