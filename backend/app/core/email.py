"""Transactional email via Resend.

A thin async client over Resend's REST API plus a few branded templates. Sends are
**fail-safe**: if `RESEND_API_KEY` is unset (local/dev/tests) or Resend errors, the
call logs and returns False, it never raises, so email can't break the request that
triggered it. Call from a FastAPI BackgroundTask so it runs after the response.
"""

from __future__ import annotations

import logging

from html import escape

import httpx

from app.core.config import settings

logger = logging.getLogger("app.email")

_RESEND_URL = "https://api.resend.com/emails"


async def send_email(to: str, subject: str, html: str) -> bool:
    if not settings.resend_api_key:
        logger.info("email skipped (RESEND_API_KEY unset): '%s' -> %s", subject, to)
        return False
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                _RESEND_URL,
                headers={"Authorization": f"Bearer {settings.resend_api_key}"},
                json={"from": settings.email_from, "to": [to], "subject": subject, "html": html},
            )
        if resp.status_code >= 400:
            logger.warning("Resend %s sending '%s' to %s: %s", resp.status_code, subject, to, resp.text[:300])
            return False
        return True
    except Exception as exc:  # noqa: BLE001 - email must never break the caller
        logger.warning("email send failed ('%s' to %s): %s", subject, to, exc)
        return False


# --- Templates (inline-styled, email-client-safe) ---

_ACCENT = "#3ddc84"


def _shell(body: str) -> str:
    return (
        '<div style="font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;'
        'max-width:480px;margin:0 auto;padding:8px 4px;color:#1f2933;line-height:1.6">'
        f'<div style="font-weight:700;font-size:18px;color:{_ACCENT};margin-bottom:18px">cognivio</div>'
        f"{body}"
        '<p style="color:#8a98a8;font-size:12px;margin-top:30px;border-top:1px solid #eceff2;padding-top:14px">'
        "Cognivio: the memory layer for your AI agents.</p></div>"
    )


def _button(url: str, label: str) -> str:
    if not url:
        return ""
    return (
        f'<p style="margin:22px 0"><a href="{url}" '
        f'style="background:{_ACCENT};color:#06140c;text-decoration:none;font-weight:600;'
        f'padding:11px 20px;border-radius:8px;display:inline-block">{label}</a></p>'
    )


def _app_link(path: str) -> str:
    base = settings.public_url.rstrip("/")
    return f"{base}{path}" if base else ""


async def send_verification(to: str, name: str, verify_url: str) -> bool:
    who = escape((name or "there").strip())
    body = (
        f"<p>Hi {who},</p>"
        "<p>Thanks for signing up for Cognivio. Confirm your email to activate your account "
        "and start using the platform.</p>"
        + _button(verify_url, "Verify email")
        + '<p style="color:#8a98a8;font-size:13px">If you didn\'t create this account, you can '
        "ignore this email.</p>"
    )
    return await send_email(to, "Verify your email for Cognivio", _shell(body))


async def send_welcome(to: str, name: str) -> bool:
    who = escape((name or "there").strip())
    body = (
        f"<p>Hi {who},</p>"
        "<p>Welcome to Cognivio, a knowledge base your AI coding agents read before they act, "
        "and write back to as they learn.</p>"
        "<p>To get going: create a Project Map and a few docs, then connect your coding tool "
        "(Claude Code, Cursor, or Codex) under <b>Agents → Connect a tool</b>.</p>"
        + _button(_app_link("/app"), "Open Cognivio")
    )
    return await send_email(to, "Welcome to Cognivio", _shell(body))


async def send_member_added(to: str, org_name: str, inviter_name: str | None = None) -> bool:
    by = f" by {escape(inviter_name)}" if inviter_name else ""
    body = (
        f"<p>You've been added{by} to the <b>{escape(org_name)}</b> organization on Cognivio.</p>"
        "<p>You can now read and contribute to your team's knowledge base.</p>"
        + _button(_app_link("/app"), "Open Cognivio")
    )
    return await send_email(to, f"You've been added to {org_name} on Cognivio", _shell(body))


async def send_password_reset(to: str, name: str, reset_url: str) -> bool:
    who = escape((name or "there").strip())
    body = (
        f"<p>Hi {who},</p>"
        "<p>We received a request to reset your Cognivio password. This link expires in 1 hour "
        "and can be used once.</p>"
        + _button(reset_url, "Reset password")
        + '<p style="color:#8a98a8;font-size:13px">If you didn\'t request this, you can safely '
        "ignore this email, your password won't change.</p>"
    )
    return await send_email(to, "Reset your Cognivio password", _shell(body))


async def send_password_changed(to: str, name: str) -> bool:
    who = escape((name or "there").strip())
    body = (
        f"<p>Hi {who},</p>"
        "<p>Your Cognivio password was just changed. If this was you, no action is needed.</p>"
        "<p>If you didn't change it, reset your password and review your account right away.</p>"
    )
    return await send_email(to, "Your Cognivio password was changed", _shell(body))
