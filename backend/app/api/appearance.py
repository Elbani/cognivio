from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel

from app.api.admin import _log_action
from app.api.deps import Db, PlatformAdmin

router = APIRouter(tags=["appearance"])

# What the SPA shows: which visual theme the auth pages and the workspace use. One platform-wide document, edited from the admin
# console, read by every visitor before the first screen renders.
SETTINGS_ID = "appearance"

# Themes the frontend knows how to render (frontend/src/styles/editorial.css and the
# auth frames in frontend/src/App.tsx). "terminal" is the original dark console look,
# "editorial" matches the "Read. Write. Know." landing page.
ALLOWED_THEMES = {"terminal", "editorial"}

DEFAULTS = {"userTheme": "editorial"}


class AppearanceUpdate(BaseModel):
    userTheme: str | None = None


async def load_appearance(db: AsyncIOMotorDatabase) -> dict:
    doc = await db.platform_settings.find_one({"_id": SETTINGS_ID}) or {}
    return {
        "userTheme": doc.get("userTheme", DEFAULTS["userTheme"]),
        "updatedAt": doc["updatedAt"].isoformat() if isinstance(doc.get("updatedAt"), datetime) else None,
        "updatedBy": doc.get("updatedBy"),
    }


@router.get("/api/appearance")
async def get_appearance(db: Db) -> dict:
    """Public: the SPA calls this on load, before anyone is signed in."""
    return await load_appearance(db)


@router.put("/api/admin/appearance")
async def update_appearance(
    payload: AppearanceUpdate, admin: PlatformAdmin, db: Db, request: Request
) -> dict:
    """Platform admins pick the user theme for everyone."""
    changes: dict = {}
    if payload.userTheme is not None:
        theme = payload.userTheme.strip().lower()
        if theme not in ALLOWED_THEMES:
            raise HTTPException(
                status_code=400,
                detail=f"Theme must be one of: {', '.join(sorted(ALLOWED_THEMES))}",
            )
        changes["userTheme"] = theme
    if not changes:
        raise HTTPException(status_code=400, detail="Nothing to change")

    before = await load_appearance(db)
    await db.platform_settings.update_one(
        {"_id": SETTINGS_ID},
        {"$set": {**changes, "updatedAt": datetime.now(timezone.utc), "updatedBy": admin.get("email")}},
        upsert=True,
    )
    after = await load_appearance(db)
    diff = ", ".join(f"{k}: {before[k]} to {after[k]}" for k in changes if before[k] != after[k]) or "no change"
    await _log_action(db, admin, "appearance.update", request=request, reason=diff)
    return after
