from __future__ import annotations

import secrets

import pytest

pytestmark = pytest.mark.asyncio


async def test_refresh_then_logout(client) -> None:
    email = f"refresh_{secrets.token_hex(4)}@example.com"
    reg = await client.post(
        "/api/auth/register", json={"email": email, "password": "password123", "name": "Ref"}
    )
    assert reg.status_code == 201
    # registration set the refresh-token cookie; refresh mints a new access token
    r = await client.post("/api/auth/refresh")
    assert r.status_code == 200
    assert r.json()["user"]["email"] == email
    assert r.json()["accessToken"]

    # logout revokes the refresh token; refresh then fails
    out = await client.post("/api/auth/logout")
    assert out.status_code == 204
    r2 = await client.post("/api/auth/refresh")
    assert r2.status_code == 401


async def test_refresh_without_cookie(client) -> None:
    client.cookies.clear()
    r = await client.post("/api/auth/refresh")
    assert r.status_code == 401
