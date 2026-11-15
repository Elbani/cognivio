from __future__ import annotations

import pytest
import pytest_asyncio

from app.mcp_remote import mcp_lifespan

pytestmark = pytest.mark.asyncio

MCP_H = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
INIT = {
    "jsonrpc": "2.0", "id": 1, "method": "initialize",
    "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}},
}


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def mcp_running():
    """Start the Streamable-HTTP session manager once for the whole session. Its run()
    can only be entered once per process (the app lifespan does this in production), and
    its task group must be entered/exited in the same task, so own it in a dedicated
    task rather than across the fixture's setup/teardown tasks."""
    import asyncio

    started, stop = asyncio.Event(), asyncio.Event()

    async def _runner():
        async with mcp_lifespan():
            started.set()
            await stop.wait()

    task = asyncio.create_task(_runner())
    await started.wait()
    yield
    stop.set()
    await task


async def _make_key(client, auth_headers, org_id, scopes):
    r = await client.post(
        f"/api/orgs/{org_id}/keys", json={"name": "remote", "scopes": scopes}, headers=auth_headers
    )
    assert r.status_code == 201, r.text
    return r.json()["key"]


async def test_mcp_requires_bearer(client, workspace) -> None:
    # no header
    r = await client.post("/mcp", headers=MCP_H, json=INIT)
    assert r.status_code == 401
    # bogus key
    r2 = await client.post("/mcp", headers={**MCP_H, "Authorization": "Bearer ak_bogus"}, json=INIT)
    assert r2.status_code == 401


async def test_mcp_initialize_list_and_call(client, auth_headers, workspace, mcp_running) -> None:
    key = await _make_key(
        client, auth_headers, workspace["org_id"], ["memory:read", "map:read", "memory:write"]
    )
    H = {**MCP_H, "Authorization": f"Bearer {key}"}
    init = await client.post("/mcp", headers=H, json=INIT)
    assert init.status_code == 200, init.text
    assert init.json()["result"]["serverInfo"]["name"] == "cognivio"

    listing = await client.post("/mcp", headers=H, json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    names = [t["name"] for t in listing.json()["result"]["tools"]]
    assert {"prime_context", "write_memory", "search_memory", "whoami"} <= set(names)
    # check_drift is now available remotely too, backed by the server-side repo
    # connection (coverage_report), so zero-setup users get drift without a local FS.
    assert "check_drift" in names

    call = await client.post("/mcp", headers=H, json={
        "jsonrpc": "2.0", "id": 3, "method": "tools/call",
        "params": {"name": "write_memory", "arguments": {
            "team_id": workspace["team_id"], "title": "Remote MCP Doc", "content": "via /mcp", "type": "note"}},
    })
    result = call.json()["result"]
    assert result.get("isError") in (False, None), result


async def test_mcp_call_enforces_scope(client, auth_headers, workspace, mcp_running) -> None:
    ro = await _make_key(client, auth_headers, workspace["org_id"], ["memory:read"])
    H = {**MCP_H, "Authorization": f"Bearer {ro}"}
    call = await client.post("/mcp", headers=H, json={
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "write_memory", "arguments": {
            "team_id": workspace["team_id"], "title": "nope", "content": "x"}},
    })
    result = call.json()["result"]
    assert result.get("isError") is True
    assert "scope" in result["content"][0]["text"].lower()
