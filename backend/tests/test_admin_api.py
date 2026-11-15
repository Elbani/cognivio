from __future__ import annotations

import secrets

import pytest
import pytest_asyncio

from app.core import config

pytestmark = pytest.mark.asyncio

ADMIN_EMAIL = "admin@cognivio.app"


@pytest_asyncio.fixture(loop_scope="session")
async def admin_headers(client, mongo_db, monkeypatch) -> dict[str, str]:
    """Register a user and put them on the ADMIN_EMAILS allowlist."""
    monkeypatch.setattr(config.settings, "admin_emails", ADMIN_EMAIL)
    resp = await client.post(
        "/api/auth/register",
        json={"email": ADMIN_EMAIL, "password": "password123", "name": "Admin"},
    )
    assert resp.status_code == 201, resp.text
    await mongo_db.users.update_one({"email": ADMIN_EMAIL}, {"$set": {"emailVerified": True}})
    return {"Authorization": f"Bearer {resp.json()['accessToken']}"}


async def _make_user(client, mongo_db, *, verified: bool = True) -> dict:
    """Register a throwaway user; return ids + token + headers."""
    email = f"user_{secrets.token_hex(4)}@example.com"
    resp = await client.post(
        "/api/auth/register",
        json={"email": email, "password": "password123", "name": "Victim"},
    )
    assert resp.status_code == 201, resp.text
    if verified:
        await mongo_db.users.update_one({"email": email}, {"$set": {"emailVerified": True}})
    user = await mongo_db.users.find_one({"email": email})
    membership = await mongo_db.memberships.find_one({"userId": str(user["_id"]), "teamId": None})
    return {
        "email": email,
        "id": str(user["_id"]),
        "token": resp.json()["accessToken"],
        "headers": {"Authorization": f"Bearer {resp.json()['accessToken']}"},
        "org_id": membership["orgId"],
    }


# --- Gate ---


async def test_admin_gate_blocks_non_admin(client, auth_headers):
    r = await client.get("/api/admin/overview", headers=auth_headers)
    assert r.status_code == 403


async def test_admin_gate_blocks_anonymous(client):
    r = await client.get("/api/admin/overview")
    assert r.status_code == 401


async def test_admin_can_access_overview(client, admin_headers):
    r = await client.get("/api/admin/overview", headers=admin_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["totals"]["users"] >= 1
    assert "signupTrend" in body
    assert "security" in body


# --- Usage analytics ---


async def _seed_activity(mongo_db, org_id: str, *, key_id: str, key_name: str) -> None:
    """Drop a handful of agent actions into audit_log for the given org/key."""
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    rows = [
        {"action": "context.pack", "resultCount": 2},   # retrieval hit
        {"action": "context.pack", "resultCount": 0},   # retrieval miss
        {"action": "memory.create"},
    ]
    for i, r in enumerate(rows):
        await mongo_db.audit_log.insert_one({
            "_id": f"audit_{key_id}_{i}", "orgId": org_id, "actor": "agent",
            "keyId": key_id, "keyName": key_name, "at": now, **r,
        })


async def test_platform_usage_aggregates_activity(client, admin_headers, mongo_db):
    u = await _make_user(client, mongo_db)
    await _seed_activity(mongo_db, u["org_id"], key_id="k_plat", key_name="agent-1")

    r = await client.get("/api/admin/usage?days=30", headers=admin_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["totals"]["actions"] >= 3
    assert body["totals"]["activeOrgs"] >= 1
    assert body["totals"]["activeKeys"] >= 1
    assert body["byAction"].get("context.pack", 0) >= 2
    assert len(body["trend"]) == 30 and body["trend"][-1]["count"] >= 3
    # 1 hit of 2 retrieval lookups
    assert body["retrieval"]["lookups"] >= 2 and body["retrieval"]["hits"] >= 1
    assert any(o["orgId"] == u["org_id"] for o in body["topOrgs"])
    assert any(k["keyId"] == "k_plat" for k in body["topKeys"])


async def test_user_usage_aggregates_across_orgs(client, admin_headers, mongo_db):
    u = await _make_user(client, mongo_db)
    await _seed_activity(mongo_db, u["org_id"], key_id="k_user", key_name="agent-x")
    # the key must exist for per-key enrichment (name/prefix/revoked)
    await mongo_db.api_keys.insert_one({
        "_id": "k_user", "orgId": u["org_id"], "name": "agent-x",
        "prefix": "ak_test", "revokedAt": None, "scopes": ["memory:read"],
    })

    r = await client.get(f"/api/admin/users/{u['id']}/usage?days=30", headers=admin_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["email"] == u["email"]
    assert body["totals"]["actions"] >= 3
    assert body["totals"]["lastActiveAt"] is not None
    assert any(o["orgId"] == u["org_id"] and o["actions"] >= 3 for o in body["perOrg"])
    key_row = next((k for k in body["perKey"] if k["keyId"] == "k_user"), None)
    assert key_row is not None and key_row["keyName"] == "agent-x" and key_row["actions"] >= 3
    assert body["retrieval"]["hitRate"] is not None


async def test_user_usage_404_for_unknown_user(client, admin_headers):
    r = await client.get("/api/admin/users/000000000000000000000000/usage", headers=admin_headers)
    assert r.status_code == 404


# --- Suspend / unsuspend ---


async def test_suspend_blocks_login_and_session(client, admin_headers, mongo_db):
    victim = await _make_user(client, mongo_db)

    # the victim's access token works before suspension
    assert (await client.get("/api/orgs", headers=victim["headers"])).status_code == 200

    r = await client.post(
        f"/api/admin/users/{victim['id']}/suspend?reason=spam", headers=admin_headers
    )
    assert r.status_code == 200

    # existing access token is now rejected (403 Account suspended)
    assert (await client.get("/api/orgs", headers=victim["headers"])).status_code == 403
    # fresh login is blocked
    login = await client.post(
        "/api/auth/login", json={"email": victim["email"], "password": "password123"}
    )
    assert login.status_code == 403

    # unsuspend restores access
    r = await client.post(f"/api/admin/users/{victim['id']}/unsuspend", headers=admin_headers)
    assert r.status_code == 200
    login = await client.post(
        "/api/auth/login", json={"email": victim["email"], "password": "password123"}
    )
    assert login.status_code == 200


async def test_cannot_suspend_or_delete_admin(client, admin_headers, mongo_db):
    admin = await mongo_db.users.find_one({"email": ADMIN_EMAIL})
    aid = str(admin["_id"])
    assert (await client.post(f"/api/admin/users/{aid}/suspend", headers=admin_headers)).status_code == 400
    assert (await client.delete(f"/api/admin/users/{aid}", headers=admin_headers)).status_code == 400


# --- Cascade deletes ---


async def test_delete_user_cascades(client, admin_headers, mongo_db):
    victim = await _make_user(client, mongo_db)
    org_id = victim["org_id"]
    # seed a memory under the victim's org
    await mongo_db.memories.insert_one(
        {"_id": secrets.token_hex(12), "orgId": org_id, "teamId": "t", "deletedAt": None, "title": "x"}
    )

    r = await client.delete(f"/api/admin/users/{victim['id']}", headers=admin_headers)
    assert r.status_code == 200, r.text

    assert await mongo_db.users.find_one({"_id": victim["id"]}) is None
    assert await mongo_db.organizations.find_one({"_id": org_id}) is None
    assert await mongo_db.memberships.count_documents({"userId": victim["id"]}) == 0
    assert await mongo_db.memories.count_documents({"orgId": org_id}) == 0


async def test_delete_org_cascades(client, admin_headers, mongo_db):
    victim = await _make_user(client, mongo_db)
    org_id = victim["org_id"]
    await mongo_db.memories.insert_one(
        {"_id": secrets.token_hex(12), "orgId": org_id, "teamId": "t", "deletedAt": None, "title": "y"}
    )

    r = await client.delete(f"/api/admin/orgs/{org_id}", headers=admin_headers)
    assert r.status_code == 200, r.text
    assert await mongo_db.organizations.find_one({"_id": org_id}) is None
    assert await mongo_db.memories.count_documents({"orgId": org_id}) == 0
    assert await mongo_db.teams.count_documents({"orgId": org_id}) == 0
    # the user themselves is untouched by an org delete
    assert await mongo_db.users.find_one({"_id": __import__("bson").ObjectId(victim["id"])}) is not None


# --- Security + action logs ---


async def test_failed_login_recorded_in_security_panel(client, admin_headers):
    await client.post(
        "/api/auth/login", json={"email": "nobody@example.com", "password": "wrongpass1"}
    )
    r = await client.get("/api/admin/security?type=failed_login", headers=admin_headers)
    assert r.status_code == 200
    events = r.json()["events"]
    assert any(e["type"] == "failed_login" for e in events)


async def test_admin_actions_are_logged(client, admin_headers, mongo_db):
    victim = await _make_user(client, mongo_db)
    await client.post(f"/api/admin/users/{victim['id']}/suspend?reason=test", headers=admin_headers)
    r = await client.get("/api/admin/actions", headers=admin_headers)
    assert r.status_code == 200
    actions = r.json()["actions"]
    assert any(a["action"] == "user.suspend" and a["targetEmail"] == victim["email"] for a in actions)


async def test_list_users_search(client, admin_headers, mongo_db):
    victim = await _make_user(client, mongo_db)
    r = await client.get(f"/api/admin/users?q={victim['email']}", headers=admin_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["total"] >= 1
    assert any(u["email"] == victim["email"] for u in body["users"])


# --- Plan management ---


async def test_set_org_plan(client, admin_headers, mongo_db):
    victim = await _make_user(client, mongo_db)
    org_id = victim["org_id"]

    r = await client.post(f"/api/admin/orgs/{org_id}/plan?plan=enterprise", headers=admin_headers)
    assert r.status_code == 200, r.text
    assert r.json()["plan"] == "enterprise"
    org = await mongo_db.organizations.find_one({"_id": org_id})
    assert org["plan"] == "enterprise"

    # the change is recorded in the admin action log
    actions = (await client.get("/api/admin/actions", headers=admin_headers)).json()["actions"]
    assert any(a["action"] == "org.plan" and a["targetOrgId"] == org_id for a in actions)


async def test_set_org_plan_rejects_unknown(client, admin_headers, mongo_db):
    victim = await _make_user(client, mongo_db)
    r = await client.post(f"/api/admin/orgs/{victim['org_id']}/plan?plan=galaxy", headers=admin_headers)
    assert r.status_code == 400


async def test_overview_reports_plan_mix(client, admin_headers, mongo_db):
    victim = await _make_user(client, mongo_db)
    await client.post(f"/api/admin/orgs/{victim['org_id']}/plan?plan=enterprise", headers=admin_headers)
    body = (await client.get("/api/admin/overview", headers=admin_headers)).json()
    assert "plans" in body
    assert body["plans"].get("enterprise", 0) >= 1


async def test_set_plan_unlocks_gated_feature(client, admin_headers, mongo_db):
    """Enterprise plan should lift the Free-plan 402 gate on creating a second team."""
    victim = await _make_user(client, mongo_db)
    org_id = victim["org_id"]
    blocked = await client.post(
        f"/api/orgs/{org_id}/teams", json={"name": "Second"}, headers=victim["headers"]
    )
    assert blocked.status_code == 402

    await client.post(f"/api/admin/orgs/{org_id}/plan?plan=enterprise", headers=admin_headers)
    allowed = await client.post(
        f"/api/orgs/{org_id}/teams", json={"name": "Second"}, headers=victim["headers"]
    )
    assert allowed.status_code == 201, allowed.text


async def test_self_hosted_lifts_plan_gates(client, mongo_db, monkeypatch):
    """SELF_HOSTED=true treats every org as Enterprise: no 402, and the org payload says so."""
    from app.core.config import settings

    victim = await _make_user(client, mongo_db)
    org_id = victim["org_id"]
    monkeypatch.setattr(settings, "self_hosted", True)
    allowed = await client.post(
        f"/api/orgs/{org_id}/teams", json={"name": "Second"}, headers=victim["headers"]
    )
    assert allowed.status_code == 201, allowed.text
    orgs = (await client.get("/api/orgs", headers=victim["headers"])).json()
    assert all(o["plan"] == "enterprise" for o in orgs)


# --- Org detail ---


async def test_get_org_detail(client, admin_headers, mongo_db):
    victim = await _make_user(client, mongo_db)
    org_id = victim["org_id"]
    # a key under the org so the detail surfaces it
    key_resp = await client.post(
        f"/api/orgs/{org_id}/keys", json={"name": "ci", "scopes": ["memory:read"]},
        headers=victim["headers"],
    )
    assert key_resp.status_code == 201

    r = await client.get(f"/api/admin/orgs/{org_id}", headers=admin_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["id"] == org_id
    assert any(m["email"] == victim["email"] and m["role"] == "owner" for m in body["members"])
    assert len(body["teams"]) >= 1
    assert any(k["name"] == "ci" for k in body["keys"])
    assert "activity30d" in body


async def test_get_org_detail_404(client, admin_headers):
    r = await client.get("/api/admin/orgs/nonexistent", headers=admin_headers)
    assert r.status_code == 404


# --- API key revoke ---


async def test_admin_revoke_key(client, admin_headers, mongo_db):
    victim = await _make_user(client, mongo_db)
    key_resp = await client.post(
        f"/api/orgs/{victim['org_id']}/keys", json={"name": "bad", "scopes": ["memory:read"]},
        headers=victim["headers"],
    )
    key = key_resp.json()["key"]
    key_id = key_resp.json()["id"]
    kh = {"Authorization": f"Bearer {key}"}

    # key works before revocation
    assert (await client.get("/api/v1/whoami", headers=kh)).status_code == 200

    r = await client.post(f"/api/admin/keys/{key_id}/revoke", headers=admin_headers)
    assert r.status_code == 200, r.text

    # key is dead after revocation, and the action is logged
    assert (await client.get("/api/v1/whoami", headers=kh)).status_code == 401
    actions = (await client.get("/api/admin/actions", headers=admin_headers)).json()["actions"]
    assert any(a["action"] == "apikey.revoke" for a in actions)


async def test_admin_revoke_key_404(client, admin_headers):
    r = await client.post("/api/admin/keys/nope/revoke", headers=admin_headers)
    assert r.status_code == 404


# --- Email verification override ---


async def test_admin_verify_user(client, admin_headers, mongo_db, email_on):
    victim = await _make_user(client, mongo_db, verified=False)
    # gated out of data access while unverified
    assert (await client.get("/api/orgs", headers=victim["headers"])).status_code == 403

    r = await client.post(f"/api/admin/users/{victim['id']}/verify", headers=admin_headers)
    assert r.status_code == 200, r.text

    # now allowed, and the override is logged
    assert (await client.get("/api/orgs", headers=victim["headers"])).status_code == 200
    actions = (await client.get("/api/admin/actions", headers=admin_headers)).json()["actions"]
    assert any(a["action"] == "user.verify" and a["targetEmail"] == victim["email"] for a in actions)


async def test_platform_admin_bypasses_free_plan_gates(client, admin_headers, mongo_db):
    """A platform admin (ADMIN_EMAILS) is never paywalled, even on a Free-plan org."""
    admin = await mongo_db.users.find_one({"email": ADMIN_EMAIL})
    membership = await mongo_db.memberships.find_one({"userId": str(admin["_id"]), "teamId": None})
    org_id = membership["orgId"]
    org = await mongo_db.organizations.find_one({"_id": org_id})
    assert org.get("plan", "free") != "enterprise"

    second_team = await client.post(
        f"/api/orgs/{org_id}/teams", json={"name": "Second"}, headers=admin_headers
    )
    assert second_team.status_code == 201, second_team.text

    second_org = await client.post("/api/orgs", json={"name": "Another org"}, headers=admin_headers)
    assert second_org.status_code == 201, second_org.text
