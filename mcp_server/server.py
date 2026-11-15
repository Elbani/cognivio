"""MCP server exposing the agent knowledge base to coding agents.

It is a thin client over the platform's `/api/v1` REST API, authenticated with
an API key. Configure via environment:

    KB_BASE_URL   e.g. http://localhost:8000   (no trailing /api/v1)
    KB_API_KEY    an ak_... key minted in the platform UI

Run (stdio transport, the default for Claude Code):

    KB_BASE_URL=http://localhost:8000 KB_API_KEY=ak_... python -m mcp_server.server
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone

import httpx
from mcp.server.fastmcp import FastMCP

BASE_URL = os.environ.get("KB_BASE_URL", "http://localhost:8000").rstrip("/")
API_KEY = os.environ.get("KB_API_KEY", "")

mcp = FastMCP("cognivio")

_client = httpx.AsyncClient(
    base_url=f"{BASE_URL}/api/v1",
    headers={"Authorization": f"Bearer {API_KEY}"},
    timeout=30.0,
)


async def _get(path: str, **params: object) -> object:
    resp = await _client.get(path, params={k: v for k, v in params.items() if v is not None})
    resp.raise_for_status()
    return resp.json()


async def _post(path: str, body: dict) -> object:
    resp = await _client.post(path, json=body)
    resp.raise_for_status()
    return resp.json()


async def _delete(path: str) -> object:
    resp = await _client.delete(path)
    resp.raise_for_status()
    return {"ok": True}


@mcp.tool()
async def prime_context(query: str, limit: int = 6) -> object:
    """START HERE. One call that returns everything you need to begin a task:
    the knowledge-base index map(s) for orientation PLUS the most relevant full
    docs (with their file/class pointers and [[links]]) for your query. Prefer
    this over list_teams/read_map/search_memory/get_memory chains, it gathers
    the same context in a single round-trip. Pass a short description of the task,
    e.g. 'add a new federated endpoint' or 'how aggregation gates on calculation'."""
    return await _get("/context", q=query, limit=limit)


@mcp.tool()
async def knowledge_gaps(days: int = 30, limit: int = 20) -> object:
    """List queries agents searched for but the KB had nothing for, a backlog of
    docs worth writing. Useful for maintaining the knowledge base."""
    return await _get("/insights/gaps", days=days, limit=limit)


@mcp.tool()
async def setup_rule(tool: str = "cursor") -> object:
    """Return the always-on rule file to install so this agent uses Cognivio on EVERY
    task (prime_context before, write_memory after), not just the first. `tool` is your
    editor: 'claude', 'cursor', or 'codex'. Write the returned `path` with the returned
    `content` VERBATIM (create parent dirs); for CLAUDE.md / AGENTS.md (`append: true`)
    add it as a new section rather than overwriting. This replaces manual copy-paste and
    gets the per-editor format right. Cursor needs `alwaysApply: true` frontmatter to
    load every turn, which is the usual reason the rule silently stops working."""
    return await _get("/agent-rule", tool=tool)


@mcp.tool()
async def seed_plan(team_id: str) -> object:
    """Call this FIRST when asked to initialize or seed a team's knowledge base. Returns a
    concrete plan, existing docs (don't duplicate), undocumented repo areas, whether writes
    are held for review, and the exact ordered steps. Then scan the repo and write the docs
    via write_memory in the order it gives."""
    return await _get(f"/teams/{team_id}/seed-plan")


@mcp.tool()
async def plan_project_docs(team_id: str) -> object:
    """Call this FIRST when asked to write or update the project's DEVELOPER DOCUMENTATION, a
    human-facing handbook (Overview, Architecture, Setup, …) kept SEPARATE from the agent
    knowledge base and never used in retrieval. Returns the recommended section outline, the
    sections that already exist, and (if a repo is connected) the least-documented areas. Then
    scan the repo and publish with write_project_docs."""
    return await _get(f"/teams/{team_id}/project-docs/plan")


@mcp.tool()
async def write_project_docs(team_id: str, summary: str, sections: list[dict]) -> object:
    """Publish the project's developer documentation as a new VERSION snapshot (requires a
    memory:write key). `sections` is a list of {slug, title, order, content}, content in
    Markdown; send the COMPLETE handbook each time, re-publishing archives the prior version
    and keeps history. This documentation is for humans and is never used in agent retrieval."""
    return await _post(f"/teams/{team_id}/project-docs", {"summary": summary, "sections": sections})


@mcp.tool()
async def delete_memory(memory_id: str) -> object:
    """Trash a memory by id, use to remove a DUPLICATE or OBSOLETE doc (requires a
    memory:write key). Soft delete: it's removed from results but restorable in the
    UI. To replace a doc's content instead of removing it, use write_memory (same
    title updates in place). Get ids from search_memory, prime_context, or check_drift."""
    return await _delete(f"/memories/{memory_id}")


@mcp.tool()
async def whoami() -> object:
    """Identify which organization this API key belongs to and what it can do."""
    return await _get("/whoami")


@mcp.tool()
async def list_teams() -> object:
    """List the teams whose memory this key can read."""
    return await _get("/teams")


@mcp.tool()
async def read_map(team_id: str) -> object:
    """Read a team's map FIRST to orient yourself before searching. Returns the
    team's map memory plus the full graph of memories (nodes) and links (edges).
    Use this to skip blind exploration."""
    return await _get(f"/teams/{team_id}/map")


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
    return await _get(
        f"/teams/{team_id}/memories", q=query or None, type=type, tag=tag, limit=limit
    )


@mcp.tool()
async def get_memory(memory_id: str) -> object:
    """Fetch one memory in full, including its Markdown content and links."""
    return await _get(f"/memories/{memory_id}")


@mcp.tool()
async def get_related(memory_id: str) -> object:
    """Get memories linked to or from this one (its neighbors in the graph)."""
    return await _get(f"/memories/{memory_id}/related")


@mcp.tool()
async def mark_helpful(
    memory_id: str, helpful: bool = True, note: str | None = None,
) -> object:
    """Tell the KB whether a doc you read actually helped with the task. Helpful docs
    rank higher in future prime_context results; ones marked unhelpful sink and surface
    in the low-signal report. Call this after acting on a doc to keep retrieval sharp."""
    return await _post(
        f"/memories/{memory_id}/feedback",
        {"helpful": helpful, "note": note},
    )


@mcp.tool()
async def write_memory(
    team_id: str,
    title: str,
    content: str,
    type: str = "lesson",
    tags: list[str] | None = None,
) -> object:
    """Write a memory to the team (requires a memory:write key). Use this to
    capture a lesson/incident/decision or to keep a doc current. Safe to re-run:
    writing an existing title UPDATES that doc instead of creating a duplicate
    (upsert by title). Reference other memories in the content with [[Their Title]]."""
    return await _post(
        f"/teams/{team_id}/memories",
        {"title": title, "content": content, "type": type, "tags": tags or []},
    )


_PATH_RE = re.compile(r"[A-Za-z0-9_.\-/]+\.[A-Za-z0-9]{1,6}")


def _parse_iso(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _referenced_files(content: str, root: str) -> list[str]:
    """File paths mentioned in a doc that actually exist in the repo."""
    found: list[str] = []
    seen: set[str] = set()
    for token in _PATH_RE.findall(content or ""):
        if "://" in token or "/" not in token or token in seen:
            continue
        seen.add(token)
        if os.path.isfile(os.path.join(root, token)):
            found.append(token)
    return found


@mcp.tool()
async def check_drift(team_id: str | None = None, repo_path: str = ".") -> object:
    """Find docs that may be OUT OF DATE: a doc has 'drifted' if a code file it
    references was modified AFTER the doc was last verified. Runs locally, call it
    from the repo root (the connector reads your working files). This catches the
    case where code changed but the doc didn't (which time-based staleness misses).
    For each drifted doc: re-read the changed file, fix the doc, and write_memory it
    (that re-verifies). Note: a fresh git clone resets file timestamps, which can
    cause false positives until you re-verify."""
    root = os.path.abspath(repo_path)
    teams = await _get("/teams")
    team_ids = [team_id] if team_id else [t["id"] for t in (teams or [])]

    drifted: list[dict] = []
    checked = 0
    for tid in team_ids:
        listing = await _get(f"/teams/{tid}/memories", limit=100)
        items = listing.get("memories", []) if isinstance(listing, dict) else (listing or [])
        for item in items:
            doc = await _get(f"/memories/{item['id']}")
            checked += 1
            verified = _parse_iso(doc.get("lastVerifiedAt"))
            if verified is None:
                continue
            changed = []
            for rel in _referenced_files(doc.get("content", ""), root):
                try:
                    mtime = datetime.fromtimestamp(
                        os.path.getmtime(os.path.join(root, rel)), tz=timezone.utc
                    )
                except OSError:
                    continue
                if mtime > verified:
                    changed.append({"file": rel, "changedAt": mtime.isoformat()})
            if changed:
                drifted.append({
                    "id": doc["id"],
                    "title": doc["title"],
                    "teamId": tid,
                    "lastVerifiedAt": doc.get("lastVerifiedAt"),
                    "changedFiles": changed,
                })

    return {
        "repoPath": root,
        "checked": checked,
        "driftedCount": len(drifted),
        "drifted": drifted,
        "note": (
            "Each drifted doc references a file modified after the doc was last verified. "
            "Re-read the changed file, update the doc, and write_memory it (re-verifies). "
            "If a doc is fine as-is, open it and click Verify to clear the flag."
        ),
    }


def main() -> None:
    """Console entrypoint (stdio transport), exposed as `cognivio-mcp`."""
    mcp.run()


if __name__ == "__main__":
    main()
