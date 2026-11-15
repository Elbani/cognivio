from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from bson import ObjectId
from fastapi import APIRouter, HTTPException, Query, Request, status
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.api.deps import Db, PlatformAdmin
from app.core.config import is_platform_admin
from app.db.database import run_atomic
from app.models.schemas import document_id

router = APIRouter(prefix="/api/admin", tags=["admin"])

# Plans the app actually understands (the Free-plan gates in orgs.py check for
# "enterprise", shown to users as Teams). Admin plan changes are restricted to these so the gates stay coherent.
ALLOWED_PLANS = {"free", "enterprise"}

# Lookups whose resultCount we treat as the "did the KB return a doc?" signal. Used by
# both the Overview hit-rate and the Usage tab's retrieval facets.
_RETRIEVAL_ACTIONS = ["context.pack", "memory.search"]


# --- Helpers ---


def _uid(user: dict) -> str:
    return document_id(user)


async def _log_action(
    db: AsyncIOMotorDatabase,
    admin: dict,
    action: str,
    *,
    request: Request | None = None,
    **target: object,
) -> None:
    """Record a destructive/moderation action so admin activity is itself auditable."""
    await db.admin_actions.insert_one(
        {
            "_id": str(ObjectId()),
            "action": action,
            "adminId": _uid(admin),
            "adminEmail": admin.get("email"),
            "ip": (request.headers.get("x-forwarded-for", "").split(",")[0].strip() or
                   (request.client.host if request and request.client else None))
            if request else None,
            "at": datetime.now(timezone.utc),
            **target,
        }
    )


async def _org_team_ids(db: AsyncIOMotorDatabase, org_id: str, session=None) -> list[str]:
    return [document_id(t) async for t in db.teams.find({"orgId": org_id}, {"_id": 1}, session=session)]


async def _db_storage(db: AsyncIOMotorDatabase) -> dict | None:
    """Database storage usage via Mongo's `dbStats`. `fsTotalSize`/`fsUsedSize` are the
    filesystem the data lives on (present on self-hosted/WiredTiger; absent on some
    managed/shared tiers), they give the real "space left". `freeStorageSize` is space
    already allocated to the DB files but reusable. All bytes. Returns None if the command
    is unavailable (e.g. insufficient privileges), so the UI can simply hide the panel."""
    try:
        stats = await db.command({"dbStats": 1, "scale": 1, "freeStorage": 1})
    except Exception:  # noqa: BLE001 - command may be denied on managed tiers
        return None
    fs_total = stats.get("fsTotalSize")
    fs_used = stats.get("fsUsedSize")
    return {
        "dataSize": int(stats.get("dataSize", 0)),
        "storageSize": int(stats.get("storageSize", 0)),
        "indexSize": int(stats.get("indexSize", 0)),
        "totalSize": int(stats.get("totalSize", stats.get("storageSize", 0))),
        "freeStorageSize": int(stats.get("totalFreeStorageSize", stats.get("freeStorageSize", 0)) or 0),
        "fsTotalSize": int(fs_total) if fs_total is not None else None,
        "fsUsedSize": int(fs_used) if fs_used is not None else None,
        "fsFreeSize": int(fs_total - fs_used) if fs_total is not None and fs_used is not None else None,
    }


async def _delete_org(db: AsyncIOMotorDatabase, org_id: str, session=None) -> dict:
    """Hard-delete an org and everything under it. Returns a count of what was removed.
    Runs inside `session` so the whole cascade commits or rolls back as one unit, a
    mid-way failure must not strand orphaned memories/keys or an owner-less org."""
    team_ids = await _org_team_ids(db, org_id, session=session)
    memory_ids = [
        document_id(m) async for m in db.memories.find({"orgId": org_id}, {"_id": 1}, session=session)
    ]

    counts: dict[str, int] = {}
    if memory_ids:
        counts["memory_versions"] = (
            await db.memory_versions.delete_many({"memoryId": {"$in": memory_ids}}, session=session)
        ).deleted_count
    counts["memories"] = (await db.memories.delete_many({"orgId": org_id}, session=session)).deleted_count
    if team_ids:
        counts["folders"] = (
            await db.folders.delete_many({"teamId": {"$in": team_ids}}, session=session)
        ).deleted_count
        counts["repos"] = (
            await db.repos.delete_many({"teamId": {"$in": team_ids}}, session=session)
        ).deleted_count
    counts["api_keys"] = (await db.api_keys.delete_many({"orgId": org_id}, session=session)).deleted_count
    counts["audit_log"] = (await db.audit_log.delete_many({"orgId": org_id}, session=session)).deleted_count
    counts["teams"] = (await db.teams.delete_many({"orgId": org_id}, session=session)).deleted_count
    counts["memberships"] = (
        await db.memberships.delete_many({"orgId": org_id}, session=session)
    ).deleted_count
    counts["organizations"] = (
        await db.organizations.delete_one({"_id": org_id}, session=session)
    ).deleted_count
    return counts


async def _owned_org_ids(db: AsyncIOMotorDatabase, user_id: str, session=None) -> list[str]:
    """Orgs this user owns (org-level owner membership)."""
    ids: list[str] = []
    async for m in db.memberships.find(
        {"userId": user_id, "teamId": None, "role": "owner"}, session=session
    ):
        ids.append(m["orgId"])
    return ids


async def _delete_user(db: AsyncIOMotorDatabase, user_id: str, session=None) -> dict:
    """Hard-delete a user, cascading their owned orgs and all session/token state.
    Threaded through `session` so the user row and every cascaded org/token go together."""
    # Validate the id up front (callers already loaded the user, so this is belt-and-suspenders)
    # NOT inside a try around the delete, because a bare except there could swallow a
    # transient in-transaction write conflict and let the cascade commit without the user row.
    try:
        oid = ObjectId(user_id)
    except Exception as exc:  # noqa: BLE001 - malformed id
        raise HTTPException(status_code=404, detail="User not found") from exc

    counts: dict[str, int] = {"orgs": 0}
    for org_id in await _owned_org_ids(db, user_id, session=session):
        await _delete_org(db, org_id, session=session)
        counts["orgs"] += 1
    counts["memberships"] = (
        await db.memberships.delete_many({"userId": user_id}, session=session)
    ).deleted_count
    for coll in ("refresh_tokens", "password_resets", "email_verifications"):
        await db[coll].delete_many({"userId": user_id}, session=session)
    counts["user"] = (await db.users.delete_one({"_id": oid}, session=session)).deleted_count
    return counts


# --- Overview analytics ---


@router.get("/overview")
async def overview(admin: PlatformAdmin, db: Db, days: int = Query(default=30, ge=1, le=365)) -> dict:
    """Platform-wide health: totals, growth, agent activity, and abuse counts."""
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=days)
    day_ago = now - timedelta(days=1)
    week_ago = now - timedelta(days=7)
    two_weeks_ago = now - timedelta(days=14)

    totals = {
        "users": await db.users.count_documents({}),
        "verifiedUsers": await db.users.count_documents({"emailVerified": True}),
        "suspendedUsers": await db.users.count_documents({"suspendedAt": {"$ne": None}}),
        "orgs": await db.organizations.count_documents({}),
        "teams": await db.teams.count_documents({}),
        "memories": await db.memories.count_documents({"deletedAt": None}),
        "apiKeys": await db.api_keys.count_documents({"revokedAt": None}),
    }

    signups = {
        "last24h": await db.users.count_documents({"createdAt": {"$gte": day_ago}}),
        "last7d": await db.users.count_documents({"createdAt": {"$gte": week_ago}}),
        # The week before last, lets the UI show week-over-week momentum, not just a count.
        "prev7d": await db.users.count_documents(
            {"createdAt": {"$gte": two_weeks_ago, "$lt": week_ago}}
        ),
        f"last{days}d": await db.users.count_documents({"createdAt": {"$gte": since}}),
    }

    # Single pass over the window's agent actions: bucket by action, and track who's
    # actually active (orgs, keys) plus the KB's core value signal, retrieval hit-rate
    # (how often a context.pack / memory.search actually returned a doc).
    agent_activity: dict[str, int] = {}
    active_keys: set[str] = set()
    active_orgs: set[str] = set()
    lookups = hits = 0
    async for e in db.audit_log.find(
        {"at": {"$gte": since}}, {"action": 1, "keyId": 1, "orgId": 1, "resultCount": 1}
    ):
        action = e["action"]
        agent_activity[action] = agent_activity.get(action, 0) + 1
        if e.get("keyId"):
            active_keys.add(e["keyId"])
        if e.get("orgId"):
            active_orgs.add(e["orgId"])
        if action in _RETRIEVAL_ACTIONS:
            lookups += 1
            if (e.get("resultCount") or 0) > 0:
                hits += 1

    # Abuse signals over the window, bucketed by type.
    security_counts: dict[str, int] = {}
    async for e in db.security_events.find({"at": {"$gte": since}}, {"type": 1}):
        security_counts[e["type"]] = security_counts.get(e["type"], 0) + 1

    # Plan mix across all orgs.
    plan_counts: dict[str, int] = {}
    async for grp in db.organizations.aggregate([{"$group": {"_id": "$plan", "n": {"$sum": 1}}}]):
        plan_counts[grp["_id"] or "free"] = grp["n"]

    # Daily new-user trend for a sparkline (real signups only).
    signup_trend: list[dict] = []
    for i in range(min(days, 30) - 1, -1, -1):
        start = (now - timedelta(days=i)).replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)
        signup_trend.append({
            "date": start.date().isoformat(),
            "count": await db.users.count_documents(
                {"createdAt": {"$gte": start, "$lt": end}}
            ),
        })

    return {
        "days": days,
        "totals": totals,
        "plans": plan_counts,
        "storage": await _db_storage(db),
        "signups": signups,
        "signupTrend": signup_trend,
        "agentActivity": {
            "byAction": agent_activity,
            "totalEvents": sum(agent_activity.values()),
            "activeKeys": len(active_keys),
            "activeOrgs": len(active_orgs),
        },
        "retrieval": {
            "lookups": lookups,
            "hits": hits,
            "hitRate": round(hits / lookups, 3) if lookups else None,
        },
        "security": {
            "byType": security_counts,
            "totalEvents": sum(security_counts.values()),
        },
    }


# --- Usage analytics ---
#
# All usage is reconstructed from `audit_log` (agent actions, keyed by orgId + keyId +
# at). There is NO per-human-user attribution on those events, so a user's usage is the
# aggregate of the orgs they belong to. One $facet pass over the window does the grouping;
# small follow-ups (distinct active ids, org/key name enrichment) run on bounded sets.
# (_RETRIEVAL_ACTIONS, the lookup actions whose resultCount signals a hit, is defined
# up top since the Overview hit-rate uses it too.)

# Shared facets every usage view needs. Callers add byOrg / byKey as needed.
_BASE_FACETS: dict = {
    "byAction": [{"$group": {"_id": "$action", "n": {"$sum": 1}}}],
    "byDay": [{"$group": {"_id": {"$dateToString": {"format": "%Y-%m-%d", "date": "$at"}}, "n": {"$sum": 1}}}],
    "retrieval": [
        {"$match": {"action": {"$in": _RETRIEVAL_ACTIONS}}},
        {"$group": {"_id": None, "lookups": {"$sum": 1},
                    "hits": {"$sum": {"$cond": [{"$gt": ["$resultCount", 0]}, 1, 0]}}}},
    ],
    "total": [{"$count": "n"}],
    "lastActive": [{"$group": {"_id": None, "at": {"$max": "$at"}}}],
}


async def _usage_facets(db: AsyncIOMotorDatabase, match: dict, extra: dict | None = None) -> dict:
    """Run the faceted usage aggregation over `audit_log` rows matching `match`."""
    pipeline = [{"$match": match}, {"$facet": {**_BASE_FACETS, **(extra or {})}}]
    docs = await db.audit_log.aggregate(pipeline).to_list(length=1)
    return docs[0] if docs else {}


def _bucket(rows: list[dict]) -> dict[str, int]:
    """`[{_id, n}]` → `{_id: n}`, dropping null keys."""
    return {r["_id"]: r["n"] for r in rows if r.get("_id")}


def _first_n(facet: dict, name: str) -> int:
    rows = facet.get(name) or []
    return rows[0]["n"] if rows else 0


def _trend(rows: list[dict], now: datetime, days: int) -> list[dict]:
    """Continuous daily series (no gaps) for a sparkline, oldest→newest. Capped at 90 bars."""
    counts = {r["_id"]: r["n"] for r in rows}
    out: list[dict] = []
    for i in range(min(days, 90) - 1, -1, -1):
        d = (now - timedelta(days=i)).date().isoformat()
        out.append({"date": d, "count": counts.get(d, 0)})
    return out


def _retrieval(facet: dict) -> dict:
    rows = facet.get("retrieval") or []
    r = rows[0] if rows else {}
    lookups, hits = r.get("lookups", 0), r.get("hits", 0)
    return {"lookups": lookups, "hits": hits, "hitRate": round(hits / lookups, 3) if lookups else None}


@router.get("/usage")
async def usage(admin: PlatformAdmin, db: Db, days: int = Query(default=30, ge=1, le=365)) -> dict:
    """Platform-wide usage over the window: total agent actions, who's active (orgs, keys,
    distinct members of active orgs), the daily activity trend, retrieval hit-rate, and the
    top orgs / keys driving load."""
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=days)
    match = {"at": {"$gte": since}}

    facet = await _usage_facets(db, match, {
        "byOrg": [{"$group": {"_id": "$orgId", "n": {"$sum": 1}}}, {"$sort": {"n": -1}}, {"$limit": 10}],
        "byKey": [
            {"$match": {"keyId": {"$ne": None}}},
            {"$group": {"_id": "$keyId", "n": {"$sum": 1},
                        "keyName": {"$first": "$keyName"}, "orgId": {"$first": "$orgId"}}},
            {"$sort": {"n": -1}}, {"$limit": 10},
        ],
    })

    # Active counts: distinct ids in-window (bounded by #orgs/#keys), plus the members of
    # those orgs as a proxy for "active users" (no human attribution on the events).
    active_org_ids = await db.audit_log.distinct("orgId", match)
    active_key_ids = [k for k in await db.audit_log.distinct("keyId", match) if k]
    active_users = (
        len(await db.memberships.distinct("userId", {"orgId": {"$in": active_org_ids}, "teamId": None}))
        if active_org_ids else 0
    )

    top_orgs: list[dict] = []
    for row in facet.get("byOrg", []):
        org = await db.organizations.find_one({"_id": row["_id"]}, {"name": 1, "plan": 1})
        top_orgs.append({
            "orgId": row["_id"], "name": org["name"] if org else None,
            "plan": (org.get("plan", "free") if org else None), "actions": row["n"],
        })

    top_keys: list[dict] = []
    for row in facet.get("byKey", []):
        oid = row.get("orgId")
        org = await db.organizations.find_one({"_id": oid}, {"name": 1}) if oid else None
        top_keys.append({
            "keyId": row["_id"], "keyName": row.get("keyName"), "orgId": oid,
            "orgName": org["name"] if org else None, "actions": row["n"],
        })

    return {
        "days": days,
        "totals": {
            "actions": _first_n(facet, "total"),
            "activeOrgs": len(active_org_ids),
            "activeKeys": len(active_key_ids),
            "activeUsers": active_users,
        },
        "byAction": _bucket(facet.get("byAction", [])),
        "trend": _trend(facet.get("byDay", []), now, days),
        "retrieval": _retrieval(facet),
        "topOrgs": top_orgs,
        "topKeys": top_keys,
    }


# --- Users ---


def _user_row(user: dict, org_count: int) -> dict:
    return {
        "id": document_id(user),
        "email": user["email"],
        "name": user.get("name", ""),
        "isAdmin": is_platform_admin(user.get("email")),
        "emailVerified": bool(user.get("emailVerified")),
        "suspendedAt": user.get("suspendedAt"),
        "suspendedReason": user.get("suspendedReason"),
        "orgCount": org_count,
        "createdAt": user.get("createdAt"),
    }


@router.get("/users")
async def list_users(
    admin: PlatformAdmin,
    db: Db,
    q: str | None = Query(default=None, max_length=120),
    suspended: bool | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    skip: int = Query(default=0, ge=0),
) -> dict:
    query: dict = {}
    if q and q.strip():
        # case-insensitive substring on email or name. Escape the input so a crafted
        # pattern can't trigger catastrophic backtracking (ReDoS) over the collection.
        rx = {"$regex": re.escape(q.strip()), "$options": "i"}
        query["$or"] = [{"email": rx}, {"name": rx}]
    if suspended is True:
        query["suspendedAt"] = {"$ne": None}
    elif suspended is False:
        query["suspendedAt"] = None

    total = await db.users.count_documents(query)
    users: list[dict] = []
    async for u in db.users.find(query).sort("createdAt", -1).skip(skip).limit(limit):
        uid = document_id(u)
        org_count = await db.memberships.count_documents({"userId": uid, "teamId": None})
        users.append(_user_row(u, org_count))
    return {"users": users, "total": total, "skip": skip, "limit": limit}


@router.get("/users/{user_id}")
async def get_user(user_id: str, admin: PlatformAdmin, db: Db) -> dict:
    try:
        user = await db.users.find_one({"_id": ObjectId(user_id)})
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=404, detail="User not found") from exc
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    orgs: list[dict] = []
    async for m in db.memberships.find({"userId": user_id, "teamId": None}):
        org = await db.organizations.find_one({"_id": m["orgId"]})
        if org is None:
            continue
        orgs.append({
            "id": org["_id"],
            "name": org["name"],
            "role": m["role"],
            "plan": org.get("plan", "free"),
            "memories": await db.memories.count_documents({"orgId": org["_id"], "deletedAt": None}),
        })
    row = _user_row(user, len([o for o in orgs if o["role"] == "owner"]))
    row["orgs"] = orgs
    return row


@router.get("/users/{user_id}/usage")
async def user_usage(
    user_id: str, admin: PlatformAdmin, db: Db, days: int = Query(default=30, ge=1, le=365)
) -> dict:
    """One user's usage over the window. Agent activity is logged per org, not per human,
    so this is the aggregate of the orgs the user belongs to, broken down by action, day,
    org, and API key, with retrieval hit-rate. perOrg lists every membership (including
    orgs with zero activity); perKey is ranked by activity."""
    user = await _load_user(db, user_id)
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=days)

    roles: dict[str, str] = {}
    async for m in db.memberships.find({"userId": user_id, "teamId": None}):
        roles[m["orgId"]] = m["role"]
    org_ids = list(roles)
    match = {"orgId": {"$in": org_ids}, "at": {"$gte": since}}

    facet = await _usage_facets(db, match, {
        "byOrg": [{"$group": {"_id": "$orgId", "n": {"$sum": 1}}}],
        "byKey": [
            {"$match": {"keyId": {"$ne": None}}},
            {"$group": {"_id": "$keyId", "n": {"$sum": 1}, "orgId": {"$first": "$orgId"}}},
            {"$sort": {"n": -1}}, {"$limit": 25},
        ],
    })
    last_rows = facet.get("lastActive") or []
    active_key_ids = [k for k in await db.audit_log.distinct("keyId", match) if k]

    org_counts = {r["_id"]: r["n"] for r in facet.get("byOrg", [])}
    per_org: list[dict] = []
    for oid in org_ids:
        org = await db.organizations.find_one({"_id": oid}, {"name": 1, "plan": 1})
        per_org.append({
            "orgId": oid, "name": org["name"] if org else None,
            "plan": (org.get("plan", "free") if org else None),
            "role": roles.get(oid), "actions": org_counts.get(oid, 0),
        })
    per_org.sort(key=lambda o: o["actions"], reverse=True)

    per_key: list[dict] = []
    for row in facet.get("byKey", []):
        key = await db.api_keys.find_one(
            {"_id": row["_id"]}, {"name": 1, "prefix": 1, "revokedAt": 1, "lastUsedAt": 1, "orgId": 1}
        )
        oid = row.get("orgId") or (key.get("orgId") if key else None)
        org = await db.organizations.find_one({"_id": oid}, {"name": 1}) if oid else None
        per_key.append({
            "keyId": row["_id"], "keyName": (key.get("name") if key else None),
            "prefix": (key.get("prefix") if key else None), "orgId": oid,
            "orgName": org["name"] if org else None, "actions": row["n"],
            "lastUsedAt": (key.get("lastUsedAt") if key else None),
            "revoked": bool(key.get("revokedAt")) if key else False,
        })

    return {
        "userId": user_id,
        "email": user["email"],
        "name": user.get("name", ""),
        "days": days,
        "totals": {
            "actions": _first_n(facet, "total"),
            "activeKeys": len(active_key_ids),
            "lastActiveAt": (last_rows[0]["at"] if last_rows else None),
        },
        "byAction": _bucket(facet.get("byAction", [])),
        "trend": _trend(facet.get("byDay", []), now, days),
        "retrieval": _retrieval(facet),
        "perOrg": per_org,
        "perKey": per_key,
    }


def _require_not_admin(user: dict, action: str) -> None:
    if is_platform_admin(user.get("email")):
        raise HTTPException(status_code=400, detail=f"Cannot {action} a platform admin account.")


async def _load_user(db: AsyncIOMotorDatabase, user_id: str) -> dict:
    try:
        user = await db.users.find_one({"_id": ObjectId(user_id)})
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=404, detail="User not found") from exc
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.post("/users/{user_id}/suspend")
async def suspend_user(
    user_id: str, admin: PlatformAdmin, db: Db, request: Request, reason: str = Query(default="")
) -> dict:
    user = await _load_user(db, user_id)
    _require_not_admin(user, "suspend")
    now = datetime.now(timezone.utc)
    await db.users.update_one(
        {"_id": user["_id"]},
        {"$set": {"suspendedAt": now, "suspendedReason": reason.strip() or None, "updatedAt": now}},
    )
    # Kill active sessions immediately.
    await db.refresh_tokens.delete_many({"userId": user_id})
    await _log_action(db, admin, "user.suspend", request=request, targetUserId=user_id,
                      targetEmail=user["email"], reason=reason.strip() or None)
    return {"ok": True, "suspendedAt": now}


@router.post("/users/{user_id}/unsuspend")
async def unsuspend_user(user_id: str, admin: PlatformAdmin, db: Db, request: Request) -> dict:
    user = await _load_user(db, user_id)
    await db.users.update_one(
        {"_id": user["_id"]},
        {"$set": {"updatedAt": datetime.now(timezone.utc)}, "$unset": {"suspendedAt": "", "suspendedReason": ""}},
    )
    await _log_action(db, admin, "user.unsuspend", request=request, targetUserId=user_id,
                      targetEmail=user["email"])
    return {"ok": True}


@router.post("/users/{user_id}/verify")
async def verify_user(user_id: str, admin: PlatformAdmin, db: Db, request: Request) -> dict:
    """Manually mark a user's email verified, for support when delivery failed.
    The platform gates data access on verification (see `verified_user`), so this
    unblocks a legitimate user without them needing the email."""
    user = await _load_user(db, user_id)
    if user.get("emailVerified"):
        return {"ok": True, "alreadyVerified": True}
    await db.users.update_one(
        {"_id": user["_id"]},
        {"$set": {"emailVerified": True, "updatedAt": datetime.now(timezone.utc)}},
    )
    await _log_action(db, admin, "user.verify", request=request, targetUserId=user_id,
                      targetEmail=user["email"])
    return {"ok": True}


@router.delete("/users/{user_id}")
async def delete_user(user_id: str, admin: PlatformAdmin, db: Db, request: Request) -> dict:
    user = await _load_user(db, user_id)
    _require_not_admin(user, "delete")
    if user_id == _uid(admin):
        raise HTTPException(status_code=400, detail="You cannot delete your own account here.")
    counts = await run_atomic(db, lambda s: _delete_user(db, user_id, session=s))
    await _log_action(db, admin, "user.delete", request=request, targetUserId=user_id,
                      targetEmail=user["email"], removed=counts)
    return {"ok": True, "removed": counts}


# --- Organizations ---


@router.get("/orgs")
async def list_orgs(
    admin: PlatformAdmin,
    db: Db,
    q: str | None = Query(default=None, max_length=120),
    limit: int = Query(default=50, ge=1, le=200),
    skip: int = Query(default=0, ge=0),
) -> dict:
    query: dict = {}
    if q and q.strip():
        # Escape so a crafted pattern can't trigger ReDoS over the collection.
        query["name"] = {"$regex": re.escape(q.strip()), "$options": "i"}
    total = await db.organizations.count_documents(query)
    orgs: list[dict] = []
    async for o in db.organizations.find(query).sort("createdAt", -1).skip(skip).limit(limit):
        oid = o["_id"]
        # owner email (best-effort) for at-a-glance attribution
        owner_email = None
        owner_m = await db.memberships.find_one({"orgId": oid, "teamId": None, "role": "owner"})
        if owner_m is not None:
            try:
                owner = await db.users.find_one({"_id": ObjectId(owner_m["userId"])})
                owner_email = owner["email"] if owner else None
            except Exception:  # noqa: BLE001
                owner_email = None
        orgs.append({
            "id": oid,
            "name": o["name"],
            "slug": o.get("slug"),
            "plan": o.get("plan", "free"),
            "ownerEmail": owner_email,
            "members": await db.memberships.count_documents({"orgId": oid, "teamId": None}),
            "teams": await db.teams.count_documents({"orgId": oid}),
            "memories": await db.memories.count_documents({"orgId": oid, "deletedAt": None}),
            "apiKeys": await db.api_keys.count_documents({"orgId": oid, "revokedAt": None}),
            "createdAt": o.get("createdAt"),
        })
    return {"orgs": orgs, "total": total, "skip": skip, "limit": limit}


@router.get("/orgs/{org_id}")
async def get_org(org_id: str, admin: PlatformAdmin, db: Db) -> dict:
    """Drill into one org: its members, teams, API keys, and recent activity,
    so an admin can investigate before suspending, re-planning, or deleting."""
    org = await db.organizations.find_one({"_id": org_id})
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")

    members: list[dict] = []
    async for m in db.memberships.find({"orgId": org_id, "teamId": None}):
        try:
            u = await db.users.find_one({"_id": ObjectId(m["userId"])})
        except Exception:  # noqa: BLE001
            u = None
        members.append({
            "userId": m["userId"],
            "email": u["email"] if u else None,
            "name": (u.get("name", "") if u else ""),
            "role": m["role"],
            "suspended": bool(u.get("suspendedAt")) if u else False,
        })

    teams: list[dict] = []
    async for t in db.teams.find({"orgId": org_id}):
        teams.append({
            "id": t["_id"],
            "name": t["name"],
            "memories": await db.memories.count_documents({"teamId": t["_id"], "deletedAt": None}),
        })

    keys: list[dict] = []
    async for k in db.api_keys.find({"orgId": org_id}).sort("createdAt", -1):
        keys.append({
            "id": k["_id"],
            "name": k.get("name"),
            "prefix": k.get("prefix"),
            "scopes": k.get("scopes", []),
            "teamId": k.get("teamId"),
            "lastUsedAt": k.get("lastUsedAt"),
            "revokedAt": k.get("revokedAt"),
            "createdAt": k.get("createdAt"),
        })

    since = datetime.now(timezone.utc) - timedelta(days=30)
    return {
        "id": org["_id"],
        "name": org["name"],
        "slug": org.get("slug"),
        "plan": org.get("plan", "free"),
        "createdAt": org.get("createdAt"),
        "members": members,
        "teams": teams,
        "keys": keys,
        "activity30d": await db.audit_log.count_documents({"orgId": org_id, "at": {"$gte": since}}),
    }


@router.post("/orgs/{org_id}/plan")
async def set_org_plan(
    org_id: str, admin: PlatformAdmin, db: Db, request: Request, plan: str = Query(...)
) -> dict:
    """Change an org's plan. The Free-plan limits in orgs.py and folders.py read this
    field. It has no effect when SELF_HOSTED is on, since every org is then unlimited."""
    org = await db.organizations.find_one({"_id": org_id})
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    plan = plan.strip().lower()
    if plan not in ALLOWED_PLANS:
        raise HTTPException(status_code=400, detail=f"Plan must be one of: {', '.join(sorted(ALLOWED_PLANS))}")
    previous = org.get("plan", "free")
    await db.organizations.update_one(
        {"_id": org_id}, {"$set": {"plan": plan, "updatedAt": datetime.now(timezone.utc)}}
    )
    await _log_action(db, admin, "org.plan", request=request, targetOrgId=org_id,
                      targetOrgName=org["name"], reason=f"{previous} → {plan}")
    return {"ok": True, "plan": plan}


@router.post("/keys/{key_id}/revoke")
async def revoke_key(key_id: str, admin: PlatformAdmin, db: Db, request: Request) -> dict:
    """Kill a specific API key platform-wide, the action that closes the loop from the
    abuse panel (invalid_api_key signals) to actually stopping a misbehaving key."""
    key = await db.api_keys.find_one({"_id": key_id})
    if key is None:
        raise HTTPException(status_code=404, detail="API key not found")
    if key.get("revokedAt") is not None:
        return {"ok": True, "alreadyRevoked": True}
    await db.api_keys.update_one(
        {"_id": key_id}, {"$set": {"revokedAt": datetime.now(timezone.utc)}}
    )
    await _log_action(db, admin, "apikey.revoke", request=request, targetOrgId=key.get("orgId"),
                      reason=key.get("name"))
    return {"ok": True}


@router.delete("/orgs/{org_id}")
async def delete_org(org_id: str, admin: PlatformAdmin, db: Db, request: Request) -> dict:
    org = await db.organizations.find_one({"_id": org_id})
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    counts = await run_atomic(db, lambda s: _delete_org(db, org_id, session=s))
    await _log_action(db, admin, "org.delete", request=request, targetOrgId=org_id,
                      targetOrgName=org["name"], removed=counts)
    return {"ok": True, "removed": counts}


# --- Security / abuse panel ---


@router.get("/security")
async def security_events(
    admin: PlatformAdmin,
    db: Db,
    type: str | None = Query(default=None, max_length=64),
    severity: str | None = Query(default=None, max_length=16),
    limit: int = Query(default=100, ge=1, le=500),
    skip: int = Query(default=0, ge=0),
) -> dict:
    query: dict = {}
    if type:
        query["type"] = type
    if severity:
        query["severity"] = severity
    total = await db.security_events.count_documents(query)
    events: list[dict] = []
    async for e in db.security_events.find(query).sort("at", -1).skip(skip).limit(limit):
        events.append({
            "id": e["_id"],
            "type": e["type"],
            "severity": e.get("severity", "info"),
            "email": e.get("email"),
            "userId": e.get("userId"),
            "orgId": e.get("orgId"),
            "ip": e.get("ip"),
            "detail": e.get("detail"),
            "at": e.get("at"),
        })
    return {"events": events, "total": total, "skip": skip, "limit": limit}


@router.get("/actions")
async def admin_actions(
    admin: PlatformAdmin,
    db: Db,
    limit: int = Query(default=100, ge=1, le=500),
    skip: int = Query(default=0, ge=0),
) -> dict:
    total = await db.admin_actions.count_documents({})
    actions: list[dict] = []
    async for a in db.admin_actions.find({}).sort("at", -1).skip(skip).limit(limit):
        actions.append({
            "id": a["_id"],
            "action": a["action"],
            "adminEmail": a.get("adminEmail"),
            "targetEmail": a.get("targetEmail"),
            "targetUserId": a.get("targetUserId"),
            "targetOrgId": a.get("targetOrgId"),
            "targetOrgName": a.get("targetOrgName"),
            "reason": a.get("reason"),
            "removed": a.get("removed"),
            "at": a.get("at"),
        })
    return {"actions": actions, "total": total, "skip": skip, "limit": limit}
