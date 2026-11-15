from __future__ import annotations

import re
from datetime import datetime, timezone

from bson import ObjectId
from fastapi import APIRouter, HTTPException, Query, status
from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import ReturnDocument

from app.api.deps import CurrentVerifiedUser, Db, TeamCtx, effective_role, ensure_role
from app.models.enums import MemorySource, MemoryStatus, MemoryType, Role
from app.models.schemas import (
    MemoryCreate,
    MemoryListItem,
    MemoryListResponse,
    MemoryOut,
    MemoryUpdate,
    document_id,
)
from app.core.embeddings import embed_and_store
from app.utils import extract_wiki_links, normalize_tag, normalize_title

router = APIRouter(prefix="/api", tags=["memories"])

LIST_PROJECTION = {"content": 0}


def clean_tags(tags: list[str]) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for tag in tags:
        value = normalize_tag(tag)
        if value and value not in seen:
            seen.add(value)
            cleaned.append(value)
    return cleaned


def memory_list_item(m: dict) -> MemoryListItem:
    return MemoryListItem(
        id=document_id(m),
        orgId=m["orgId"],
        teamId=m["teamId"],
        folderId=m.get("folderId"),
        type=MemoryType(m.get("type", "note")),
        status=MemoryStatus(m.get("status", "active")),
        title=m["title"],
        tags=m.get("tags", []),
        linkedMemoryIds=m.get("linkedMemoryIds", []),
        unresolvedLinks=m.get("unresolvedLinks", []),
        source=MemorySource(m.get("source", "manual")),
        helpfulCount=m.get("helpfulCount", 0),
        notHelpfulCount=m.get("notHelpfulCount", 0),
        lastVerifiedAt=m.get("lastVerifiedAt"),
        createdAt=m["createdAt"],
        updatedAt=m["updatedAt"],
        lastOpenedAt=m.get("lastOpenedAt"),
        deletedAt=m.get("deletedAt"),
    )


def memory_out(m: dict) -> MemoryOut:
    return MemoryOut(
        id=document_id(m),
        orgId=m["orgId"],
        teamId=m["teamId"],
        folderId=m.get("folderId"),
        type=MemoryType(m.get("type", "note")),
        status=MemoryStatus(m.get("status", "active")),
        title=m["title"],
        content=m.get("content", ""),
        tags=m.get("tags", []),
        linkedMemoryIds=m.get("linkedMemoryIds", []),
        unresolvedLinks=m.get("unresolvedLinks", []),
        source=MemorySource(m.get("source", "manual")),
        sourceRef=m.get("sourceRef"),
        helpfulCount=m.get("helpfulCount", 0),
        notHelpfulCount=m.get("notHelpfulCount", 0),
        lastVerifiedAt=m.get("lastVerifiedAt"),
        verifiedBy=m.get("verifiedBy"),
        createdBy=m.get("createdBy"),
        updatedBy=m.get("updatedBy"),
        createdAt=m["createdAt"],
        updatedAt=m["updatedAt"],
        lastOpenedAt=m.get("lastOpenedAt"),
        deletedAt=m.get("deletedAt"),
    )


async def ensure_folder_exists(db: AsyncIOMotorDatabase, team_id: str, folder_id: str | None) -> None:
    if folder_id is None:
        return
    folder = await db.folders.find_one({"_id": folder_id, "teamId": team_id})
    if folder is None:
        raise HTTPException(status_code=404, detail="Project not found")


async def resolve_memory_links(
    db: AsyncIOMotorDatabase, team_id: str, content: str
) -> tuple[list[str], list[str]]:
    requested_titles = extract_wiki_links(content)
    if not requested_titles:
        return [], []

    normalized_titles = [normalize_title(t) for t in requested_titles]
    cursor = db.memories.find(
        {"teamId": team_id, "titleNormalized": {"$in": normalized_titles}, "deletedAt": None}
    )
    matched = {m["titleNormalized"]: document_id(m) async for m in cursor}

    linked: list[str] = []
    unresolved: list[str] = []
    for title in requested_titles:
        mid = matched.get(normalize_title(title))
        (linked if mid else unresolved).append(mid or title)
    return linked, unresolved


async def refresh_memory_links(db: AsyncIOMotorDatabase, memory: dict) -> dict:
    linked_ids, unresolved = await resolve_memory_links(
        db, memory["teamId"], memory.get("content", "")
    )
    await db.memories.update_one(
        {"_id": memory["_id"]},
        {"$set": {"linkedMemoryIds": linked_ids, "unresolvedLinks": unresolved}},
    )
    memory["linkedMemoryIds"] = linked_ids
    memory["unresolvedLinks"] = unresolved
    return memory


async def _load_memory(db: AsyncIOMotorDatabase, user: dict, memory_id: str, required: Role) -> dict:
    memory = await db.memories.find_one({"_id": memory_id})
    if memory is None:
        raise HTTPException(status_code=404, detail="Memory not found")
    role = await effective_role(db, document_id(user), memory["orgId"], memory["teamId"])
    ensure_role(role, required)
    return memory


VERSION_KEEP = 50  # most recent revisions retained per doc


async def snapshot_version(db: AsyncIOMotorDatabase, memory: dict) -> None:
    """Record a doc's CURRENT state as a historical revision before it gets overwritten.
    Called from every write path (human edit, agent upsert) so changes are reversible.
    Prunes to the most recent VERSION_KEEP revisions."""
    await db.memory_versions.insert_one(
        {
            "_id": str(ObjectId()),
            "memoryId": memory["_id"],
            "orgId": memory["orgId"],
            "teamId": memory["teamId"],
            "title": memory.get("title", ""),
            "content": memory.get("content", ""),
            "type": memory.get("type", "note"),
            "tags": memory.get("tags", []),
            "updatedAt": memory.get("updatedAt"),
            "updatedBy": memory.get("updatedBy"),
            "source": memory.get("source", "manual"),
            "sourceRef": memory.get("sourceRef"),
            "supersededAt": datetime.now(timezone.utc),
        }
    )
    # prune anything older than the most recent VERSION_KEEP
    old = (
        db.memory_versions.find({"memoryId": memory["_id"]}, {"_id": 1})
        .sort("supersededAt", -1)
        .skip(VERSION_KEEP)
    )
    stale_ids = [v["_id"] async for v in old]
    if stale_ids:
        await db.memory_versions.delete_many({"_id": {"$in": stale_ids}})


def version_item(v: dict) -> dict:
    return {
        "id": document_id(v),
        "title": v.get("title", ""),
        "type": v.get("type", "note"),
        "chars": len(v.get("content") or ""),
        "updatedAt": v.get("updatedAt"),
        "supersededAt": v.get("supersededAt"),
        "source": v.get("source", "manual"),
        "updatedBy": v.get("updatedBy"),
        "keyName": (v.get("sourceRef") or {}).get("keyName"),
    }


# --- Team-scoped collection routes ---


@router.get("/teams/{team_id}/memories", response_model=MemoryListResponse)
async def list_memories(
    ctx: TeamCtx,
    db: Db,
    q: str | None = None,
    folderId: str | None = None,
    tag: str | None = None,
    type: MemoryType | None = None,
    status_: MemoryStatus | None = Query(default=None, alias="status"),
    source: MemorySource | None = None,
    deleted: bool = False,
) -> MemoryListResponse:
    query: dict = {
        "teamId": ctx.team_id,
        "deletedAt": {"$ne": None} if deleted else None,
    }
    if q and q.strip():
        regex = {"$regex": re.escape(q.strip()), "$options": "i"}
        query["$or"] = [{"title": regex}, {"content": regex}, {"tags": regex}]
    if folderId is not None:
        query["folderId"] = folderId or None
    if tag:
        query["tags"] = normalize_tag(tag)
    if type is not None:
        query["type"] = type.value
    if status_ is not None:
        query["status"] = status_.value
    if source is not None:
        query["source"] = source.value

    cursor = db.memories.find(query, LIST_PROJECTION).sort("updatedAt", -1)
    return MemoryListResponse(memories=[memory_list_item(m) async for m in cursor])


@router.get("/teams/{team_id}/memories/recent", response_model=MemoryListResponse)
async def recent_memories(
    ctx: TeamCtx, db: Db, limit: int = Query(default=8, ge=1, le=30)
) -> MemoryListResponse:
    cursor = (
        db.memories.find(
            {"teamId": ctx.team_id, "deletedAt": None, "lastOpenedAt": {"$ne": None}},
            LIST_PROJECTION,
        )
        .sort("lastOpenedAt", -1)
        .limit(limit)
    )
    return MemoryListResponse(memories=[memory_list_item(m) async for m in cursor])


@router.get("/teams/{team_id}/memories/trash", response_model=MemoryListResponse)
async def trashed_memories(ctx: TeamCtx, db: Db) -> MemoryListResponse:
    cursor = db.memories.find(
        {"teamId": ctx.team_id, "deletedAt": {"$ne": None}}, LIST_PROJECTION
    ).sort("deletedAt", -1)
    return MemoryListResponse(memories=[memory_list_item(m) async for m in cursor])


@router.post("/teams/{team_id}/memories", response_model=MemoryOut, status_code=status.HTTP_201_CREATED)
async def create_memory(payload: MemoryCreate, ctx: TeamCtx, db: Db) -> MemoryOut:
    ensure_role(ctx.role, Role.editor)
    await ensure_folder_exists(db, ctx.team_id, payload.folderId)

    now = datetime.now(timezone.utc)
    memory = {
        "_id": str(ObjectId()),
        "orgId": ctx.org_id,
        "teamId": ctx.team_id,
        "folderId": payload.folderId,
        "type": payload.type.value,
        "status": payload.status.value,
        "title": payload.title.strip(),
        "titleNormalized": normalize_title(payload.title),
        "content": payload.content,
        "tags": clean_tags(payload.tags),
        "linkedMemoryIds": [],
        "unresolvedLinks": [],
        "source": MemorySource.manual.value,
        "sourceRef": None,
        "helpfulCount": 0,
        "notHelpfulCount": 0,
        "lastVerifiedAt": now,
        "verifiedBy": ctx.user_id,
        "createdBy": ctx.user_id,
        "updatedBy": ctx.user_id,
        "createdAt": now,
        "updatedAt": now,
        "lastOpenedAt": now,
        "deletedAt": None,
    }
    await db.memories.insert_one(memory)
    await embed_and_store(db, memory["_id"], memory["title"], memory["content"], memory["tags"])
    result = memory_out(await refresh_memory_links(db, memory))

    return result


@router.delete("/teams/{team_id}/memories/all")
async def delete_all_memories(ctx: TeamCtx, db: Db) -> dict:
    """Permanently wipe EVERY memory in a team, active, draft, deprecated, and
    trashed alike, plus all their version history. There is no trash step here, so
    it is irreversible and gated to admins/owners (a higher bar than single-doc
    delete, which only needs an editor). Powers the one-click "Delete all documents"
    in Settings. Folders are left intact."""
    ensure_role(ctx.role, Role.admin)

    deleted = (await db.memories.delete_many({"teamId": ctx.team_id})).deleted_count
    await db.memory_versions.delete_many({"teamId": ctx.team_id})

    return {"deleted": deleted}


# --- Single-memory routes (org/team resolved from the doc) ---


@router.get("/memories/{memory_id}", response_model=MemoryOut)
async def get_memory(memory_id: str, user: CurrentVerifiedUser, db: Db) -> MemoryOut:
    await _load_memory(db, user, memory_id, Role.viewer)
    memory = await db.memories.find_one_and_update(
        {"_id": memory_id, "deletedAt": None},
        {"$set": {"lastOpenedAt": datetime.now(timezone.utc)}},
        return_document=ReturnDocument.AFTER,
    )
    if memory is None:
        raise HTTPException(status_code=404, detail="Memory not found")
    return memory_out(memory)


@router.patch("/memories/{memory_id}", response_model=MemoryOut)
async def update_memory(memory_id: str, payload: MemoryUpdate, user: CurrentVerifiedUser, db: Db) -> MemoryOut:
    memory = await _load_memory(db, user, memory_id, Role.editor)
    if memory.get("deletedAt") is not None:
        raise HTTPException(status_code=404, detail="Memory not found")

    update: dict = {"updatedAt": datetime.now(timezone.utc), "updatedBy": document_id(user)}
    if payload.title is not None:
        update["title"] = payload.title.strip()
        update["titleNormalized"] = normalize_title(payload.title)
    if payload.content is not None:
        update["content"] = payload.content
    if payload.type is not None:
        update["type"] = payload.type.value
    if payload.status is not None:
        update["status"] = payload.status.value
    if "folderId" in payload.model_fields_set and payload.folderId != memory.get("folderId"):
        await ensure_folder_exists(db, memory["teamId"], payload.folderId)
        update["folderId"] = payload.folderId
    if payload.tags is not None:
        update["tags"] = clean_tags(payload.tags)

    content_changed = payload.content is not None and payload.content != memory.get("content", "")
    title_changed = (
        payload.title is not None
        and normalize_title(payload.title) != memory.get("titleNormalized", "")
    )

    # snapshot the pre-edit state so the change is reversible
    if content_changed or title_changed:
        await snapshot_version(db, memory)

    await db.memories.update_one({"_id": memory_id}, {"$set": update})
    updated = await db.memories.find_one({"_id": memory_id})
    assert updated is not None

    if content_changed or title_changed:
        updated = await refresh_memory_links(db, updated)
    # Re-embed when any field that feeds the vector changed (title / content / tags).
    if content_changed or title_changed or payload.tags is not None:
        await embed_and_store(
            db, memory_id, updated["title"], updated.get("content", ""), updated.get("tags", [])
        )

    return memory_out(updated)


@router.post("/memories/{memory_id}/verify", response_model=MemoryOut)
async def verify_memory(memory_id: str, user: CurrentVerifiedUser, db: Db) -> MemoryOut:
    await _load_memory(db, user, memory_id, Role.editor)
    now = datetime.now(timezone.utc)
    memory = await db.memories.find_one_and_update(
        {"_id": memory_id, "deletedAt": None},
        {"$set": {"lastVerifiedAt": now, "verifiedBy": document_id(user)}},
        return_document=ReturnDocument.AFTER,
    )
    if memory is None:
        raise HTTPException(status_code=404, detail="Memory not found")
    return memory_out(memory)


@router.post("/memories/{memory_id}/approve", response_model=MemoryOut)
async def approve_memory(memory_id: str, user: CurrentVerifiedUser, db: Db) -> MemoryOut:
    """Promote a `draft` doc to `active`, the human side of the agent write-back
    review queue. When a team enables agentWriteReview, agent writes land as drafts
    (excluded from agent retrieval) until an editor approves them here. Also stamps
    verification so an approved doc isn't immediately flagged stale."""
    await _load_memory(db, user, memory_id, Role.editor)
    now = datetime.now(timezone.utc)
    memory = await db.memories.find_one_and_update(
        {"_id": memory_id, "deletedAt": None},
        {"$set": {
            "status": MemoryStatus.active.value,
            "lastVerifiedAt": now,
            "verifiedBy": document_id(user),
            "updatedAt": now,
        }},
        return_document=ReturnDocument.AFTER,
    )
    if memory is None:
        raise HTTPException(status_code=404, detail="Memory not found")

    return memory_out(memory)


@router.delete("/memories/{memory_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def trash_memory(memory_id: str, user: CurrentVerifiedUser, db: Db) -> None:
    memory = await _load_memory(db, user, memory_id, Role.editor)
    result = await db.memories.update_one(
        {"_id": memory_id, "deletedAt": None},
        {"$set": {"deletedAt": datetime.now(timezone.utc)}},
    )
    if result.modified_count == 0:
        raise HTTPException(status_code=404, detail="Memory not found")


@router.post("/memories/{memory_id}/restore", response_model=MemoryOut)
async def restore_memory(memory_id: str, user: CurrentVerifiedUser, db: Db) -> MemoryOut:
    await _load_memory(db, user, memory_id, Role.editor)
    memory = await db.memories.find_one_and_update(
        {"_id": memory_id, "deletedAt": {"$ne": None}},
        {"$set": {"deletedAt": None, "updatedAt": datetime.now(timezone.utc)}},
        return_document=ReturnDocument.AFTER,
    )
    if memory is None:
        raise HTTPException(status_code=404, detail="Memory not found")
    return memory_out(await refresh_memory_links(db, memory))


@router.delete("/memories/{memory_id}/permanent", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def delete_memory_permanently(memory_id: str, user: CurrentVerifiedUser, db: Db) -> None:
    await _load_memory(db, user, memory_id, Role.editor)
    result = await db.memories.delete_one({"_id": memory_id, "deletedAt": {"$ne": None}})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Memory not found")
    await db.memory_versions.delete_many({"memoryId": memory_id})


# --- Version history ---


@router.get("/memories/{memory_id}/versions")
async def list_versions(memory_id: str, user: CurrentVerifiedUser, db: Db) -> dict:
    """Past revisions of a doc (newest first), metadata only. Each write, human edit or
    agent upsert, snapshots the prior content here so changes are reversible."""
    await _load_memory(db, user, memory_id, Role.viewer)
    cursor = db.memory_versions.find(
        {"memoryId": memory_id}, {"content": 0}
    ).sort("supersededAt", -1)
    return {"versions": [version_item(v) async for v in cursor]}


@router.get("/memories/{memory_id}/versions/{version_id}")
async def get_version(memory_id: str, version_id: str, user: CurrentVerifiedUser, db: Db) -> dict:
    """Full content of one past revision (for diffing against the current doc)."""
    await _load_memory(db, user, memory_id, Role.viewer)
    v = await db.memory_versions.find_one({"_id": version_id, "memoryId": memory_id})
    if v is None:
        raise HTTPException(status_code=404, detail="Version not found")
    return {**version_item(v), "content": v.get("content", ""), "tags": v.get("tags", [])}


@router.post("/memories/{memory_id}/versions/{version_id}/restore", response_model=MemoryOut)
async def restore_version(memory_id: str, version_id: str, user: CurrentVerifiedUser, db: Db) -> MemoryOut:
    """Roll the doc back to a past revision. Snapshots the current state first, so a
    restore is itself reversible."""
    memory = await _load_memory(db, user, memory_id, Role.editor)
    if memory.get("deletedAt") is not None:
        raise HTTPException(status_code=404, detail="Memory not found")
    v = await db.memory_versions.find_one({"_id": version_id, "memoryId": memory_id})
    if v is None:
        raise HTTPException(status_code=404, detail="Version not found")

    await snapshot_version(db, memory)  # current state stays recoverable
    now = datetime.now(timezone.utc)
    await db.memories.update_one(
        {"_id": memory_id},
        {"$set": {
            "title": v.get("title", memory["title"]),
            "titleNormalized": normalize_title(v.get("title", memory["title"])),
            "content": v.get("content", ""),
            "type": v.get("type", memory.get("type", "note")),
            "tags": v.get("tags", []),
            "updatedAt": now,
            "updatedBy": document_id(user),
        }},
    )
    updated = await db.memories.find_one({"_id": memory_id})
    assert updated is not None
    await embed_and_store(
        db, memory_id, updated["title"], updated.get("content", ""), updated.get("tags", [])
    )

    return memory_out(await refresh_memory_links(db, updated))
