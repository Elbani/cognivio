from __future__ import annotations

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


async def _make_key(client, auth_headers, org_id, scopes):
    resp = await client.post(
        f"/api/orgs/{org_id}/keys", json={"name": "agent", "scopes": scopes}, headers=auth_headers
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["key"]


async def test_text_search_tokenizes(client, auth_headers, workspace) -> None:
    """$text search matches a content word, not just an exact substring of the query."""
    await client.post(
        f"/api/teams/{workspace['team_id']}/memories",
        json={"title": "Deploy Guide", "type": "playbook", "content": "rollback the previous image tag"},
        headers=auth_headers,
    )
    key = await _make_key(client, auth_headers, workspace["org_id"], ["memory:read"])
    H = {"Authorization": f"Bearer {key}"}

    # multi-word query that never appears as a literal substring still finds the doc
    found = await client.get(
        f"/api/v1/teams/{workspace['team_id']}/memories?q=image%20rollback", headers=H
    )
    assert found.status_code == 200
    assert "Deploy Guide" in [m["title"] for m in found.json()["memories"]]


async def test_insights_coverage_gaps_activity(client, auth_headers, workspace) -> None:
    org_id = workspace["org_id"]
    # a map + a doc → coverage should see them
    await client.post(
        f"/api/teams/{workspace['team_id']}/memories",
        json={"title": "Project Map", "type": "map", "content": "entry point"},
        headers=auth_headers,
    )
    await client.post(
        f"/api/teams/{workspace['team_id']}/memories",
        json={"title": "Auth", "type": "architecture", "content": "jwt sessions"},
        headers=auth_headers,
    )

    key = await _make_key(client, auth_headers, org_id, ["memory:read"])
    H = {"Authorization": f"Bearer {key}"}
    # two near-duplicate misses (should cluster into one gap) + one hit
    await client.get(f"/api/v1/teams/{workspace['team_id']}/memories?q=billing%20webhooks", headers=H)
    await client.get(f"/api/v1/teams/{workspace['team_id']}/memories?q=webhooks%20billing%20retry", headers=H)
    await client.get(f"/api/v1/teams/{workspace['team_id']}/memories?q=auth", headers=H)

    resp = await client.get(f"/api/orgs/{org_id}/insights", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()

    cov = data["coverage"]
    assert cov["docs"] >= 2
    assert cov["teamsWithMap"] == 1
    assert cov["byType"].get("map") == 1

    # the two webhook/billing misses collapse into a single clustered gap
    gap_qs = [g["query"] for g in data["gaps"]]
    assert any("webhook" in q or "billing" in q for q in gap_qs)
    clustered = next(g for g in data["gaps"] if "webhook" in g["query"] or "billing" in g["query"])
    assert clustered["missCount"] >= 2

    act = data["activity"]
    assert act["byAction"].get("memory.search", 0) >= 3
    assert act["activeKeys"] >= 1


async def test_insights_requires_membership(client, auth_headers, workspace) -> None:
    # an unrelated user can't read this org's insights
    reg = await client.post(
        "/api/auth/register",
        json={"email": "outsider@example.com", "password": "password123", "name": "Outsider"},
    )
    other_h = {"Authorization": f"Bearer {reg.json()['accessToken']}"}
    resp = await client.get(f"/api/orgs/{workspace['org_id']}/insights", headers=other_h)
    assert resp.status_code == 403


async def test_insights_doc_usage(client, auth_headers, workspace) -> None:
    """memory.read events drive the most-read list; unread active docs are 'never read'."""
    org_id, team = workspace["org_id"], workspace["team_id"]
    read_doc = await client.post(
        f"/api/teams/{team}/memories",
        json={"title": "Read Me", "type": "note", "content": "x"}, headers=auth_headers,
    )
    rid = read_doc.json()["id"]
    await client.post(
        f"/api/teams/{team}/memories",
        json={"title": "Ignored Doc", "type": "note", "content": "y"}, headers=auth_headers,
    )

    key = await _make_key(client, auth_headers, org_id, ["memory:read"])
    H = {"Authorization": f"Bearer {key}"}
    # pull one doc in full twice (logs memory.read)
    await client.get(f"/api/v1/memories/{rid}", headers=H)
    await client.get(f"/api/v1/memories/{rid}", headers=H)

    data = (await client.get(f"/api/orgs/{org_id}/insights", headers=auth_headers)).json()
    docs = data["docs"]
    top = {d["id"]: d for d in docs["topRead"]}
    assert rid in top and top[rid]["reads"] >= 2
    never_titles = [d["title"] for d in docs["neverRead"]]
    assert "Ignored Doc" in never_titles
    assert "Read Me" not in never_titles
