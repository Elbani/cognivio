"""Single sign-on with OpenID Connect.

An organization's SSO settings live on the org document under `sso` and are set by a
platform admin (ADMIN_EMAILS), never by the org's own admins. The settings claim email
domains, and a sign-in is only accepted for an address in a claimed domain. Whoever
controls the identity provider can sign in as any address in those domains, so the
platform admin is the one who vouches that the org owns them.
"""
from __future__ import annotations

import logging
import re
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from bson import ObjectId
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from pymongo.errors import DuplicateKeyError
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.api import auth as auth_api
from app.api.deps import Db, PlatformAdmin
from app.core import oidc
from app.core.config import settings
from app.core.events import SEVERITY_WARN, log_security_event
from app.core.security import decrypt_secret, encrypt_secret, hash_api_key, hash_password
from app.models.enums import Role
from app.models.schemas import document_id

logger = logging.getLogger("app.sso")

router = APIRouter(tags=["sso"])
limiter = auth_api.limiter

STATE_COOKIE = "cognivio_sso"
STATE_TTL_MINUTES = 10
_DOMAIN_RE = re.compile(r"^(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")


email_domain = auth_api.email_domain
sso_org_for_email = auth_api.sso_org_for_email


def _redirect_uri(request: Request) -> str:
    return f"{auth_api._abs_base(request)}/api/auth/sso/callback"


def _fail(code: str) -> RedirectResponse:
    """Back to the login page with a short error code the SPA turns into a message.
    Never echo provider or user input into the URL."""
    resp = RedirectResponse(f"/login?sso_error={quote(code)}", status_code=303)
    resp.delete_cookie(STATE_COOKIE, path="/api/auth/sso")
    return resp


# --- Sign-in flow ---


@router.get("/api/auth/sso/start")
@limiter.limit("20/minute")
async def sso_start(request: Request, db: Db, email: str = Query(max_length=320)) -> RedirectResponse:
    """Send the browser to the identity provider that owns this email's domain."""
    email = email.strip().lower()
    org = await sso_org_for_email(db, email)
    if org is None:
        return _fail("not_configured")
    sso = org["sso"]
    try:
        prov = await oidc.provider(sso["issuer"])
    except oidc.OidcError:
        logger.exception("SSO provider unavailable for org %s", org["_id"])
        return _fail("provider")

    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    verifier, challenge = oidc.new_pkce()
    now = datetime.now(timezone.utc)
    await db.sso_states.insert_one(
        {
            "_id": hash_api_key(state),
            "orgId": org["_id"],
            "nonce": nonce,
            "codeVerifier": verifier,
            "expiresAt": now + timedelta(minutes=STATE_TTL_MINUTES),
            "createdAt": now,
        }
    )
    url = oidc.authorization_url(
        prov["meta"], client_id=sso["clientId"], redirect_uri=_redirect_uri(request),
        state=state, nonce=nonce, code_challenge=challenge, login_hint=email,
    )
    resp = RedirectResponse(url, status_code=303)
    # Binds the sign-in to this browser: the callback only accepts a state that matches
    # the cookie, so nobody can finish a sign-in they started in a victim's browser.
    resp.set_cookie(
        STATE_COOKIE, state, max_age=STATE_TTL_MINUTES * 60, httponly=True, samesite="lax",
        secure=settings.public_url.startswith("https"), path="/api/auth/sso",
    )
    return resp


async def _sign_in_user(db, org: dict, claims: dict) -> tuple[dict | None, str | None]:
    """Find or create the account for verified ID token claims. Returns (user, error)."""
    sso = org["sso"]
    email = claims.get("email")
    if not isinstance(email, str) or "@" not in email:
        return None, "no_email"
    email = email.strip().lower()
    if email_domain(email) not in sso.get("domains", []):
        return None, "domain"
    if claims.get("email_verified") is False:
        return None, "unverified"

    now = datetime.now(timezone.utc)
    link = {"orgId": org["_id"], "issuer": sso["issuer"], "sub": str(claims["sub"]), "linkedAt": now}
    user = await db.users.find_one({"email": email})

    if user is None:
        name = claims.get("name") if isinstance(claims.get("name"), str) else ""
        user = {
            "email": email,
            "name": (name.strip() or email.split("@", 1)[0])[:120],
            # No usable password: the account signs in through the identity provider.
            "passwordHash": hash_password(secrets.token_urlsafe(32)),
            "emailVerified": True,
            "sso": link,
            "lastSsoAt": now,
            "createdAt": now,
            "updatedAt": now,
        }
        try:
            user["_id"] = (await db.users.insert_one(user)).inserted_id
        except DuplicateKeyError:
            return None, "retry"
        logger.info("New user provisioned through SSO: %s", email)
    else:
        if user.get("suspendedAt") is not None:
            return None, "suspended"
        existing = user.get("sso") or {}
        same_issuer = existing.get("issuer") == sso["issuer"]
        if same_issuer and existing.get("sub") != link["sub"]:
            # The provider now says a different person holds this address (for example a
            # reassigned mailbox). Do not hand them the old person's account.
            return None, "identity"
        update: dict = {"emailVerified": True, "lastSsoAt": now, "updatedAt": now}
        if not same_issuer:
            # First sign-in through this provider. Whoever made the account before may
            # not be the person the provider vouches for, so their password and
            # sessions stop working. A real owner can set a new password by email.
            update["sso"] = link
            update["passwordHash"] = hash_password(secrets.token_urlsafe(32))
            await db.refresh_tokens.delete_many({"userId": document_id(user)})
        await db.users.update_one({"_id": user["_id"]}, {"$set": update})
        user.update(update)

    user_id = document_id(user)
    if await db.memberships.find_one({"userId": user_id, "orgId": org["_id"]}) is None:
        try:
            await db.memberships.insert_one(
                {
                    "_id": str(ObjectId()),
                    "userId": user_id,
                    "orgId": org["_id"],
                    "teamId": None,
                    "role": sso.get("defaultRole", Role.editor.value),
                    "createdAt": now,
                }
            )
        except DuplicateKeyError:
            pass
    return user, None


@router.get("/api/auth/sso/callback")
@limiter.limit("30/minute")
async def sso_callback(
    request: Request, db: Db,
    code: str | None = Query(default=None, max_length=4096),
    state: str | None = Query(default=None, max_length=512),
    error: str | None = Query(default=None, max_length=512),
) -> RedirectResponse:
    cookie_state = request.cookies.get(STATE_COOKIE)
    if not state or not cookie_state or not secrets.compare_digest(state, cookie_state):
        return _fail("state")
    # Single use: the state is deleted as it is read.
    rec = await db.sso_states.find_one_and_delete({"_id": hash_api_key(state)})
    expires = rec.get("expiresAt") if rec else None
    if expires is not None and expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if rec is None or expires is None or expires <= datetime.now(timezone.utc):
        return _fail("state")
    if error or not code:
        return _fail("denied")

    org = await db.organizations.find_one({"_id": rec["orgId"]})
    sso = (org or {}).get("sso") or {}
    if org is None or not sso.get("enabled"):
        return _fail("not_configured")

    try:
        prov = await oidc.provider(sso["issuer"])
        id_token = await oidc.exchange_code(
            prov["meta"], client_id=sso["clientId"],
            client_secret=decrypt_secret(sso.get("clientSecret", "")),
            code=code, redirect_uri=_redirect_uri(request), code_verifier=rec["codeVerifier"],
        )
        claims = await oidc.verify_id_token(
            sso["issuer"], id_token, client_id=sso["clientId"], nonce=rec["nonce"]
        )
    except oidc.OidcError as exc:
        await log_security_event(
            db, "sso_login_failed", severity=SEVERITY_WARN, org_id=org["_id"],
            request=request, reason=str(exc),
        )
        return _fail("provider")

    user, problem = await _sign_in_user(db, org, claims)
    if user is None:
        await log_security_event(
            db, "sso_login_failed", severity=SEVERITY_WARN, org_id=org["_id"],
            email=claims.get("email") if isinstance(claims.get("email"), str) else None,
            request=request, reason=problem,
        )
        return _fail(problem or "provider")

    resp = RedirectResponse("/app", status_code=303)
    # An SSO session has a hard end: after it the person must pass the identity provider
    # again, which is what removes someone the provider has deactivated.
    lifetime = timedelta(hours=settings.sso_session_hours)
    raw = await auth_api._issue_refresh(db, user, sso_org_id=org["_id"], lifetime=lifetime)
    auth_api._set_refresh_cookie(resp, raw, max_age=int(lifetime.total_seconds()))
    resp.delete_cookie(STATE_COOKIE, path="/api/auth/sso")
    return resp


# --- Settings (platform admin) ---


class SsoSettingsIn(BaseModel):
    issuer: str = Field(min_length=8, max_length=500)
    clientId: str = Field(min_length=1, max_length=500)
    # Omit to keep the stored secret when editing other fields.
    clientSecret: str | None = Field(default=None, min_length=1, max_length=2000)
    domains: list[str] = Field(min_length=1, max_length=50)
    enabled: bool = True
    required: bool = False
    defaultRole: Role = Role.editor


def _settings_out(org: dict, request: Request) -> dict:
    sso = org.get("sso") or {}
    return {
        "configured": bool(sso),
        "enabled": bool(sso.get("enabled")),
        "required": bool(sso.get("required")),
        "issuer": sso.get("issuer", ""),
        "clientId": sso.get("clientId", ""),
        "hasSecret": bool(sso.get("clientSecret")),
        "domains": sso.get("domains", []),
        "defaultRole": sso.get("defaultRole", Role.editor.value),
        # Register this exact URL with the identity provider.
        "redirectUri": _redirect_uri(request),
    }


async def _load_org(db, org_id: str) -> dict:
    org = await db.organizations.find_one({"_id": org_id})
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    return org


async def _log(db, admin: dict, action: str, org: dict, request: Request, **extra) -> None:
    await db.admin_actions.insert_one(
        {
            "_id": str(ObjectId()),
            "action": action,
            "adminId": document_id(admin),
            "adminEmail": admin.get("email"),
            "ip": request.client.host if request.client else None,
            "at": datetime.now(timezone.utc),
            "targetOrgId": org["_id"],
            "targetOrgName": org.get("name"),
            **extra,
        }
    )


@router.get("/api/admin/orgs/{org_id}/sso")
async def get_sso(org_id: str, admin: PlatformAdmin, db: Db, request: Request) -> dict:
    return _settings_out(await _load_org(db, org_id), request)


@router.put("/api/admin/orgs/{org_id}/sso")
async def put_sso(
    org_id: str, payload: SsoSettingsIn, admin: PlatformAdmin, db: Db, request: Request
) -> dict:
    org = await _load_org(db, org_id)
    current = org.get("sso") or {}

    domains = sorted({d.strip().lower().lstrip("@") for d in payload.domains if d.strip()})
    bad = [d for d in domains if not _DOMAIN_RE.match(d)]
    if not domains or bad:
        raise HTTPException(status_code=400, detail=f"Not a valid email domain: {', '.join(bad) or 'none given'}")
    taken = await db.organizations.find_one(
        {"_id": {"$ne": org_id}, "sso.domains": {"$in": domains}}
    )
    if taken is not None:
        raise HTTPException(status_code=409, detail="Another organization already claims one of these domains.")

    try:
        prov = await oidc.provider(payload.issuer, refresh=True)
    except oidc.OidcError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    secret = encrypt_secret(payload.clientSecret) if payload.clientSecret else current.get("clientSecret")
    if not secret:
        raise HTTPException(status_code=400, detail="A client secret is required.")

    sso = {
        # The provider's own spelling of its issuer, which is what ID tokens carry.
        "issuer": prov["meta"]["issuer"],
        "clientId": payload.clientId.strip(),
        "clientSecret": secret,
        "domains": domains,
        "enabled": payload.enabled,
        "required": payload.required,
        "defaultRole": payload.defaultRole.value,
        "updatedAt": datetime.now(timezone.utc),
    }
    try:
        await db.organizations.update_one(
            {"_id": org_id}, {"$set": {"sso": sso, "updatedAt": sso["updatedAt"]}}
        )
    except DuplicateKeyError as exc:
        raise HTTPException(status_code=409, detail="Another organization already claims one of these domains.") from exc
    await _log(db, admin, "org.sso", org, request,
               reason=f"{'on' if sso['enabled'] else 'off'}, {'required, ' if sso['required'] else ''}{', '.join(domains)}")
    org["sso"] = sso
    return _settings_out(org, request)


@router.delete("/api/admin/orgs/{org_id}/sso")
async def delete_sso(org_id: str, admin: PlatformAdmin, db: Db, request: Request) -> dict:
    org = await _load_org(db, org_id)
    await db.organizations.update_one(
        {"_id": org_id}, {"$unset": {"sso": ""}, "$set": {"updatedAt": datetime.now(timezone.utc)}}
    )
    await _log(db, admin, "org.sso", org, request, reason="removed")
    org.pop("sso", None)
    return _settings_out(org, request)
