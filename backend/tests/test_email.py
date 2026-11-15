from __future__ import annotations

import secrets

import pytest

from app.core import email as email_mod

pytestmark = pytest.mark.asyncio


async def test_send_email_noop_without_key(monkeypatch) -> None:
    """No API key configured → send is skipped and returns False, never raises."""
    monkeypatch.setattr(email_mod.settings, "resend_api_key", "")
    assert await email_mod.send_email("a@b.com", "Hi", "<p>x</p>") is False


async def test_register_fires_verification_email(client, monkeypatch, email_on) -> None:
    calls: list[tuple[str, str]] = []

    async def fake_verify(to: str, name: str, url: str) -> bool:
        calls.append((to, name))
        return True

    # add_task captures the module-level name, so patch it in the auth module.
    monkeypatch.setattr("app.api.auth.send_verification", fake_verify)
    email = f"verify_{secrets.token_hex(4)}@example.com"
    r = await client.post(
        "/api/auth/register", json={"email": email, "password": "password123", "name": "Wendy"}
    )
    assert r.status_code == 201, r.text
    # registration returns an account that is not yet verified
    assert r.json()["user"]["emailVerified"] is False
    # BackgroundTasks run before the ASGI response fully completes.
    assert calls == [(email, "Wendy")]


async def test_templates_render(monkeypatch) -> None:
    """The branded templates produce a subject + HTML and route through send_email."""
    sent: list[tuple[str, str, str]] = []

    async def capture(to: str, subject: str, html: str) -> bool:
        sent.append((to, subject, html))
        return True

    monkeypatch.setattr(email_mod, "send_email", capture)
    await email_mod.send_welcome("u@x.com", "Sam")
    await email_mod.send_member_added("u@x.com", "Acme", "Pat")
    await email_mod.send_password_changed("u@x.com", "Sam")
    assert [s[1] for s in sent] == [
        "Welcome to Cognivio",
        "You've been added to Acme on Cognivio",
        "Your Cognivio password was changed",
    ]
    assert all("cognivio" in html.lower() for _, _, html in sent)
