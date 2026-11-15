"""Remote MCP endpoint (Streamable HTTP), the zero-local-setup connector.

Coding tools connect to `https://<host>/mcp` with `Authorization: Bearer ak_…` and get
the same tools as the local stdio connector, with no `uv`/`pipx`/PATH on their machine.

It runs *inside* this FastAPI app and reuses the `/api/v1` handlers directly (no HTTP
loopback). Auth is per-request: an ASGI shim validates the Bearer key, stashes the
resolved AgentContext in a contextvar, and the tools read it. `check_drift` is exposed
here too, the remote version is backed by the server-side repo connection (a read-only
Git token), so it needs no local filesystem; the stdio connector's `check_drift` instead
diffs the user's working tree.
"""

from __future__ import annotations

import contextlib
import json
from contextvars import ContextVar

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import BaseModel
from starlette.routing import Route

from app.api.agent import (
    AgentContext,
    agent_rule_payload as _agent_rule_payload,
    context_pack as _context,
    create_memory as _create,
    delete_memory as _delete,
    get_map as _get_map,
    get_memory as _get_memory,
    knowledge_gaps as _gaps,
    list_teams as _list_teams,
    project_docs_plan as _pd_plan,
    publish_project_docs as _pd_publish,
    related_memories as _related,
    resolve_api_key,
    search_memories as _search,
    seed_plan as _seed_plan,
    submit_feedback as _feedback,
    team_drift as _drift,
    whoami as _whoami,
)
from app.api.project_docs import ProjectDocsPublishIn
from app.db.database import get_db
from app.models.enums import MemoryType
from app.models.schemas import MemoryCreate, MemoryFeedback

# Per-request auth context, set by the ASGI shim before the tool runs.
_agent_ctx: ContextVar[AgentContext | None] = ContextVar("mcp_agent_ctx", default=None)

# DNS-rebinding (Host-header) protection defaults to localhost-only, that's meant for
# local stdio dev servers and would 421 a real deployed domain. This endpoint is a public,
# Bearer-authenticated API reached at arbitrary hostnames, so we turn it off here; auth +
# TLS + CORS are the real controls.
mcp = FastMCP(
    "cognivio",
    stateless_http=True,
    json_response=True,
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)


def _ctx() -> AgentContext:
    ctx = _agent_ctx.get()
    if ctx is None:  # the ASGI shim rejects unauthenticated requests before this runs
        raise RuntimeError("Not authenticated")
    return ctx


def _dump(result: object) -> object:
    if result is None:
        return {"ok": True}
    if isinstance(result, BaseModel):
        return result.model_dump(mode="json")
    if isinstance(result, list):
        return [r.model_dump(mode="json") if isinstance(r, BaseModel) else r for r in result]
    return result


# --- Tools (same surface as the stdio connector; check_drift here is server-side) ---


@mcp.tool()
async def prime_context(query: str, limit: int = 6) -> object:
    """START HERE. One call that returns everything you need to begin a task: the
    knowledge-base index map(s) plus the most relevant docs (as excerpts, with their
    file/class pointers and [[links]]) for your query. Prefer this over
    list_teams/read_map/search_memory/get_memory chains. Pass a short task description."""
    return _dump(await _context(ctx=_ctx(), db=get_db(), q=query, limit=limit))


@mcp.tool()
async def whoami() -> object:
    """Identify which organization this API key belongs to and what it can do."""
    return _dump(await _whoami(ctx=_ctx(), db=get_db()))


@mcp.tool()
async def list_teams() -> object:
    """List the teams whose memory this key can read."""
    return _dump(await _list_teams(ctx=_ctx(), db=get_db()))


@mcp.tool()
async def read_map(team_id: str) -> object:
    """Read a team's map FIRST to orient yourself. Returns the map memory plus the full
    graph of memories (nodes) and links (edges) so you can skip blind exploration."""
    return _dump(await _get_map(team_id=team_id, ctx=_ctx(), db=get_db()))


@mcp.tool()
async def search_memory(
    team_id: str,
    query: str = "",
    type: str | None = None,
    tag: str | None = None,
    limit: int = 25,
) -> object:
    """Search a team's memories by free text, optionally filtered by type
    (map, architecture, playbook, incident, decision, lesson, note) or tag.
    Returns lightweight items without full content; call get_memory for the body."""
    mt = MemoryType(type) if type else None
    return _dump(
        await _search(
            team_id=team_id, ctx=_ctx(), db=get_db(),
            q=query or None, type=mt, tag=tag, status_=None, limit=limit,
        )
    )


@mcp.tool()
async def get_memory(memory_id: str) -> object:
    """Fetch one memory in full, including its Markdown content and links."""
    return _dump(await _get_memory(memory_id=memory_id, ctx=_ctx(), db=get_db()))


@mcp.tool()
async def get_related(memory_id: str) -> object:
    """Get memories linked to or from this one (its neighbors in the graph)."""
    return _dump(await _related(memory_id=memory_id, ctx=_ctx(), db=get_db()))


@mcp.tool()
async def mark_helpful(
    memory_id: str, helpful: bool = True, note: str | None = None,
) -> object:
    """Tell the KB whether a doc you read actually helped with the task. Helpful docs
    rank higher in future prime_context results; ones marked unhelpful sink and surface
    in the low-signal report. Call this after acting on a doc to keep retrieval sharp."""
    payload = MemoryFeedback(helpful=helpful, note=note)
    return _dump(await _feedback(memory_id=memory_id, payload=payload, ctx=_ctx(), db=get_db()))


@mcp.tool()
async def write_memory(
    team_id: str,
    title: str,
    content: str,
    type: str = "lesson",
    tags: list[str] | None = None,
) -> object:
    """Write a memory to the team (requires a memory:write key). Safe to re-run: writing
    an existing title UPDATES that doc instead of creating a duplicate (upsert by title).
    Reference other memories in the content with [[Their Title]]."""
    payload = MemoryCreate(title=title, content=content, type=MemoryType(type), tags=tags or [])
    return _dump(await _create(team_id=team_id, payload=payload, ctx=_ctx(), db=get_db()))


@mcp.tool()
async def delete_memory(memory_id: str) -> object:
    """Trash a memory by id, remove a DUPLICATE or OBSOLETE doc (requires memory:write).
    Soft delete: removed from results but restorable in the UI."""
    await _delete(memory_id=memory_id, ctx=_ctx(), db=get_db())
    return {"ok": True, "deleted": memory_id}


@mcp.tool()
async def knowledge_gaps(days: int = 30, limit: int = 20) -> object:
    """List queries agents searched for but the KB had nothing for, a backlog of docs
    worth writing. Useful for maintaining the knowledge base."""
    return _dump(await _gaps(ctx=_ctx(), db=get_db(), days=days, limit=limit))


@mcp.tool()
async def setup_rule(tool: str = "cursor") -> object:
    """Return the always-on rule file to install so this agent uses Cognivio on EVERY
    task (prime_context before, write_memory after), not just the first. `tool` is your
    editor: 'claude', 'cursor', or 'codex'. Write the returned `path` with the returned
    `content` VERBATIM (create parent dirs); for CLAUDE.md / AGENTS.md (`append: true`)
    add it as a new section rather than overwriting. This replaces manual copy-paste and
    gets the per-editor format right. Cursor needs `alwaysApply: true` frontmatter to
    load every turn, which is the usual reason the rule silently stops working."""
    try:
        return _agent_rule_payload(tool)
    except ValueError as e:
        return {"error": str(e)}


@mcp.tool()
async def check_drift(team_id: str) -> object:
    """List docs that have DRIFTED, they cite a repo file whose last commit is newer than
    the doc's last verification, so the doc may be out of date. For each, read the changed
    file(s) and call write_memory with the SAME title to refresh the doc (updates in place
    and re-verifies). Returns an empty list if no repo is connected or nothing drifted."""
    return _dump(await _drift(team_id=team_id, ctx=_ctx(), db=get_db()))


@mcp.tool()
async def plan_project_docs(team_id: str) -> object:
    """Call this FIRST when asked to write or update the project's DEVELOPER DOCUMENTATION, a
    human-facing handbook (Overview, Architecture, Setup, …) kept SEPARATE from the agent
    knowledge base and never used in retrieval. Returns the recommended section outline, the
    sections that already exist, and (if a repo is connected) the least-documented areas. Then
    scan the repo and publish with write_project_docs."""
    return _dump(await _pd_plan(team_id=team_id, ctx=_ctx(), db=get_db()))


@mcp.tool()
async def write_project_docs(team_id: str, summary: str, sections: list[dict]) -> object:
    """Publish the project's developer documentation as a new VERSION snapshot (requires a
    memory:write key). `sections` is a list of {slug, title, order, content}, content in
    Markdown; send the COMPLETE handbook each time, re-publishing archives the prior version
    and keeps history. This documentation is for humans and is never used in agent retrieval."""
    payload = ProjectDocsPublishIn(summary=summary, sections=sections)
    return _dump(await _pd_publish(team_id=team_id, payload=payload, ctx=_ctx(), db=get_db()))


@mcp.tool()
async def seed_plan(team_id: str) -> object:
    """Call this FIRST when asked to initialize or seed a team's knowledge base. Returns a
    concrete plan, existing docs (don't duplicate), undocumented repo areas, whether writes
    are held for review, and the exact ordered steps. Then scan the repo and write the docs
    via write_memory in the order it gives."""
    return _dump(await _seed_plan(team_id=team_id, ctx=_ctx(), db=get_db()))


# --- ASGI plumbing: Bearer auth + Streamable HTTP, mounted at /mcp ---

# Create the session manager (lazily built by this call); started in mcp_lifespan().
_ = mcp.streamable_http_app()

_UNAUTH = json.dumps(
    {"error": "Missing or invalid API key. Send 'Authorization: Bearer ak_…'."}
).encode()


class _McpEndpoint:
    """ASGI app: authenticate the Bearer key, stash the AgentContext, then hand off to
    the MCP Streamable-HTTP session manager."""

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await mcp.session_manager.handle_request(scope, receive, send)
            return
        headers = dict(scope.get("headers") or [])
        auth = headers.get(b"authorization", b"").decode()
        token = auth[7:].strip() if auth.startswith("Bearer ") else ""
        ctx = await resolve_api_key(get_db(), token) if token else None
        if ctx is None:
            await send({
                "type": "http.response.start",
                "status": 401,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"www-authenticate", b'Bearer realm="cognivio"'),
                ],
            })
            await send({"type": "http.response.body", "body": _UNAUTH})
            return
        reset = _agent_ctx.set(ctx)
        try:
            await mcp.session_manager.handle_request(scope, receive, send)
        finally:
            _agent_ctx.reset(reset)


def mcp_route() -> Route:
    """Exact-path route at /mcp (no trailing-slash redirect). Add before the SPA catch-all."""
    return Route("/mcp", _McpEndpoint(), methods=["GET", "POST", "DELETE"])


@contextlib.asynccontextmanager
async def mcp_lifespan():
    """Runs the Streamable-HTTP session manager; compose into the app lifespan."""
    async with mcp.session_manager.run():
        yield
