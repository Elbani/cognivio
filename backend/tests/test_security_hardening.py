from __future__ import annotations

import secrets

import pytest

from app.core.config import settings
from app.core.email import send_member_added

pytestmark = pytest.mark.asyncio


async def _register(client, name: str = "Sam") -> dict:
    email = f"{name.lower()}_{secrets.token_hex(4)}@example.com"
    r = await client.post(
        "/api/auth/register", json={"email": email, "password": "password123", "name": name}
    )
    assert r.status_code == 201, r.text
    headers = {"Authorization": f"Bearer {r.json()['accessToken']}"}
    return {"email": email, "id": r.json()["user"]["id"], "headers": headers}


async def test_registration_can_be_closed(client, monkeypatch) -> None:
    monkeypatch.setattr(settings, "registration_open", False)
    r = await client.post(
        "/api/auth/register",
        json={"email": "late@example.com", "password": "password123", "name": "Late"},
    )
    assert r.status_code == 403


async def test_unverified_allowlisted_email_is_not_admin(client, monkeypatch, email_on) -> None:
    """Registering an ADMIN_EMAILS address must not grant the console before the
    account has proven it owns that address."""
    email = f"boss_{secrets.token_hex(4)}@example.com"
    monkeypatch.setattr(settings, "admin_emails", email)
    r = await client.post(
        "/api/auth/register", json={"email": email, "password": "password123", "name": "Boss"}
    )
    headers = {"Authorization": f"Bearer {r.json()['accessToken']}"}
    assert (await client.get("/api/admin/overview", headers=headers)).status_code == 403


async def test_only_owner_can_change_owner_role(client, monkeypatch) -> None:
    monkeypatch.setattr(settings, "self_hosted", True)  # teammates allowed
    owner = await _register(client, "Owner")
    admin = await _register(client, "Admin")
    third = await _register(client, "Third")
    org_id = (await client.get("/api/orgs", headers=owner["headers"])).json()[0]["id"]
    members = f"/api/orgs/{org_id}/members"

    r = await client.post(members, json={"email": admin["email"], "role": "admin"}, headers=owner["headers"])
    assert r.status_code == 201, r.text

    # An admin cannot mint an owner, demote the owner, or remove the owner.
    r = await client.post(members, json={"email": third["email"], "role": "owner"}, headers=admin["headers"])
    assert r.status_code == 403
    r = await client.patch(f"{members}/{owner['id']}", json={"role": "viewer"}, headers=admin["headers"])
    assert r.status_code == 403
    r = await client.delete(f"{members}/{owner['id']}", headers=admin["headers"])
    assert r.status_code == 403

    # The last owner cannot demote themselves.
    r = await client.patch(f"{members}/{owner['id']}", json={"role": "admin"}, headers=owner["headers"])
    assert r.status_code == 400


async def test_password_reset_ends_existing_sessions(client, monkeypatch) -> None:
    captured: dict[str, str] = {}

    async def fake_reset(to: str, name: str, url: str) -> bool:
        captured["url"] = url
        return True

    monkeypatch.setattr("app.api.auth.send_password_reset", fake_reset)
    client.cookies.clear()
    user = await _register(client, "Vic")
    assert (await client.post("/api/auth/refresh")).status_code == 200  # session is live

    await client.post("/api/auth/forgot-password", json={"email": user["email"]})
    token = captured["url"].split("token=", 1)[1]
    r = await client.post("/api/auth/reset-password", json={"token": token, "newPassword": "newpassword1"})
    assert r.status_code == 200

    # The refresh cookie issued before the reset no longer works.
    assert (await client.post("/api/auth/refresh")).status_code == 401
    client.cookies.clear()


async def test_email_escapes_user_controlled_names(monkeypatch) -> None:
    sent: dict[str, str] = {}

    async def fake_send(to: str, subject: str, html: str) -> bool:
        sent["html"] = html
        return True

    monkeypatch.setattr("app.core.email.send_email", fake_send)
    await send_member_added("a@example.com", '<a href="https://evil.example">Org</a>', "<b>Eve</b>")
    assert "<a href" not in sent["html"].split("organization")[0]
    assert "&lt;b&gt;Eve&lt;/b&gt;" in sent["html"]
