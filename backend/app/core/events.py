from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from bson import ObjectId
from fastapi import Request
from motor.motor_asyncio import AsyncIOMotorDatabase

logger = logging.getLogger("app.security")

# Severity ranks for filtering/highlighting in the admin console.
SEVERITY_INFO = "info"
SEVERITY_WARN = "warn"
SEVERITY_CRITICAL = "critical"


def client_ip(request: Request | None) -> str | None:
    """Best-effort client IP, honoring the proxy's X-Forwarded-For."""
    if request is None:
        return None
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else None


async def log_security_event(
    db: AsyncIOMotorDatabase,
    event_type: str,
    *,
    severity: str = SEVERITY_INFO,
    email: str | None = None,
    user_id: str | None = None,
    org_id: str | None = None,
    request: Request | None = None,
    **detail: Any,
) -> None:
    """Record an abuse / suspicious-behavior signal for the admin security panel.
    Fail-safe: a logging failure must never break the request it's observing."""
    try:
        await db.security_events.insert_one(
            {
                "_id": str(ObjectId()),
                "type": event_type,
                "severity": severity,
                "email": (email or "").lower() or None,
                "userId": user_id,
                "orgId": org_id,
                "ip": client_ip(request),
                "userAgent": request.headers.get("user-agent") if request else None,
                "detail": detail or None,
                "at": datetime.now(timezone.utc),
            }
        )
    except Exception:  # noqa: BLE001 - telemetry must never break the caller
        logger.exception("Failed to record security event %s", event_type)
