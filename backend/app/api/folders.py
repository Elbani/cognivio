from __future__ import annotations

from datetime import datetime, timezone

from bson import ObjectId
from fastapi import APIRouter, HTTPException, status
from pymongo.errors import DuplicateKeyError

from app.api.deps import CurrentVerifiedUser, Db, TeamCtx, effective_role, ensure_role, plan_unlocked
from app.core.config import settings
from app.models.enums import Role
from app.models.schemas import FolderCreate, FolderOut, FolderUpdate, document_id
from app.utils import normalize_title

router = APIRouter(prefix="/api", tags=["folders"])


def folder_out(folder: dict) -> FolderOut:
    return FolderOut(
        id=document_id(folder),
        teamId=folder["teamId"],
        name=folder["name"],
        parentId=folder.get("parentId"),
        createdAt=folder["createdAt"],
        updatedAt=folder["updatedAt"],
    )


async def ensure_parent_exists(
    db: Db, team_id: str, parent_id: str | None, exclude_id: str | None = None
) -> None:
    if parent_id is None:
        return

    visited: set[str] = set()
    current = parent_id
    while current is not None:
        if current == exclude_id:
            raise HTTPException(status_code=400, detail="Circular folder reference detected")
        if current in visited:
            raise HTTPException(status_code=400, detail="Circular folder reference detected")
        visited.add(current)
        folder = await db.folders.find_one({"_id": current, "teamId": team_id})
        if folder is None:
            raise HTTPException(status_code=404, detail="Parent project not found")
        current = folder.get("parentId")


async def _load_folder(db: Db, user: dict, folder_id: str, required: Role) -> dict:
    folder = await db.folders.find_one({"_id": folder_id})
    if folder is None:
        raise HTTPException(status_code=404, detail="Project not found")
    team = await db.teams.find_one({"_id": folder["teamId"]})
    if team is None:
        raise HTTPException(status_code=404, detail="Team not found")
    role = await effective_role(db, document_id(user), team["orgId"], folder["teamId"])
    ensure_role(role, required)
    return folder


@router.get("/teams/{team_id}/folders", response_model=list[FolderOut])
async def list_folders(ctx: TeamCtx, db: Db) -> list[FolderOut]:
    cursor = db.folders.find({"teamId": ctx.team_id}).sort("name", 1)
    return [folder_out(folder) async for folder in cursor]


@router.post("/teams/{team_id}/folders", response_model=FolderOut, status_code=status.HTTP_201_CREATED)
async def create_folder(payload: FolderCreate, ctx: TeamCtx, db: Db) -> FolderOut:
    ensure_role(ctx.role, Role.editor)
    # Free plan = one project. A "project" is a TOP-LEVEL folder (parentId None);
    # subfolders organize within it and are unlimited, so only gate new top-level ones.
    if (
        not plan_unlocked(ctx.org, ctx.user)
        and payload.parentId is None
        and await db.folders.count_documents({"teamId": ctx.team_id, "parentId": None}) >= 1
    ):
        raise HTTPException(
            status_code=402,
            detail=f"Multiple projects are an Enterprise feature. The Free plan includes one. {settings.upgrade_hint}",
        )
    await ensure_parent_exists(db, ctx.team_id, payload.parentId)

    now = datetime.now(timezone.utc)
    folder = {
        "_id": str(ObjectId()),
        "teamId": ctx.team_id,
        "name": payload.name.strip(),
        "nameNormalized": normalize_title(payload.name),
        "parentId": payload.parentId,
        "createdAt": now,
        "updatedAt": now,
    }

    try:
        await db.folders.insert_one(folder)
    except DuplicateKeyError as exc:
        raise HTTPException(status_code=409, detail="Project name already exists") from exc

    return folder_out(folder)


@router.patch("/folders/{folder_id}", response_model=FolderOut)
async def update_folder(folder_id: str, payload: FolderUpdate, user: CurrentVerifiedUser, db: Db) -> FolderOut:
    folder = await _load_folder(db, user, folder_id, Role.editor)
    team_id = folder["teamId"]

    update: dict = {"updatedAt": datetime.now(timezone.utc)}
    if payload.name is not None:
        update["name"] = payload.name.strip()
        update["nameNormalized"] = normalize_title(payload.name)
    if "parentId" in payload.model_fields_set and payload.parentId != folder.get("parentId"):
        await ensure_parent_exists(db, team_id, payload.parentId, exclude_id=folder_id)
        update["parentId"] = payload.parentId

    try:
        await db.folders.update_one({"_id": folder_id}, {"$set": update})
    except DuplicateKeyError as exc:
        raise HTTPException(status_code=409, detail="Project name already exists") from exc

    updated = await db.folders.find_one({"_id": folder_id})
    assert updated is not None
    return folder_out(updated)


@router.delete("/folders/{folder_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def delete_folder(folder_id: str, user: CurrentVerifiedUser, db: Db) -> None:
    folder = await _load_folder(db, user, folder_id, Role.editor)
    team_id = folder["teamId"]

    child = await db.folders.find_one({"teamId": team_id, "parentId": folder_id})
    if child is not None:
        raise HTTPException(status_code=409, detail="Delete child projects first")

    await db.folders.delete_one({"_id": folder_id})
    await db.memories.update_many(
        {"teamId": team_id, "folderId": folder_id}, {"$set": {"folderId": None}}
    )
