from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Query

from app.api.deps import Db, OrgCtx
from app.models.enums import MemoryType

router = APIRouter(prefix="/api", tags=["insights"])

# A doc is "stale" once it hasn't been verified in this many days (matches the
# frontend STALE_DAYS so the workspace and Insights agree).
STALE_DAYS = 90

# Words too generic to tell two knowledge-gap queries apart.
_STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "is", "are",
    "how", "what", "where", "when", "why", "do", "does", "with", "this", "that",
    "add", "new", "use", "using", "make", "get", "set", "can", "it", "we",
}


def _signif(query: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", query.lower()) if len(w) >= 3 and w not in _STOPWORDS}


def _cluster_gaps(rows: list[dict], limit: int) -> list[dict]:
    """Greedily merge near-duplicate zero-result queries so the backlog shows
    distinct missing topics, not 12 rewordings of one. Two queries join the same
    cluster when their significant-word sets overlap a lot (Jaccard >= 0.5) or one
    is contained in the other."""
    clusters: list[dict] = []
    for row in sorted(rows, key=lambda r: r["missCount"], reverse=True):
        words = _signif(row["query"])
        placed = False
        for c in clusters:
            cw = c["words"]
            if not words or not cw:
                continue
            inter = len(words & cw)
            union = len(words | cw)
            if inter and (inter / union >= 0.5 or words <= cw or cw <= words):
                c["missCount"] += row["missCount"]
                c["words"] |= words
                if len(c["examples"]) < 3 and row["query"] not in c["examples"]:
                    c["examples"].append(row["query"])
                if row["lastAt"] and (c["lastAt"] is None or row["lastAt"] > c["lastAt"]):
                    c["lastAt"] = row["lastAt"]
                placed = True
                break
        if not placed:
            clusters.append({
                "query": row["query"],          # representative (highest-count member)
                "words": words,
                "missCount": row["missCount"],
                "examples": [row["query"]],
                "lastAt": row["lastAt"],
            })
    clusters.sort(key=lambda c: c["missCount"], reverse=True)
    out = []
    for c in clusters[:limit]:
        out.append({
            "query": c["query"],
            "missCount": c["missCount"],
            "examples": c["examples"],
            "lastAt": c["lastAt"].isoformat() if isinstance(c["lastAt"], datetime) else c["lastAt"],
        })
    return out


@router.get("/orgs/{org_id}/insights")
async def org_insights(
    ctx: OrgCtx,
    db: Db,
    days: int = Query(default=30, ge=1, le=365),
    gapLimit: int = Query(default=10, ge=1, le=50),
    docLimit: int = Query(default=8, ge=1, le=50),
) -> dict:
    """One dashboard payload for the org: knowledge-base COVERAGE (how much exists,
    how much is stale, which teams lack a map), the GAP backlog (clustered zero-result
    agent searches = docs worth writing), recent agent ACTIVITY (what agents are
    actually doing), and per-doc USAGE (which docs agents actually read vs. dead docs
    never read). Drives the Insights view."""
    org_id = ctx.org_id
    now = datetime.now(timezone.utc)
    stale_cutoff = now - timedelta(days=STALE_DAYS)
    since = now - timedelta(days=days)

    # --- Coverage ---
    active = {"orgId": org_id, "deletedAt": None}
    docs_total = await db.memories.count_documents(active)
    teams_total = await db.teams.count_documents({"orgId": org_id})
    teams_with_map = len(
        await db.memories.distinct("teamId", {**active, "type": MemoryType.map.value})
    )
    stale = await db.memories.count_documents(
        {**active, "$or": [{"lastVerifiedAt": None}, {"lastVerifiedAt": {"$lt": stale_cutoff}}]}
    )
    by_type: dict[str, int] = {}
    async for grp in db.memories.aggregate(
        [{"$match": active}, {"$group": {"_id": "$type", "n": {"$sum": 1}}}]
    ):
        by_type[grp["_id"] or "note"] = grp["n"]

    # --- Gaps (clustered zero-result lookups) ---
    gap_rows: dict[str, dict] = {}
    async for e in db.audit_log.find(
        {
            "orgId": org_id,
            "action": {"$in": ["memory.search", "context.pack"]},
            "resultCount": 0,
            "at": {"$gte": since},
        }
    ):
        key = " ".join(str(e.get("query") or "").lower().split())
        if not key:
            continue
        row = gap_rows.setdefault(key, {"query": key, "missCount": 0, "lastAt": None})
        row["missCount"] += 1
        at = e.get("at")
        if at and (row["lastAt"] is None or at > row["lastAt"]):
            row["lastAt"] = at
    gaps = _cluster_gaps(list(gap_rows.values()), gapLimit)

    # --- Activity ---
    by_action: dict[str, int] = {}
    total_events = 0
    async for grp in db.audit_log.aggregate(
        [
            {"$match": {"orgId": org_id, "at": {"$gte": since}}},
            {"$group": {"_id": "$action", "n": {"$sum": 1}}},
        ]
    ):
        by_action[grp["_id"] or "?"] = grp["n"]
        total_events += grp["n"]
    active_keys = len(
        [
            n
            for n in await db.audit_log.distinct(
                "keyName", {"orgId": org_id, "actor": "agent", "at": {"$gte": since}}
            )
            if n
        ]
    )
    reads = sum(by_action.get(a, 0) for a in ("context.pack", "map.read", "memory.search", "memory.read"))
    writes = sum(by_action.get(a, 0) for a in ("memory.create", "memory.update", "memory.delete"))

    # --- Retrieval ROI: how often a lookup actually landed a doc ---
    # Every prime_context / search logs resultCount. hitRate = the share that returned at
    # least one doc, the headline "is the KB earning its keep?" number. A low rate means
    # agents keep coming up empty (cross-reference the gaps backlog).
    lookups = 0
    hits = 0
    async for grp in db.audit_log.aggregate([
        {"$match": {
            "orgId": org_id,
            "action": {"$in": ["context.pack", "memory.search"]},
            "at": {"$gte": since},
        }},
        {"$group": {"_id": {"$gt": ["$resultCount", 0]}, "n": {"$sum": 1}}},
    ]):
        lookups += grp["n"]
        if grp["_id"]:
            hits += grp["n"]
    hit_rate = round(hits / lookups, 3) if lookups else None

    # --- Doc usage (which docs agents actually pull in full) ---
    # memory.read = an agent called get_memory on a specific doc, the strongest signal a
    # doc earned its keep. Top reads (in-window) = most valuable; active docs never read
    # (all-time) = dead weight to fix or prune.
    read_counts: dict[str, int] = {}
    async for grp in db.audit_log.aggregate([
        {"$match": {"orgId": org_id, "action": "memory.read", "memoryId": {"$ne": None}, "at": {"$gte": since}}},
        {"$group": {"_id": "$memoryId", "n": {"$sum": 1}}},
    ]):
        if grp["_id"]:
            read_counts[grp["_id"]] = grp["n"]
    ever_read = set(await db.audit_log.distinct(
        "memoryId", {"orgId": org_id, "action": "memory.read", "memoryId": {"$ne": None}}
    ))

    top_ids = sorted(read_counts, key=lambda k: read_counts[k], reverse=True)[:docLimit]
    meta: dict[str, dict] = {}
    if top_ids:
        async for m in db.memories.find({"_id": {"$in": top_ids}}, {"title": 1, "type": 1, "deletedAt": 1}):
            meta[m["_id"]] = m
    top_read = [
        {
            "id": i, "title": meta[i]["title"], "type": meta[i].get("type", "note"),
            "reads": read_counts[i], "deleted": bool(meta[i].get("deletedAt")),
        }
        for i in top_ids if i in meta
    ]

    never_read: list[dict] = []
    never_read_count = 0
    async for m in db.memories.find(active, {"title": 1, "type": 1}):
        if m["_id"] not in ever_read:
            never_read_count += 1
            if len(never_read) < docLimit:
                never_read.append({"id": m["_id"], "title": m["title"], "type": m.get("type", "note")})

    # --- Usefulness (agent feedback via mark_helpful) ---
    # Net thumbs across the KB, plus the docs agents explicitly flagged as noise
    # (more 👎 than 👍), the strongest "fix or prune" signal, complementing never-read.
    helpful_total = 0
    not_helpful_total = 0
    rated_docs = 0
    async for grp in db.memories.aggregate([
        {"$match": active},
        {"$group": {
            "_id": None,
            "helpful": {"$sum": {"$ifNull": ["$helpfulCount", 0]}},
            "notHelpful": {"$sum": {"$ifNull": ["$notHelpfulCount", 0]}},
            "rated": {"$sum": {"$cond": [
                {"$gt": [{"$add": [{"$ifNull": ["$helpfulCount", 0]}, {"$ifNull": ["$notHelpfulCount", 0]}]}, 0]},
                1, 0,
            ]}},
        }},
    ]):
        helpful_total = grp["helpful"]
        not_helpful_total = grp["notHelpful"]
        rated_docs = grp["rated"]

    low_signal: list[dict] = []
    async for m in db.memories.find(
        {**active, "notHelpfulCount": {"$gt": 0}, "$expr": {"$gt": ["$notHelpfulCount", {"$ifNull": ["$helpfulCount", 0]}]}},
        {"title": 1, "type": 1, "helpfulCount": 1, "notHelpfulCount": 1},
    ).sort("notHelpfulCount", -1).limit(docLimit):
        low_signal.append({
            "id": m["_id"], "title": m["title"], "type": m.get("type", "note"),
            "helpful": m.get("helpfulCount", 0), "notHelpful": m.get("notHelpfulCount", 0),
        })

    return {
        "coverage": {
            "docs": docs_total,
            "teams": teams_total,
            "teamsWithMap": teams_with_map,
            "stale": stale,
            "byType": by_type,
        },
        "gaps": gaps,
        "activity": {
            "days": days,
            "totalEvents": total_events,
            "byAction": by_action,
            "activeKeys": active_keys,
            "reads": reads,
            "writes": writes,
        },
        "retrieval": {
            "lookups": lookups,
            "hits": hits,
            "hitRate": hit_rate,
        },
        "usefulness": {
            "helpful": helpful_total,
            "notHelpful": not_helpful_total,
            "ratedDocs": rated_docs,
            "lowSignal": low_signal,
        },
        "docs": {
            "topRead": top_read,
            "neverRead": never_read,
            "neverReadCount": never_read_count,
        },
    }
