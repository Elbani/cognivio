from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.core.config import is_platform_admin, settings
from app.core.security import decode_access_token
from app.db.database import get_db
from app.models.enums import ROLE_RANK, Role, role_at_least
from app.models.schemas import document_id

bearer_scheme = HTTPBearer(auto_error=False)


async def current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)]
) -> dict:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing credentials"
        )

    user_id = decode_access_token(credentials.credentials)
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials"
        )

    try:
        object_id = ObjectId(user_id)
    except InvalidId as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials"
        ) from exc

    user = await get_db().users.find_one({"_id": object_id})
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials"
        )
    if user.get("suspendedAt") is not None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Account suspended"
        )
    return user


Db = Annotated[AsyncIOMotorDatabase, Depends(get_db)]
CurrentUser = Annotated[dict, Depends(current_user)]


async def verified_user(user: CurrentUser) -> dict:
    """A signed-in user who has verified their email.
    Gates all workspace/data access so unverified users can't use the platform."""
    if not user.get("emailVerified"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Email not verified"
        )
    return user


CurrentVerifiedUser = Annotated[dict, Depends(verified_user)]


async def platform_admin(user: CurrentUser) -> dict:
    """A signed-in user whose email is on the ADMIN_EMAILS allowlist. Gates the
    platform admin console. Access is config-driven, never a self-service flag."""
    # The allowlist names addresses, so the account must have proven it owns the address.
    if not is_platform_admin(user.get("email")) or not user.get("emailVerified"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required"
        )
    return user


PlatformAdmin = Annotated[dict, Depends(platform_admin)]


def effective_plan(org: dict | None) -> str:
    """The plan the org behaves as. SELF_HOSTED installs treat every org as Enterprise,
    so the API and the SPA (which reads the plan from the org payload) agree."""
    if settings.self_hosted:
        return "enterprise"
    return (org or {}).get("plan", "free")


def plan_unlocked(org: dict | None, user: dict) -> bool:
    """True when Enterprise-only features are available: the install is SELF_HOSTED, the
    org is on the Enterprise plan, or the signed-in user is a platform admin
    (ADMIN_EMAILS). Admins operate the platform and must never be stopped by the
    Free-plan paywall on their own workspaces."""
    if is_platform_admin(user.get("email")):
        return True
    return effective_plan(org) == "enterprise"


# --- Membership / role resolution ---


async def effective_role(
    db: AsyncIOMotorDatabase, user_id: str, org_id: str, team_id: str | None = None
) -> str | None:
    """Highest role a user holds in an org, optionally elevated by a
    team-scoped membership for the given team."""
    cursor = db.memberships.find({"userId": user_id, "orgId": org_id})
    best: str | None = None
    best_rank = -1

    async for m in cursor:
        if m.get("teamId") not in (None, team_id):
            continue
        rank = ROLE_RANK.get(m["role"], -1)
        if rank > best_rank:
            best_rank = rank
            best = m["role"]
    return best


def ensure_role(role: str | None, required: Role) -> None:
    if role is None or not role_at_least(role, required.value):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")


@dataclass
class OrgContext:
    user: dict
    org: dict
    role: str

    @property
    def user_id(self) -> str:
        return document_id(self.user)

    @property
    def org_id(self) -> str:
        return document_id(self.org)


@dataclass
class TeamContext(OrgContext):
    team: dict

    @property
    def team_id(self) -> str:
        return document_id(self.team)


async def org_context(org_id: str, user: CurrentVerifiedUser, db: Db) -> OrgContext:
    org = await db.organizations.find_one({"_id": org_id})
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    role = await effective_role(db, document_id(user), org_id)
    if role is None:
        raise HTTPException(status_code=403, detail="Not a member of this organization")
    return OrgContext(user=user, org=org, role=role)


async def team_context(team_id: str, user: CurrentVerifiedUser, db: Db) -> TeamContext:
    team = await db.teams.find_one({"_id": team_id})
    if team is None:
        raise HTTPException(status_code=404, detail="Team not found")
    org = await db.organizations.find_one({"_id": team["orgId"]})
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    role = await effective_role(db, document_id(user), team["orgId"], team_id)
    if role is None:
        raise HTTPException(status_code=403, detail="Not a member of this team")
    return TeamContext(user=user, org=org, role=role, team=team)


OrgCtx = Annotated[OrgContext, Depends(org_context)]
TeamCtx = Annotated[TeamContext, Depends(team_context)]
