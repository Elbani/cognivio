from __future__ import annotations

from datetime import datetime, timezone

from bson import ObjectId
from fastapi import APIRouter, BackgroundTasks, HTTPException, status
from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo.errors import DuplicateKeyError

from app.api.deps import CurrentVerifiedUser, Db, OrgCtx, TeamCtx, effective_plan, ensure_role, plan_unlocked
from app.core.config import settings
from app.core.email import send_member_added
from app.db.database import run_atomic
from app.models.enums import ROLE_RANK, Role
from app.models.schemas import (
    MemberInvite,
    MemberOut,
    MemberUpdate,
    OrgCreate,
    OrgOut,
    OrgUpdate,
    TeamCreate,
    TeamOut,
    TeamUpdate,
    document_id,
)
from app.utils import slugify

router = APIRouter(prefix="/api", tags=["orgs"])


async def _unique_slug(
    db: AsyncIOMotorDatabase, collection: str, base: str, query: dict | None = None
) -> str:
    query = query or {}
    slug = base
    i = 2
    while await db[collection].find_one({**query, "slug": slug}):
        slug = f"{base}-{i}"
        i += 1
    return slug


async def create_org_with_owner(db: AsyncIOMotorDatabase, user_id: str, name: str) -> dict:
    now = datetime.now(timezone.utc)
    slug = await _unique_slug(db, "organizations", slugify(name))
    org = {"_id": str(ObjectId()), "name": name.strip(), "slug": slug, "plan": "free",
           "createdAt": now, "updatedAt": now}
    team = {
        "_id": str(ObjectId()),
        "orgId": org["_id"],
        "name": "Main",
        "slug": "main",
        "createdAt": now,
        "updatedAt": now,
    }
    membership = {
        "_id": str(ObjectId()),
        "userId": user_id,
        "orgId": org["_id"],
        "teamId": None,
        "role": Role.owner.value,
        "createdAt": now,
    }

    # All three inserts commit together, a partial create would otherwise leave an
    # org with no owner membership (uneditable and undeletable through the UI).
    async def _work(session):
        await db.organizations.insert_one(org, session=session)
        await db.teams.insert_one(team, session=session)
        await db.memberships.insert_one(membership, session=session)

    await run_atomic(db, _work)
    return org


def org_out(org: dict, role: str) -> OrgOut:
    return OrgOut(
        id=document_id(org),
        name=org["name"],
        slug=org["slug"],
        role=Role(role),
        plan=effective_plan(org),
        createdAt=org["createdAt"],
        updatedAt=org["updatedAt"],
    )


def team_out(team: dict) -> TeamOut:
    return TeamOut(
        id=document_id(team),
        orgId=team["orgId"],
        name=team["name"],
        slug=team["slug"],
        agentWriteReview=bool(team.get("agentWriteReview", False)),
        createdAt=team["createdAt"],
        updatedAt=team["updatedAt"],
    )


# --- Organizations ---


@router.get("/orgs", response_model=list[OrgOut])
async def list_orgs(user: CurrentVerifiedUser, db: Db) -> list[OrgOut]:
    user_id = document_id(user)
    org_ids: dict[str, str] = {}
    async for m in db.memberships.find({"userId": user_id}):
        cur = org_ids.get(m["orgId"])
        if cur is None or ROLE_RANK.get(m["role"], -1) > ROLE_RANK.get(cur, -1):
            org_ids[m["orgId"]] = m["role"]

    result: list[OrgOut] = []
    async for org in db.organizations.find({"_id": {"$in": list(org_ids)}}).sort("name", 1):
        result.append(org_out(org, org_ids[document_id(org)]))
    return result


@router.post("/orgs", response_model=OrgOut, status_code=status.HTTP_201_CREATED)
async def create_org(payload: OrgCreate, user: CurrentVerifiedUser, db: Db) -> OrgOut:
    user_id = document_id(user)
    # Free plan = a single organization. More needs the Teams plan.
    my_org_ids = await db.memberships.distinct("orgId", {"userId": user_id})
    if my_org_ids and not plan_unlocked(None, user):
        plans = await db.organizations.distinct("plan", {"_id": {"$in": my_org_ids}})
        if "enterprise" not in plans:
            raise HTTPException(
                status_code=402,
                detail=f"Multiple organizations are on the Teams plan. The free plan includes one. {settings.upgrade_hint}",
            )
    org = await create_org_with_owner(db, user_id, payload.name)
    return org_out(org, Role.owner.value)


@router.get("/orgs/{org_id}", response_model=OrgOut)
async def get_org(ctx: OrgCtx) -> OrgOut:
    return org_out(ctx.org, ctx.role)


@router.patch("/orgs/{org_id}", response_model=OrgOut)
async def update_org(payload: OrgUpdate, ctx: OrgCtx, db: Db) -> OrgOut:
    ensure_role(ctx.role, Role.admin)
    update: dict = {"updatedAt": datetime.now(timezone.utc)}
    if payload.name is not None:
        update["name"] = payload.name.strip()
    await db.organizations.update_one({"_id": ctx.org_id}, {"$set": update})
    org = await db.organizations.find_one({"_id": ctx.org_id})
    assert org is not None
    return org_out(org, ctx.role)


# --- Members ---


@router.get("/orgs/{org_id}/members", response_model=list[MemberOut])
async def list_members(ctx: OrgCtx, db: Db) -> list[MemberOut]:
    members: list[MemberOut] = []
    async for m in db.memberships.find({"orgId": ctx.org_id}):
        try:
            user = await db.users.find_one({"_id": ObjectId(m["userId"])})
        except Exception:
            user = None
        if user is None:
            continue
        members.append(
            MemberOut(
                userId=m["userId"],
                email=user["email"],
                name=user["name"],
                role=Role(m["role"]),
                teamId=m.get("teamId"),
            )
        )
    return members


async def _guard_owner_change(db: AsyncIOMotorDatabase, ctx: OrgCtx, target_user_id: str | None, new_role: Role | None) -> None:
    """Only an owner may grant the owner role or change or remove an owner, and an
    organization always keeps at least one owner."""
    target = None
    if target_user_id is not None:
        target = await db.memberships.find_one(
            {"orgId": ctx.org_id, "userId": target_user_id, "teamId": None}
        )
    target_is_owner = bool(target and target.get("role") == Role.owner.value)
    if (target_is_owner or new_role == Role.owner) and ctx.role != Role.owner.value:
        raise HTTPException(status_code=403, detail="Only an owner can assign or change the owner role")
    if target_is_owner and new_role != Role.owner:
        owners = await db.memberships.count_documents(
            {"orgId": ctx.org_id, "teamId": None, "role": Role.owner.value}
        )
        if owners <= 1:
            raise HTTPException(status_code=400, detail="An organization needs at least one owner")


@router.post("/orgs/{org_id}/members", response_model=MemberOut, status_code=status.HTTP_201_CREATED)
async def invite_member(payload: MemberInvite, ctx: OrgCtx, db: Db, background_tasks: BackgroundTasks) -> MemberOut:
    ensure_role(ctx.role, Role.admin)
    await _guard_owner_change(db, ctx, None, payload.role)
    user = await db.users.find_one({"email": payload.email.lower()})
    if user is None:
        raise HTTPException(status_code=404, detail="No user with that email")

    # Free plan = one person. Adding a *new* teammate needs the Teams plan.
    if not plan_unlocked(ctx.org, ctx.user):
        existing = await db.memberships.distinct("userId", {"orgId": ctx.org_id})
        if document_id(user) not in existing and len(existing) >= 1:
            raise HTTPException(
                status_code=402,
                detail="Adding teammates is on the Teams plan. The free plan is for one person. "
                f"{settings.upgrade_hint}",
            )

    if payload.teamId is not None:
        team = await db.teams.find_one({"_id": payload.teamId, "orgId": ctx.org_id})
        if team is None:
            raise HTTPException(status_code=404, detail="Team not found")

    membership = {
        "_id": str(ObjectId()),
        "userId": document_id(user),
        "orgId": ctx.org_id,
        "teamId": payload.teamId,
        "role": payload.role.value,
        "createdAt": datetime.now(timezone.utc),
    }
    try:
        await db.memberships.insert_one(membership)
    except DuplicateKeyError as exc:
        raise HTTPException(status_code=409, detail="Already a member") from exc

    background_tasks.add_task(
        send_member_added, user["email"], ctx.org["name"], ctx.user.get("name")
    )

    return MemberOut(
        userId=document_id(user),
        email=user["email"],
        name=user["name"],
        role=payload.role,
        teamId=payload.teamId,
    )


@router.patch("/orgs/{org_id}/members/{user_id}", response_model=MemberOut)
async def update_member(user_id: str, payload: MemberUpdate, ctx: OrgCtx, db: Db) -> MemberOut:
    ensure_role(ctx.role, Role.admin)
    membership = await db.memberships.find_one(
        {"orgId": ctx.org_id, "userId": user_id, "teamId": None}
    )
    if membership is None:
        raise HTTPException(status_code=404, detail="Membership not found")
    await _guard_owner_change(db, ctx, user_id, payload.role)
    await db.memberships.update_one({"_id": membership["_id"]}, {"$set": {"role": payload.role.value}})

    user = await db.users.find_one({"_id": ObjectId(user_id)})
    assert user is not None
    return MemberOut(
        userId=user_id, email=user["email"], name=user["name"], role=payload.role, teamId=None
    )


@router.delete("/orgs/{org_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def remove_member(user_id: str, ctx: OrgCtx, db: Db) -> None:
    ensure_role(ctx.role, Role.admin)
    if user_id == ctx.user_id:
        raise HTTPException(status_code=400, detail="Cannot remove yourself")
    await _guard_owner_change(db, ctx, user_id, None)
    result = await db.memberships.delete_many({"orgId": ctx.org_id, "userId": user_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Membership not found")


# --- Teams ---


@router.get("/orgs/{org_id}/teams", response_model=list[TeamOut])
async def list_teams(ctx: OrgCtx, db: Db) -> list[TeamOut]:
    teams = [team_out(t) async for t in db.teams.find({"orgId": ctx.org_id}).sort("name", 1)]
    return teams


@router.post("/orgs/{org_id}/teams", response_model=TeamOut, status_code=status.HTTP_201_CREATED)
async def create_team(payload: TeamCreate, ctx: OrgCtx, db: Db) -> TeamOut:
    ensure_role(ctx.role, Role.admin)
    if not plan_unlocked(ctx.org, ctx.user) and await db.teams.count_documents({"orgId": ctx.org_id}) >= 1:
        raise HTTPException(
            status_code=402,
            detail=f"Multiple teams are on the Teams plan. The free plan includes one team. {settings.upgrade_hint}",
        )
    now = datetime.now(timezone.utc)
    slug = await _unique_slug(db, "teams", slugify(payload.name), {"orgId": ctx.org_id})
    team = {
        "_id": str(ObjectId()),
        "orgId": ctx.org_id,
        "name": payload.name.strip(),
        "slug": slug,
        "createdAt": now,
        "updatedAt": now,
    }
    await db.teams.insert_one(team)
    return team_out(team)


@router.patch("/teams/{team_id}", response_model=TeamOut)
async def update_team(payload: TeamUpdate, ctx: TeamCtx, db: Db) -> TeamOut:
    ensure_role(ctx.role, Role.admin)
    update: dict = {"updatedAt": datetime.now(timezone.utc)}
    if payload.name is not None:
        update["name"] = payload.name.strip()
        update["slug"] = await _unique_slug(
            db, "teams", slugify(payload.name), {"orgId": ctx.org_id}
        )
    if payload.agentWriteReview is not None:
        update["agentWriteReview"] = payload.agentWriteReview
    await db.teams.update_one({"_id": ctx.team_id}, {"$set": update})
    team = await db.teams.find_one({"_id": ctx.team_id})
    assert team is not None
    return team_out(team)


@router.delete("/teams/{team_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def delete_team(ctx: TeamCtx, db: Db) -> None:
    ensure_role(ctx.role, Role.admin)
    if await db.memories.find_one({"teamId": ctx.team_id}) is not None:
        raise HTTPException(status_code=409, detail="Delete the team's memories first")
    if await db.folders.find_one({"teamId": ctx.team_id}) is not None:
        raise HTTPException(status_code=409, detail="Delete the team's projects first")
    await db.teams.delete_one({"_id": ctx.team_id})
    await db.memberships.delete_many({"teamId": ctx.team_id})
