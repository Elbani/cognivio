from __future__ import annotations

import pytest
import pytest_asyncio

from app.core import config

pytestmark = pytest.mark.asyncio

ADMIN_EMAIL = "admin@cognivio.app"


@pytest_asyncio.fixture(loop_scope="session")
async def admin_headers(client, mongo_db, monkeypatch) -> dict[str, str]:
    monkeypatch.setattr(config.settings, "admin_emails", ADMIN_EMAIL)
    resp = await client.post(
        "/api/auth/register",
        json={"email": ADMIN_EMAIL, "password": "password123", "name": "Admin"},
    )
    assert resp.status_code == 201, resp.text
    await mongo_db.users.update_one({"email": ADMIN_EMAIL}, {"$set": {"emailVerified": True}})
    return {"Authorization": f"Bearer {resp.json()['accessToken']}"}


async def test_appearance_defaults_are_public(client):
    r = await client.get("/api/appearance")
    assert r.status_code == 200
    body = r.json()
    assert body["userTheme"] == "editorial"
    assert body["updatedAt"] is None


async def test_non_admin_cannot_change_appearance(client, auth_headers):
    r = await client.put("/api/admin/appearance", json={"userTheme": "terminal"}, headers=auth_headers)
    assert r.status_code == 403


async def test_admin_changes_theme(client, admin_headers, mongo_db):
    r = await client.put(
        "/api/admin/appearance", json={"userTheme": "terminal"}, headers=admin_headers
    )
    assert r.status_code == 200, r.text
    assert r.json()["userTheme"] == "terminal"
    assert r.json()["updatedBy"] == "admin@cognivio.app"

    # Visible to everyone, no auth needed.
    pub = await client.get("/api/appearance")
    assert pub.json()["userTheme"] == "terminal"

    # Logged like every other admin action.
    action = await mongo_db.admin_actions.find_one({"action": "appearance.update"})
    assert action is not None
    assert "userTheme: editorial to terminal" in action["reason"]


async def test_appearance_rejects_unknown_theme_and_empty_update(client, admin_headers):
    r = await client.put("/api/admin/appearance", json={"userTheme": "neon"}, headers=admin_headers)
    assert r.status_code == 400
    r = await client.put("/api/admin/appearance", json={}, headers=admin_headers)
    assert r.status_code == 400
