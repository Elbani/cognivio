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


# --- Feature 4: agent write-back review queue ---


async def test_team_review_toggle_roundtrips(client: AsyncClient, auth_headers, workspace) -> None:
    team_id = workspace["team_id"]
    # default off
    teams = (await client.get(f"/api/orgs/{workspace['org_id']}/teams", headers=auth_headers)).json()
    assert teams[0]["agentWriteReview"] is False

    resp = await client.patch(
        f"/api/teams/{team_id}", json={"agentWriteReview": True}, headers=auth_headers
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["agentWriteReview"] is True


async def test_agent_write_held_as_draft_and_hidden_then_approved(
    client: AsyncClient, auth_headers, workspace
) -> None:
    org_id, team_id = workspace["org_id"], workspace["team_id"]
    await client.patch(f"/api/teams/{team_id}", json={"agentWriteReview": True}, headers=auth_headers)

    key = await _make_key(client, auth_headers, org_id, ["memory:read", "memory:write", "map:read"])
    H = {"Authorization": f"Bearer {key}"}

    # Agent write lands as a draft (not active) when review is required.
    created = await client.post(
        f"/api/v1/teams/{team_id}/memories",
        json={"title": "Payments Service", "type": "architecture", "content": "how payments work"},
        headers=H,
    )
    assert created.status_code == 201, created.text
    mem_id = created.json()["id"]
    assert created.json()["status"] == "draft"

    # Draft is hidden from every agent read path.
    ctx = await client.get("/api/v1/context", params={"q": "payments service"}, headers=H)
    assert mem_id not in [r["id"] for r in ctx.json()["results"]]

    search = await client.get(
        f"/api/v1/teams/{team_id}/memories", params={"q": "payments"}, headers=H
    )
    assert mem_id not in [m["id"] for m in search.json()["memories"]]

    mp = await client.get(f"/api/v1/teams/{team_id}/map", headers=H)
    assert mem_id not in [n["id"] for n in mp.json()["nodes"]]

    # A human approves it; now it surfaces to agents.
    approved = await client.post(f"/api/memories/{mem_id}/approve", headers=auth_headers)
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "active"

    ctx2 = await client.get("/api/v1/context", params={"q": "payments service"}, headers=H)
    assert mem_id in [r["id"] for r in ctx2.json()["results"]]


async def test_review_off_writes_go_live(client: AsyncClient, auth_headers, workspace) -> None:
    org_id, team_id = workspace["org_id"], workspace["team_id"]
    key = await _make_key(client, auth_headers, org_id, ["memory:read", "memory:write"])
    H = {"Authorization": f"Bearer {key}"}
    created = await client.post(
        f"/api/v1/teams/{team_id}/memories",
        json={"title": "Live Doc", "type": "note", "content": "x"},
        headers=H,
    )
    assert created.json()["status"] == "active"


async def test_review_queue_filter_by_source_and_status(
    client: AsyncClient, auth_headers, workspace
) -> None:
    org_id, team_id = workspace["org_id"], workspace["team_id"]
    await client.patch(f"/api/teams/{team_id}", json={"agentWriteReview": True}, headers=auth_headers)
    key = await _make_key(client, auth_headers, org_id, ["memory:write"])
    H = {"Authorization": f"Bearer {key}"}
    await client.post(
        f"/api/v1/teams/{team_id}/memories",
        json={"title": "Pending One", "type": "note", "content": "y"},
        headers=H,
    )
    # The human review queue = agent-authored drafts.
    resp = await client.get(
        f"/api/teams/{team_id}/memories",
        params={"status": "draft", "source": "agent"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    titles = [m["title"] for m in resp.json()["memories"]]
    assert "Pending One" in titles


# --- Feature 6: usefulness feedback loop ---


async def test_feedback_increments_counts(client: AsyncClient, auth_headers, workspace) -> None:
    org_id, team_id = workspace["org_id"], workspace["team_id"]
    created = await client.post(
        f"/api/teams/{team_id}/memories",
        json={"title": "Rollback Guide", "type": "playbook", "content": "steps"},
        headers=auth_headers,
    )
    mem_id = created.json()["id"]
    assert created.json()["helpfulCount"] == 0

    key = await _make_key(client, auth_headers, org_id, ["memory:read"])
    H = {"Authorization": f"Bearer {key}"}

    up = await client.post(f"/api/v1/memories/{mem_id}/feedback", json={"helpful": True}, headers=H)
    assert up.status_code == 200, up.text
    assert up.json() == {"id": mem_id, "helpfulCount": 1, "notHelpfulCount": 0}

    down = await client.post(
        f"/api/v1/memories/{mem_id}/feedback", json={"helpful": False, "note": "stale"}, headers=H
    )
    assert down.json()["notHelpfulCount"] == 1

    got = await client.get(f"/api/v1/memories/{mem_id}", headers=H)
    assert got.json()["helpfulCount"] == 1
    assert got.json()["notHelpfulCount"] == 1


async def test_feedback_requires_read_scope(client: AsyncClient, auth_headers, workspace) -> None:
    org_id, team_id = workspace["org_id"], workspace["team_id"]
    created = await client.post(
        f"/api/teams/{team_id}/memories",
        json={"title": "Scope Doc", "type": "note"},
        headers=auth_headers,
    )
    mem_id = created.json()["id"]
    # map:read only, no memory:read
    key = await _make_key(client, auth_headers, org_id, ["map:read"])
    H = {"Authorization": f"Bearer {key}"}
    resp = await client.post(f"/api/v1/memories/{mem_id}/feedback", json={"helpful": True}, headers=H)
    assert resp.status_code == 403


async def test_helpfulness_boosts_ranking(client: AsyncClient, auth_headers, workspace) -> None:
    """Two equally-relevant docs: the one agents marked helpful should rank first."""
    org_id, team_id = workspace["org_id"], workspace["team_id"]
    a = await client.post(
        f"/api/teams/{team_id}/memories",
        json={"title": "Caching Strategy A", "type": "note", "content": "caching"},
        headers=auth_headers,
    )
    b = await client.post(
        f"/api/teams/{team_id}/memories",
        json={"title": "Caching Strategy B", "type": "note", "content": "caching"},
        headers=auth_headers,
    )
    a_id, b_id = a.json()["id"], b.json()["id"]

    key = await _make_key(client, auth_headers, org_id, ["memory:read"])
    H = {"Authorization": f"Bearer {key}"}
    # B gets repeated positive feedback.
    for _ in range(3):
        await client.post(f"/api/v1/memories/{b_id}/feedback", json={"helpful": True}, headers=H)

    ctx = await client.get("/api/v1/context", params={"q": "caching strategy"}, headers=H)
    ids = [r["id"] for r in ctx.json()["results"]]
    assert a_id in ids and b_id in ids
    assert ids.index(b_id) < ids.index(a_id)


# --- Feature 5: retrieval + usefulness in insights ---


async def test_insights_reports_retrieval_and_usefulness(
    client: AsyncClient, auth_headers, workspace
) -> None:
    org_id, team_id = workspace["org_id"], workspace["team_id"]
    created = await client.post(
        f"/api/teams/{team_id}/memories",
        json={"title": "Deployment Runbook", "type": "playbook", "content": "deploy steps"},
        headers=auth_headers,
    )
    mem_id = created.json()["id"]

    key = await _make_key(client, auth_headers, org_id, ["memory:read"])
    H = {"Authorization": f"Bearer {key}"}
    # one hit, one miss → drives hitRate
    await client.get("/api/v1/context", params={"q": "deployment runbook"}, headers=H)
    await client.get("/api/v1/context", params={"q": "zzz nonexistent topic"}, headers=H)
    # mark the doc unhelpful so it's low-signal
    await client.post(f"/api/v1/memories/{mem_id}/feedback", json={"helpful": False}, headers=H)

    ins = (await client.get(f"/api/orgs/{org_id}/insights", headers=auth_headers)).json()

    assert ins["retrieval"]["lookups"] >= 2
    assert ins["retrieval"]["hits"] >= 1
    assert ins["retrieval"]["hitRate"] is not None and 0 <= ins["retrieval"]["hitRate"] <= 1

    assert ins["usefulness"]["notHelpful"] >= 1
    assert ins["usefulness"]["ratedDocs"] >= 1
    assert mem_id in [d["id"] for d in ins["usefulness"]["lowSignal"]]


# --- Seeding: seed-plan ---


async def test_seed_plan_uninitialized(client: AsyncClient, auth_headers, workspace) -> None:
    org_id, team_id = workspace["org_id"], workspace["team_id"]
    key = await _make_key(client, auth_headers, org_id, ["memory:read"])
    H = {"Authorization": f"Bearer {key}"}

    r = await client.get(f"/api/v1/teams/{team_id}/seed-plan", headers=H)
    assert r.status_code == 200, r.text
    plan = r.json()
    assert plan["initialized"] is False
    assert plan["docCount"] == 0
    assert plan["repoConnected"] is False
    assert plan["reviewEnabled"] is False
    assert plan["recommendedOrder"] == ["decision", "architecture", "map"]
    assert "scan" in plan["instructions"].lower()


async def test_seed_plan_sees_existing_docs_and_review(
    client: AsyncClient, auth_headers, workspace
) -> None:
    org_id, team_id = workspace["org_id"], workspace["team_id"]
    await client.post(
        f"/api/teams/{team_id}/memories",
        json={"title": "System Map", "type": "map", "content": "x"},
        headers=auth_headers,
    )
    await client.post(
        f"/api/teams/{team_id}/memories",
        json={"title": "Auth Decision", "type": "decision", "content": "y"},
        headers=auth_headers,
    )
    await client.patch(f"/api/teams/{team_id}", json={"agentWriteReview": True}, headers=auth_headers)

    key = await _make_key(client, auth_headers, org_id, ["memory:read"])
    H = {"Authorization": f"Bearer {key}"}
    plan = (await client.get(f"/api/v1/teams/{team_id}/seed-plan", headers=H)).json()

    assert plan["initialized"] is True  # a map exists
    assert plan["docCount"] == 2
    titles = [d["title"] for d in plan["existingDocs"]]
    assert "System Map" in titles and "Auth Decision" in titles
    assert plan["reviewEnabled"] is True
    assert "draft" in plan["instructions"].lower()


async def test_seed_plan_requires_read_scope(client: AsyncClient, auth_headers, workspace) -> None:
    org_id, team_id = workspace["org_id"], workspace["team_id"]
    key = await _make_key(client, auth_headers, org_id, ["map:read"])  # no memory:read
    H = {"Authorization": f"Bearer {key}"}
    r = await client.get(f"/api/v1/teams/{team_id}/seed-plan", headers=H)
    assert r.status_code == 403
