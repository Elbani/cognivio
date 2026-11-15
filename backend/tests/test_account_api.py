import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def test_update_profile_name(client: AsyncClient, auth_headers: dict[str, str]):
    resp = await client.patch("/api/auth/me", headers=auth_headers, json={"name": "  New Name  "})
    assert resp.status_code == 200, resp.text
    assert resp.json()["name"] == "New Name"

    # persisted
    me = await client.get("/api/auth/me", headers=auth_headers)
    assert me.json()["name"] == "New Name"


async def test_update_profile_rejects_blank(client: AsyncClient, auth_headers: dict[str, str]):
    resp = await client.patch("/api/auth/me", headers=auth_headers, json={"name": ""})
    assert resp.status_code == 422


async def test_change_password_flow(client: AsyncClient):
    reg = await client.post(
        "/api/auth/register",
        json={"email": "pw@example.com", "password": "password123", "name": "PW User"},
    )
    assert reg.status_code == 201, reg.text
    headers = {"Authorization": f"Bearer {reg.json()['accessToken']}"}

    # wrong current password is rejected
    bad = await client.post(
        "/api/auth/password",
        headers=headers,
        json={"currentPassword": "wrongpass", "newPassword": "brandnew123"},
    )
    assert bad.status_code == 400

    # correct change succeeds
    ok = await client.post(
        "/api/auth/password",
        headers=headers,
        json={"currentPassword": "password123", "newPassword": "brandnew123"},
    )
    assert ok.status_code == 204

    # old password no longer works, new one does
    old_login = await client.post(
        "/api/auth/login", json={"email": "pw@example.com", "password": "password123"}
    )
    assert old_login.status_code == 401
    new_login = await client.post(
        "/api/auth/login", json={"email": "pw@example.com", "password": "brandnew123"}
    )
    assert new_login.status_code == 200


async def test_account_endpoints_require_auth(client: AsyncClient):
    assert (await client.patch("/api/auth/me", json={"name": "x"})).status_code == 401
    assert (
        await client.post(
            "/api/auth/password",
            json={"currentPassword": "a", "newPassword": "brandnew123"},
        )
    ).status_code == 401
