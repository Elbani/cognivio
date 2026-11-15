from __future__ import annotations

import secrets

import pytest

pytestmark = pytest.mark.asyncio


async def _register(client, email, password="oldpassword1", name="Rae"):
    r = await client.post(
        "/api/auth/register", json={"email": email, "password": password, "name": name}
    )
    assert r.status_code == 201, r.text


async def test_reset_flow(client, monkeypatch) -> None:
    captured: dict[str, str] = {}

    async def fake_reset(to: str, name: str, url: str) -> bool:
        captured["to"] = to
        captured["url"] = url
        return True

    monkeypatch.setattr("app.api.auth.send_password_reset", fake_reset)

    email = f"reset_{secrets.token_hex(4)}@example.com"
    await _register(client, email)

    # request a reset → token arrives via the (patched) email
    r = await client.post("/api/auth/forgot-password", json={"email": email})
    assert r.status_code == 200
    assert captured.get("to") == email
    token = captured["url"].split("token=", 1)[1]

    # reset with the token
    rr = await client.post(
        "/api/auth/reset-password", json={"token": token, "newPassword": "newpassword1"}
    )
    assert rr.status_code == 200

    # old password no longer works; new one does
    assert (await client.post("/api/auth/login", json={"email": email, "password": "oldpassword1"})).status_code == 401
    assert (await client.post("/api/auth/login", json={"email": email, "password": "newpassword1"})).status_code == 200

    # token is single-use
    again = await client.post(
        "/api/auth/reset-password", json={"token": token, "newPassword": "another123"}
    )
    assert again.status_code == 400


async def test_forgot_unknown_email_is_silent(client) -> None:
    """Unknown email still returns 200 (no account-existence leak)."""
    r = await client.post("/api/auth/forgot-password", json={"email": "nobody_xyz@example.com"})
    assert r.status_code == 200


async def test_reset_invalid_token(client) -> None:
    r = await client.post(
        "/api/auth/reset-password", json={"token": "bogus-token-value", "newPassword": "newpassword1"}
    )
    assert r.status_code == 400
