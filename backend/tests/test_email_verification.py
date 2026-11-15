from __future__ import annotations

import secrets

import pytest

pytestmark = pytest.mark.asyncio


async def test_registration_is_verified_when_email_is_disabled(client) -> None:
    """Without RESEND_API_KEY no link can be sent, so the account must not be gated."""
    reg = await client.post(
        "/api/auth/register",
        json={"email": f"noemail_{secrets.token_hex(4)}@example.com", "password": "password123", "name": "Nia"},
    )
    assert reg.status_code == 201, reg.text
    assert reg.json()["user"]["emailVerified"] is True
    H = {"Authorization": f"Bearer {reg.json()['accessToken']}"}
    assert (await client.get("/api/orgs", headers=H)).status_code == 200


async def test_unverified_user_is_gated_then_verifies(client, monkeypatch, email_on) -> None:
    captured: dict[str, str] = {}

    async def fake_verify(to: str, name: str, url: str) -> bool:
        captured["url"] = url
        return True

    monkeypatch.setattr("app.api.auth.send_verification", fake_verify)

    email = f"verif_{secrets.token_hex(4)}@example.com"
    reg = await client.post(
        "/api/auth/register", json={"email": email, "password": "password123", "name": "Val"}
    )
    assert reg.status_code == 201
    # the emailed link must be an absolute URL (not a relative path that email
    # clients mangle into http:///…)
    assert captured["url"].startswith("http://") or captured["url"].startswith("https://")
    assert "://verify-email" not in captured["url"]
    token = reg.json()["accessToken"]
    H = {"Authorization": f"Bearer {token}"}

    # signed in, but unverified → identity works, data access is blocked
    me = await client.get("/api/auth/me", headers=H)
    assert me.status_code == 200 and me.json()["emailVerified"] is False
    blocked = await client.get("/api/orgs", headers=H)
    assert blocked.status_code == 403

    # verify with the emailed token → data access opens up
    vtoken = captured["url"].split("token=", 1)[1]
    v = await client.post("/api/auth/verify-email", json={"token": vtoken})
    assert v.status_code == 200
    ok = await client.get("/api/orgs", headers=H)
    assert ok.status_code == 200
    assert (await client.get("/api/auth/me", headers=H)).json()["emailVerified"] is True

    # token is single-use
    again = await client.post("/api/auth/verify-email", json={"token": vtoken})
    assert again.status_code == 400


async def test_resend_verification(client, monkeypatch, email_on) -> None:
    sends: list[str] = []

    async def fake_verify(to: str, name: str, url: str) -> bool:
        sends.append(to)
        return True

    monkeypatch.setattr("app.api.auth.send_verification", fake_verify)
    email = f"resend_{secrets.token_hex(4)}@example.com"
    reg = await client.post(
        "/api/auth/register", json={"email": email, "password": "password123", "name": "Rex"}
    )
    H = {"Authorization": f"Bearer {reg.json()['accessToken']}"}
    sends.clear()  # ignore the registration send

    r = await client.post("/api/auth/resend-verification", headers=H)
    assert r.status_code == 200
    assert sends == [email]


async def test_verify_invalid_token(client) -> None:
    r = await client.post("/api/auth/verify-email", json={"token": "bogus-token-value"})
    assert r.status_code == 400
