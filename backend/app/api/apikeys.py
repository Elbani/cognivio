from __future__ import annotations

from datetime import datetime, timezone

from bson import ObjectId
from fastapi import APIRouter, HTTPException, status

from app.api.deps import Db, OrgCtx, ensure_role
from app.core.security import generate_api_key
from app.models.enums import ApiScope, Role
from app.models.schemas import ApiKeyCreate, ApiKeyCreated, ApiKeyOut, document_id

router = APIRouter(prefix="/api", tags=["api-keys"])


def api_key_out(doc: dict) -> ApiKeyOut:
    return ApiKeyOut(
        id=document_id(doc),
        orgId=doc["orgId"],
        teamId=doc.get("teamId"),
        name=doc["name"],
        prefix=doc["prefix"],
        scopes=[ApiScope(s) for s in doc.get("scopes", [])],
        createdAt=doc["createdAt"],
        lastUsedAt=doc.get("lastUsedAt"),
        expiresAt=doc.get("expiresAt"),
        revokedAt=doc.get("revokedAt"),
    )


@router.get("/orgs/{org_id}/keys", response_model=list[ApiKeyOut])
async def list_keys(ctx: OrgCtx, db: Db) -> list[ApiKeyOut]:
    ensure_role(ctx.role, Role.admin)
    cursor = db.api_keys.find({"orgId": ctx.org_id}).sort("createdAt", -1)
    return [api_key_out(doc) async for doc in cursor]


@router.post("/orgs/{org_id}/keys", response_model=ApiKeyCreated, status_code=status.HTTP_201_CREATED)
async def create_key(payload: ApiKeyCreate, ctx: OrgCtx, db: Db) -> ApiKeyCreated:
    ensure_role(ctx.role, Role.admin)

    if payload.teamId is not None:
        team = await db.teams.find_one({"_id": payload.teamId, "orgId": ctx.org_id})
        if team is None:
            raise HTTPException(status_code=404, detail="Team not found")

    full_key, prefix, key_hash = generate_api_key()
    doc = {
        "_id": str(ObjectId()),
        "orgId": ctx.org_id,
        "teamId": payload.teamId,
        "name": payload.name.strip(),
        "prefix": prefix,
        "keyHash": key_hash,
        "scopes": [s.value for s in payload.scopes],
        "createdBy": ctx.user_id,
        "createdAt": datetime.now(timezone.utc),
        "lastUsedAt": None,
        "expiresAt": payload.expiresAt,
        "revokedAt": None,
    }
    await db.api_keys.insert_one(doc)

    created = api_key_out(doc).model_dump()
    return ApiKeyCreated(**created, key=full_key)


@router.delete("/orgs/{org_id}/keys/{key_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def revoke_key(key_id: str, ctx: OrgCtx, db: Db) -> None:
    ensure_role(ctx.role, Role.admin)
    result = await db.api_keys.update_one(
        {"_id": key_id, "orgId": ctx.org_id, "revokedAt": None},
        {"$set": {"revokedAt": datetime.now(timezone.utc)}},
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="API key not found")
