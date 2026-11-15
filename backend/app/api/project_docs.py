"""Project documentation: a human-facing developer handbook, versioned per team.

This is deliberately SEPARATE from the agent knowledge base (`memories`). It lives in its
own `project_docs` collection and is NEVER read by any agent retrieval path (no embeddings,
not in `context_pack`). The content is written BY the connected coding agent, the platform
only plans, stores, versions, and renders it (same "no server-side LLM" stance as seed_plan):
the agent endpoints live in `app.api.agent`; this module holds the shared shapes plus the
human read API (current version, version history, and per-section diffs between versions).

Each publish is a full snapshot with an incrementing `version`; exactly one row per team is
`status="current"` (the rest are `archived`), which is how "evolving documentation" is kept
as browsable history.
"""

from __future__ import annotations

import difflib

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.api.deps import Db, TeamCtx

router = APIRouter(prefix="/api", tags=["project-docs"])


# The default chapter outline the agent is nudged to cover. Not enforced, the agent adds or
# drops sections to fit the project, but it makes "generate our docs" produce something
# consistent and complete for a developer new to the codebase.
RECOMMENDED_SECTIONS: list[dict] = [
    {"slug": "overview", "title": "Overview",
     "hint": "What the project is, who it's for, and the high-level value. A few paragraphs."},
    {"slug": "architecture", "title": "Architecture",
     "hint": "Components/services, how they fit together, the request/data flow, key directories. Cite real paths."},
    {"slug": "local-setup", "title": "Local Setup",
     "hint": "Prerequisites, env vars, how to run the app and the tests locally, and common gotchas."},
    {"slug": "data-model", "title": "Data Model",
     "hint": "The main entities/collections/tables and how they relate."},
    {"slug": "api-surface", "title": "API Surface",
     "hint": "The endpoints/interfaces a developer needs, grouped by area."},
    {"slug": "deployment", "title": "Deployment",
     "hint": "How it builds and ships to each environment; config and secrets handling."},
    {"slug": "conventions", "title": "Conventions",
     "hint": "Code style, branching/commit rules, testing expectations, and review norms."},
]


class ProjectDocSectionIn(BaseModel):
    slug: str = Field(min_length=1, max_length=80, pattern=r"^[a-z0-9][a-z0-9-]*$")
    title: str = Field(min_length=1, max_length=160)
    content: str = Field(default="", max_length=200_000)  # Markdown; bounded to keep a snapshot sane
    order: int = Field(default=0, ge=0, le=999)


class ProjectDocsPublishIn(BaseModel):
    summary: str = Field(default="", max_length=500)  # one-line "what changed" for the version log
    sections: list[ProjectDocSectionIn] = Field(min_length=1, max_length=60)


def project_doc_version_out(doc: dict, include_content: bool = True) -> dict:
    """Serialize a snapshot. `include_content=False` for version-list metadata (keeps the
    history listing light, section bodies can be large)."""
    sections = sorted(
        doc.get("sections", []), key=lambda s: (s.get("order", 0), s.get("title", ""))
    )
    out_sections = [
        {
            "slug": s.get("slug"),
            "title": s.get("title"),
            "order": s.get("order", 0),
            **({"content": s.get("content", "")} if include_content else {}),
        }
        for s in sections
    ]
    return {
        "id": doc["_id"],
        "version": doc.get("version"),
        "status": doc.get("status"),
        "summary": doc.get("summary", ""),
        "source": doc.get("source"),
        "sourceRef": doc.get("sourceRef"),
        "sectionCount": len(sections),
        "createdAt": doc.get("createdAt"),
        "sections": out_sections,
    }


@router.get("/teams/{team_id}/project-docs")
async def get_current_project_docs(ctx: TeamCtx, db: Db) -> dict:
    """The current published handbook for a team (or an empty state if none yet)."""
    doc = await db.project_docs.find_one({"teamId": ctx.team_id, "status": "current"})
    version_count = await db.project_docs.count_documents({"teamId": ctx.team_id})
    return {
        "teamId": ctx.team_id,
        "hasDocs": doc is not None,
        "current": project_doc_version_out(doc) if doc else None,
        "versionCount": version_count,
    }


@router.get("/teams/{team_id}/project-docs/versions")
async def list_project_docs_versions(ctx: TeamCtx, db: Db) -> dict:
    """Version history (newest first), without section bodies, for the snapshot picker."""
    versions = [
        project_doc_version_out(d, include_content=False)
        async for d in db.project_docs.find({"teamId": ctx.team_id}).sort("version", -1)
    ]
    return {"teamId": ctx.team_id, "versions": versions}


@router.get("/teams/{team_id}/project-docs/versions/{version}")
async def get_project_docs_version(version: int, ctx: TeamCtx, db: Db) -> dict:
    """One historical snapshot in full."""
    doc = await db.project_docs.find_one({"teamId": ctx.team_id, "version": version})
    if doc is None:
        raise HTTPException(status_code=404, detail="Version not found")
    return project_doc_version_out(doc)


def _section_map(doc: dict) -> dict[str, dict]:
    return {s["slug"]: s for s in doc.get("sections", [])}


def _diff_sections(a: dict, b: dict) -> list[dict]:
    """Per-section unified diff between two snapshots. Sections are matched by slug; a section
    present in only one side is reported as added/removed."""
    amap, bmap = _section_map(a), _section_map(b)
    slugs = list(dict.fromkeys([*amap.keys(), *bmap.keys()]))
    out: list[dict] = []
    for slug in slugs:
        sa, sb = amap.get(slug), bmap.get(slug)
        before = (sa or {}).get("content", "")
        after = (sb or {}).get("content", "")
        if sa is None:
            state = "added"
        elif sb is None:
            state = "removed"
        elif before == after:
            state = "unchanged"
        else:
            state = "changed"
        diff = (
            ""
            if state == "unchanged"
            else "".join(
                difflib.unified_diff(
                    before.splitlines(keepends=True),
                    after.splitlines(keepends=True),
                    fromfile=f"v{a.get('version')}",
                    tofile=f"v{b.get('version')}",
                    n=2,
                )
            )
        )
        out.append(
            {"slug": slug, "title": (sb or sa or {}).get("title"), "status": state, "diff": diff}
        )
    return out


@router.get("/teams/{team_id}/project-docs/diff")
async def diff_project_docs(
    ctx: TeamCtx,
    db: Db,
    from_: int = Query(..., alias="from", description="older version number"),
    to: int = Query(..., description="newer version number"),
) -> dict:
    """Section-by-section diff between two versions, how the docs (and the project) evolved."""
    a = await db.project_docs.find_one({"teamId": ctx.team_id, "version": from_})
    b = await db.project_docs.find_one({"teamId": ctx.team_id, "version": to})
    if a is None or b is None:
        raise HTTPException(status_code=404, detail="Version not found")
    return {"from": from_, "to": to, "sections": _diff_sections(a, b)}
