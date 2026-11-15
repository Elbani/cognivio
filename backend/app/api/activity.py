from __future__ import annotations

from fastapi import APIRouter, Query
from pymongo import ASCENDING, DESCENDING

from app.api.deps import Db, OrgCtx, TeamCtx
from app.models.schemas import AuditEntryOut, AuditResponse

router = APIRouter(prefix="/api", tags=["activity"])


async def _to_entries(db, docs: list[dict]) -> list[AuditEntryOut]:
    """Resolve each entry's referenced doc (incl. trashed ones) so every row shows
    what it touched and stays clickable, even if the doc isn't in the active list."""
    mem_ids = {doc["memoryId"] for doc in docs if doc.get("memoryId")}
    mems: dict[str, dict] = {}
    if mem_ids:
        async for m in db.memories.find(
            {"_id": {"$in": list(mem_ids)}}, {"title": 1, "deletedAt": 1}
        ):
            mems[str(m["_id"])] = m

    entries = []
    for doc in docs:
        mid = doc.get("memoryId")
        m = mems.get(mid) if mid else None
        entries.append(
            AuditEntryOut(
                id=str(doc["_id"]),
                action=doc.get("action", ""),
                actor=doc.get("actor", "agent"),
                keyName=doc.get("keyName"),
                teamId=doc.get("teamId"),
                memoryId=mid,
                memoryTitle=(m["title"] if m else None),
                memoryDeleted=bool(m.get("deletedAt")) if m else False,
                query=doc.get("query"),
                at=doc["at"],
            )
        )
    return entries


@router.get("/teams/{team_id}/activity", response_model=AuditResponse)
async def team_activity(
    ctx: TeamCtx, db: Db, limit: int = Query(default=100, ge=1, le=500)
) -> AuditResponse:
    """Agent activity for a single team (the team's docs + org-wide entries)."""
    docs = [
        doc
        async for doc in db.audit_log.find(
            {"orgId": ctx.org_id, "$or": [{"teamId": ctx.team_id}, {"teamId": None}]}
        )
        .sort("at", -1)
        .limit(limit)
    ]
    return AuditResponse(entries=await _to_entries(db, docs))


@router.get("/orgs/{org_id}/activity", response_model=AuditResponse)
async def org_activity(
    ctx: OrgCtx,
    db: Db,
    keyName: str | None = None,
    action: str | None = None,
    team: str | None = Query(default=None, description="a team id, '__org__' for org-wide, or omit for all"),
    order: str = Query(default="desc", pattern="^(asc|desc)$"),
    limit: int = Query(default=25, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> AuditResponse:
    """Agent activity across the WHOLE org, every team in one feed, filterable,
    sortable and paginated. An agent's session spans teams, so this is the right
    view for the org-level Agents page. Full history is retained."""
    query: dict = {"orgId": ctx.org_id}
    if keyName:
        query["keyName"] = keyName
    if action:
        query["action"] = action
    if team == "__org__":
        query["teamId"] = None
    elif team:
        query["teamId"] = team

    total = await db.audit_log.count_documents(query)
    direction = ASCENDING if order == "asc" else DESCENDING
    docs = [
        doc
        async for doc in db.audit_log.find(query).sort("at", direction).skip(offset).limit(limit)
    ]
    # distinct key names across the org (unfiltered) so the UI can populate its filter
    key_names = sorted(n for n in await db.audit_log.distinct("keyName", {"orgId": ctx.org_id}) if n)
    return AuditResponse(entries=await _to_entries(db, docs), total=total, keyNames=key_names)
