import logging
import os
import secrets
from datetime import datetime, timedelta, timezone

from bson import ObjectId
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, Response, status
from pymongo.errors import DuplicateKeyError
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.api.deps import CurrentUser, Db
from app.api.orgs import create_org_with_owner
from app.core.config import is_platform_admin, settings
from app.core.events import SEVERITY_WARN, log_security_event
from app.core.email import (
    send_password_changed,
    send_password_reset,
    send_verification,
    send_welcome,
)
from app.core.security import create_access_token, hash_api_key, hash_password, verify_password
from app.models.schemas import (
    EmailVerify,
    LoginRequest,
    PasswordChange,
    PasswordResetConfirm,
    PasswordResetRequest,
    ProfileUpdate,
    TokenResponse,
    UserCreate,
    UserOut,
    document_id,
)

logger = logging.getLogger("app.auth")

router = APIRouter(prefix="/api/auth", tags=["auth"])

limiter = Limiter(key_func=get_remote_address, enabled=not bool(os.getenv("TESTING")))


def user_out(user: dict) -> UserOut:
    return UserOut(
        id=document_id(user),
        email=user["email"],
        name=user["name"],
        emailVerified=bool(user.get("emailVerified")),
        isAdmin=is_platform_admin(user.get("email")),
    )


VERIFY_TTL_HOURS = 24 * 7


def _abs_base(request: Request) -> str:
    """Absolute base URL for email links: PUBLIC_URL if set (the reliable prod value
    behind a proxy), otherwise the host the request actually came in on."""
    return (settings.public_url or str(request.base_url)).rstrip("/")


def _verify_link(request: Request, token: str) -> str:
    return f"{_abs_base(request)}/verify-email?token={token}"


def _reset_link(request: Request, token: str) -> str:
    return f"{_abs_base(request)}/reset-password?token={token}"


async def _issue_verification(db, user: dict, request: Request) -> str:
    """Create a single-use email-verification token (returns the raw token to email)."""
    raw = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    await db.email_verifications.insert_one(
        {
            "_id": str(ObjectId()),
            "userId": document_id(user),
            "tokenHash": hash_api_key(raw),
            "expiresAt": now + timedelta(hours=VERIFY_TTL_HOURS),
            "usedAt": None,
            "createdAt": now,
        }
    )
    if not settings.resend_api_key:  # dev convenience: no email configured → log the link
        logger.info("Email disabled, verify link for %s: %s", user["email"], _verify_link(request, raw))
    return raw


def token_response(user: dict) -> TokenResponse:
    return TokenResponse(accessToken=create_access_token(document_id(user)), user=user_out(user))


REFRESH_COOKIE = "cognivio_refresh"


async def _issue_refresh(db, user: dict) -> str:
    """Mint a long-lived refresh token (stored hashed) and return the raw value."""
    raw = secrets.token_urlsafe(48)
    now = datetime.now(timezone.utc)
    await db.refresh_tokens.insert_one(
        {
            "_id": str(ObjectId()),
            "userId": document_id(user),
            "tokenHash": hash_api_key(raw),
            "expiresAt": now + timedelta(days=settings.refresh_token_days),
            "createdAt": now,
        }
    )
    return raw


def _set_refresh_cookie(response: Response, raw: str) -> None:
    response.set_cookie(
        REFRESH_COOKIE,
        raw,
        max_age=settings.refresh_token_days * 24 * 3600,
        httponly=True,
        samesite="lax",
        secure=settings.public_url.startswith("https"),
        path="/api/auth",
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(REFRESH_COOKIE, path="/api/auth")


async def _start_session(db, response: Response, user: dict) -> TokenResponse:
    """Issue an access token (body) + set the refresh-token cookie (durable session)."""
    raw = await _issue_refresh(db, user)
    _set_refresh_cookie(response, raw)
    return token_response(user)


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("5/minute")
async def register(request: Request, response: Response, payload: UserCreate, db: Db, background_tasks: BackgroundTasks) -> TokenResponse:
    now = datetime.now(timezone.utc)
    user = {
        "email": payload.email.lower(),
        "name": payload.name.strip(),
        "passwordHash": hash_password(payload.password),
        # No email provider means no verification link can be sent, so a new account
        # would be locked out forever. Treat it as verified instead.
        "emailVerified": not settings.email_enabled,
        "createdAt": now,
        "updatedAt": now,
    }

    try:
        result = await db.users.insert_one(user)
    except DuplicateKeyError as exc:
        logger.warning("Duplicate registration attempt for %s", payload.email.lower())
        raise HTTPException(
            status_code=400, detail="Registration failed"
        ) from exc

    user["_id"] = result.inserted_id
    await create_org_with_owner(db, document_id(user), f"{payload.name.strip()}'s Org")
    logger.info("New user registered: %s", payload.email.lower())
    raw = await _issue_verification(db, user, request)
    background_tasks.add_task(send_verification, user["email"], user["name"], _verify_link(request, raw))

    return await _start_session(db, response, user)


@router.post("/login", response_model=TokenResponse)
@limiter.limit("10/minute")
async def login(request: Request, response: Response, payload: LoginRequest, db: Db) -> TokenResponse:
    user = await db.users.find_one({"email": payload.email.lower()})
    if user is None or not verify_password(payload.password, user["passwordHash"]):
        logger.warning("Failed login attempt for %s", payload.email.lower())
        await log_security_event(
            db, "failed_login", severity=SEVERITY_WARN, email=payload.email, request=request
        )
        raise HTTPException(status_code=401, detail="Invalid email or password")

    if user.get("suspendedAt") is not None:
        await log_security_event(
            db, "suspended_login_attempt", severity=SEVERITY_WARN,
            email=user["email"], user_id=document_id(user), request=request,
        )
        raise HTTPException(status_code=403, detail="This account has been suspended.")

    return await _start_session(db, response, user)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(request: Request, response: Response, db: Db) -> TokenResponse:
    """Mint a fresh access token from the refresh-token cookie and slide its expiry.
    The durable session: the SPA calls this on load, on a timer, and on focus."""
    raw = request.cookies.get(REFRESH_COOKIE)
    if not raw:
        raise HTTPException(status_code=401, detail="No session")
    now = datetime.now(timezone.utc)
    rec = await db.refresh_tokens.find_one({"tokenHash": hash_api_key(raw)})
    expires = rec.get("expiresAt") if rec else None
    if expires is not None and expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if rec is None or expires is None or expires <= now:
        _clear_refresh_cookie(response)
        raise HTTPException(status_code=401, detail="Session expired")
    try:
        user = await db.users.find_one({"_id": ObjectId(rec["userId"])})
    except Exception:  # noqa: BLE001
        user = None
    if user is None:
        _clear_refresh_cookie(response)
        raise HTTPException(status_code=401, detail="Session expired")

    # A suspended account can't ride an existing session: kill the refresh token too.
    if user.get("suspendedAt") is not None:
        await db.refresh_tokens.delete_one({"_id": rec["_id"]})
        _clear_refresh_cookie(response)
        raise HTTPException(status_code=403, detail="This account has been suspended.")

    # slide the expiry forward (both server record and the browser cookie)
    await db.refresh_tokens.update_one(
        {"_id": rec["_id"]},
        {"$set": {"expiresAt": now + timedelta(days=settings.refresh_token_days)}},
    )
    _set_refresh_cookie(response, raw)
    return token_response(user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: Request, response: Response, db: Db) -> None:
    raw = request.cookies.get(REFRESH_COOKIE)
    if raw:
        await db.refresh_tokens.delete_one({"tokenHash": hash_api_key(raw)})
    _clear_refresh_cookie(response)


@router.get("/me", response_model=UserOut)
async def me(user: CurrentUser) -> UserOut:
    return user_out(user)


@router.patch("/me", response_model=UserOut)
async def update_me(payload: ProfileUpdate, user: CurrentUser, db: Db) -> UserOut:
    name = payload.name.strip()
    await db.users.update_one(
        {"_id": user["_id"]},
        {"$set": {"name": name, "updatedAt": datetime.now(timezone.utc)}},
    )
    user["name"] = name
    return user_out(user)


@router.post("/password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    payload: PasswordChange, user: CurrentUser, db: Db, background_tasks: BackgroundTasks
) -> None:
    if not verify_password(payload.currentPassword, user["passwordHash"]):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    await db.users.update_one(
        {"_id": user["_id"]},
        {
            "$set": {
                "passwordHash": hash_password(payload.newPassword),
                "updatedAt": datetime.now(timezone.utc),
            }
        },
    )
    background_tasks.add_task(send_password_changed, user["email"], user.get("name", ""))


RESET_TTL_MINUTES = 60


@router.post("/forgot-password", status_code=status.HTTP_200_OK)
@limiter.limit("5/minute")
async def forgot_password(
    request: Request, payload: PasswordResetRequest, db: Db, background_tasks: BackgroundTasks
) -> dict:
    """Email a one-time reset link. Always responds identically so it can't be used to
    probe which emails have accounts."""
    user = await db.users.find_one({"email": payload.email.lower()})
    if user is not None:
        raw = secrets.token_urlsafe(32)
        now = datetime.now(timezone.utc)
        await db.password_resets.insert_one(
            {
                "_id": str(ObjectId()),
                "userId": document_id(user),
                "tokenHash": hash_api_key(raw),
                "expiresAt": now + timedelta(minutes=RESET_TTL_MINUTES),
                "usedAt": None,
                "createdAt": now,
            }
        )
        background_tasks.add_task(send_password_reset, user["email"], user.get("name", ""), _reset_link(request, raw))
        logger.info("Password reset requested: %s", user["email"])
        if not settings.resend_api_key:  # dev convenience when email isn't configured
            logger.info("Email disabled, reset link for %s: %s", user["email"], _reset_link(request, raw))
    return {"ok": True}


@router.post("/reset-password", status_code=status.HTTP_200_OK)
@limiter.limit("10/minute")
async def reset_password(
    request: Request, payload: PasswordResetConfirm, db: Db, background_tasks: BackgroundTasks
) -> dict:
    now = datetime.now(timezone.utc)
    rec = await db.password_resets.find_one({"tokenHash": hash_api_key(payload.token), "usedAt": None})
    expires = rec.get("expiresAt") if rec else None
    if expires is not None and expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if rec is None or expires is None or expires <= now:
        raise HTTPException(status_code=400, detail="This reset link is invalid or has expired.")
    try:
        user = await db.users.find_one({"_id": ObjectId(rec["userId"])})
    except Exception:  # noqa: BLE001 - malformed id → treat as invalid token
        user = None
    if user is None:
        raise HTTPException(status_code=400, detail="This reset link is invalid or has expired.")

    await db.users.update_one(
        {"_id": user["_id"]},
        {"$set": {"passwordHash": hash_password(payload.newPassword), "updatedAt": now}},
    )
    # single-use: consume this token and invalidate any others outstanding for the user
    await db.password_resets.update_many(
        {"userId": rec["userId"], "usedAt": None}, {"$set": {"usedAt": now}}
    )
    background_tasks.add_task(send_password_changed, user["email"], user.get("name", ""))
    logger.info("Password reset completed: %s", user["email"])

    return {"ok": True}


@router.post("/verify-email", status_code=status.HTTP_200_OK)
@limiter.limit("20/minute")
async def verify_email(
    request: Request, payload: EmailVerify, db: Db, background_tasks: BackgroundTasks
) -> dict:
    now = datetime.now(timezone.utc)
    rec = await db.email_verifications.find_one({"tokenHash": hash_api_key(payload.token), "usedAt": None})
    expires = rec.get("expiresAt") if rec else None
    if expires is not None and expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if rec is None or expires is None or expires <= now:
        raise HTTPException(status_code=400, detail="This verification link is invalid or has expired.")
    try:
        user = await db.users.find_one({"_id": ObjectId(rec["userId"])})
    except Exception:  # noqa: BLE001
        user = None
    if user is None:
        raise HTTPException(status_code=400, detail="This verification link is invalid or has expired.")

    already = bool(user.get("emailVerified"))
    await db.users.update_one(
        {"_id": user["_id"]}, {"$set": {"emailVerified": True, "updatedAt": now}}
    )
    await db.email_verifications.update_many(
        {"userId": rec["userId"], "usedAt": None}, {"$set": {"usedAt": now}}
    )
    if not already:
        background_tasks.add_task(send_welcome, user["email"], user.get("name", ""))
        logger.info("Email verified: %s", user["email"])

    return {"ok": True}


@router.post("/resend-verification", status_code=status.HTTP_200_OK)
@limiter.limit("3/minute")
async def resend_verification(
    request: Request, user: CurrentUser, db: Db, background_tasks: BackgroundTasks
) -> dict:
    """Re-send the verification email to the signed-in (but unverified) user."""
    if user.get("emailVerified"):
        return {"ok": True}
    raw = await _issue_verification(db, user, request)
    background_tasks.add_task(send_verification, user["email"], user.get("name", ""), _verify_link(request, raw))
    return {"ok": True}
