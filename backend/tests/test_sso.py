from __future__ import annotations

import json
import secrets
import time
from urllib.parse import parse_qs, urlparse

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app.core import oidc
from app.core.config import settings

pytestmark = pytest.mark.asyncio

ISSUER = "https://idp.example.com"
CLIENT_ID = "cognivio-client"
ADMIN = "root@operatorco.io"


class FakeIdp:
    """Stands in for the identity provider's HTTP endpoints. Tokens are really signed
    and really verified, only the network is replaced."""

    def __init__(self) -> None:
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(self.key.public_key()))
        jwk.update({"kid": "k1", "use": "sig", "alg": "RS256"})
        self.jwks = {"keys": [jwk]}
        self.claims: dict = {}
        self.nonce: str | None = None
        self.token_calls: list[dict] = []
        self.forged_token: str | None = None

    def token(self, **overrides) -> str:
        now = int(time.time())
        claims = {
            "iss": ISSUER, "aud": CLIENT_ID, "sub": "idp-user-1", "iat": now, "exp": now + 300,
            "nonce": self.nonce, "email_verified": True, **self.claims, **overrides,
        }
        return jwt.encode(claims, self.key, algorithm="RS256", headers={"kid": "k1"})

    async def fetch_json(self, url: str) -> dict:
        if url.endswith("/.well-known/openid-configuration"):
            return {
                "issuer": ISSUER,
                "authorization_endpoint": f"{ISSUER}/authorize",
                "token_endpoint": f"{ISSUER}/token",
                "jwks_uri": f"{ISSUER}/jwks",
                "token_endpoint_auth_methods_supported": ["client_secret_post"],
            }
        assert url == f"{ISSUER}/jwks"
        return self.jwks

    async def post_form(self, url: str, data: dict, auth=None) -> dict:
        assert url == f"{ISSUER}/token"
        self.token_calls.append(data)
        return {"id_token": self.forged_token or self.token()}


@pytest.fixture
def idp(monkeypatch) -> FakeIdp:
    fake = FakeIdp()
    oidc._cache.clear()
    monkeypatch.setattr(oidc, "fetch_json", fake.fetch_json)
    monkeypatch.setattr(oidc, "post_form", fake.post_form)
    monkeypatch.setattr(settings, "admin_emails", ADMIN)
    monkeypatch.setattr(settings, "self_hosted", True)
    return fake


async def _register(client, email: str, name: str = "Sam") -> dict:
    r = await client.post(
        "/api/auth/register", json={"email": email, "password": "password123", "name": name}
    )
    assert r.status_code == 201, r.text
    client.cookies.clear()
    return {"id": r.json()["user"]["id"], "headers": {"Authorization": f"Bearer {r.json()['accessToken']}"}}


async def _org_with_sso(client, domain: str = "acmecorp.io", **settings_over) -> dict:
    """An org owned by a non-SSO account, with SSO set up by the platform admin."""
    admin = await _register(client, ADMIN, "Root")
    owner = await _register(client, f"owner_{secrets.token_hex(3)}@elsewhere.org", "Owner")
    org_id = (await client.get("/api/orgs", headers=owner["headers"])).json()[0]["id"]
    body = {"issuer": ISSUER, "clientId": CLIENT_ID, "clientSecret": "s3cret", "domains": [domain], **settings_over}
    r = await client.put(f"/api/admin/orgs/{org_id}/sso", json=body, headers=admin["headers"])
    assert r.status_code == 200, r.text
    return {"org_id": org_id, "owner": owner, "admin": admin}


async def _sso_login(client, idp: FakeIdp, email: str, **claims):
    client.cookies.clear()
    start = await client.get("/api/auth/sso/start", params={"email": email})
    assert start.status_code == 303
    query = parse_qs(urlparse(start.headers["location"]).query)
    idp.nonce = query["nonce"][0]
    idp.claims = {"email": email, "name": "Dana Dev", **claims}
    return await client.get("/api/auth/sso/callback", params={"code": "abc", "state": query["state"][0]})


async def test_sso_signs_in_and_provisions_a_member(client, idp, mongo_db) -> None:
    ws = await _org_with_sso(client)
    r = await _sso_login(client, idp, "dana@acmecorp.io")
    assert r.status_code == 303 and r.headers["location"] == "/app"
    assert idp.token_calls[0]["code_verifier"] and idp.token_calls[0]["client_secret"] == "s3cret"

    session = await client.post("/api/auth/refresh")
    assert session.status_code == 200, session.text
    assert session.json()["user"]["email"] == "dana@acmecorp.io"
    assert session.json()["user"]["emailVerified"] is True
    headers = {"Authorization": f"Bearer {session.json()['accessToken']}"}
    orgs = (await client.get("/api/orgs", headers=headers)).json()
    assert [o["id"] for o in orgs] == [ws["org_id"]]
    assert orgs[0]["role"] == "editor" and orgs[0]["ssoEnabled"] is True

    # The client secret is stored encrypted and never returned.
    stored = (await mongo_db.organizations.find_one({"_id": ws["org_id"]}))["sso"]["clientSecret"]
    assert stored != "s3cret"
    got = await client.get(f"/api/admin/orgs/{ws['org_id']}/sso", headers=ws["admin"]["headers"])
    assert "clientSecret" not in got.json() and got.json()["hasSecret"] is True


async def test_sso_session_has_a_hard_end(client, idp, mongo_db) -> None:
    await _org_with_sso(client)
    await _sso_login(client, idp, "dana@acmecorp.io")
    rec = await mongo_db.refresh_tokens.find_one({"ssoOrgId": {"$exists": True}})
    hard_end = rec["absoluteExpiresAt"]
    assert (await client.post("/api/auth/refresh")).status_code == 200
    after = await mongo_db.refresh_tokens.find_one({"_id": rec["_id"]})
    assert after["expiresAt"] <= hard_end  # refreshing never moves the end


async def test_only_platform_admin_can_configure_sso(client, idp) -> None:
    ws = await _org_with_sso(client)
    body = {"issuer": ISSUER, "clientId": "x", "clientSecret": "y", "domains": ["victimco.org"]}
    r = await client.put(f"/api/admin/orgs/{ws['org_id']}/sso", json=body, headers=ws["owner"]["headers"])
    assert r.status_code == 403


async def test_a_domain_belongs_to_one_org(client, idp) -> None:
    ws = await _org_with_sso(client)
    other = await _register(client, "second@elsewhere.org")
    other_org = (await client.get("/api/orgs", headers=other["headers"])).json()[0]["id"]
    body = {"issuer": ISSUER, "clientId": "x", "clientSecret": "y", "domains": ["acmecorp.io"]}
    r = await client.put(f"/api/admin/orgs/{other_org}/sso", json=body, headers=ws["admin"]["headers"])
    assert r.status_code == 409


async def test_email_outside_the_claimed_domains_is_refused(client, idp, mongo_db) -> None:
    """The provider asserts an address in a domain the org does not own."""
    await _org_with_sso(client)
    victim = await _register(client, "ceo@victimco.org")
    client.cookies.clear()
    start = await client.get("/api/auth/sso/start", params={"email": "dana@acmecorp.io"})
    query = parse_qs(urlparse(start.headers["location"]).query)
    idp.nonce = query["nonce"][0]
    idp.claims = {"email": "ceo@victimco.org"}
    r = await client.get("/api/auth/sso/callback", params={"code": "abc", "state": query["state"][0]})
    assert r.headers["location"] == "/login?sso_error=domain"
    assert (await client.post("/api/auth/refresh")).status_code == 401
    assert await mongo_db.memberships.count_documents({"userId": victim["id"]}) == 1


@pytest.mark.parametrize(
    "overrides",
    [{"aud": "someone-else"}, {"iss": "https://evil.example"}, {"nonce": "wrong"}, {"exp": 1}],
)
async def test_bad_id_token_claims_are_refused(client, idp, overrides) -> None:
    await _org_with_sso(client)
    client.cookies.clear()
    start = await client.get("/api/auth/sso/start", params={"email": "dana@acmecorp.io"})
    query = parse_qs(urlparse(start.headers["location"]).query)
    idp.nonce = query["nonce"][0]
    idp.claims = {"email": "dana@acmecorp.io"}
    idp.forged_token = idp.token(**overrides)
    r = await client.get("/api/auth/sso/callback", params={"code": "abc", "state": query["state"][0]})
    assert r.headers["location"] == "/login?sso_error=provider"
    assert (await client.post("/api/auth/refresh")).status_code == 401


async def test_token_signed_by_another_key_or_hs256_is_refused(client, idp) -> None:
    await _org_with_sso(client)
    now = int(time.time())
    for forged in ("other_key", "hs256"):
        client.cookies.clear()
        start = await client.get("/api/auth/sso/start", params={"email": "dana@acmecorp.io"})
        query = parse_qs(urlparse(start.headers["location"]).query)
        claims = {"iss": ISSUER, "aud": CLIENT_ID, "sub": "x", "iat": now, "exp": now + 300,
                  "nonce": query["nonce"][0], "email": "dana@acmecorp.io"}
        if forged == "other_key":
            other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            idp.forged_token = jwt.encode(claims, other, algorithm="RS256", headers={"kid": "k1"})
        else:
            idp.forged_token = jwt.encode(claims, "x" * 40, algorithm="HS256", headers={"kid": "k1"})
        r = await client.get("/api/auth/sso/callback", params={"code": "abc", "state": query["state"][0]})
        assert r.headers["location"] == "/login?sso_error=provider", forged


async def test_state_is_bound_to_the_browser_and_single_use(client, idp) -> None:
    await _org_with_sso(client)
    start = await client.get("/api/auth/sso/start", params={"email": "dana@acmecorp.io"})
    query = parse_qs(urlparse(start.headers["location"]).query)
    idp.nonce = query["nonce"][0]
    idp.claims = {"email": "dana@acmecorp.io"}
    state = query["state"][0]

    # Another browser (no state cookie) cannot finish the sign-in.
    saved = dict(client.cookies)
    client.cookies.clear()
    r = await client.get("/api/auth/sso/callback", params={"code": "abc", "state": state})
    assert r.headers["location"] == "/login?sso_error=state"

    for k, v in saved.items():
        client.cookies.set(k, v)
    ok = await client.get("/api/auth/sso/callback", params={"code": "abc", "state": state})
    assert ok.headers["location"] == "/app"
    client.cookies.set("cognivio_sso", state)
    replay = await client.get("/api/auth/sso/callback", params={"code": "abc", "state": state})
    assert replay.headers["location"] == "/login?sso_error=state"


async def test_required_sso_blocks_password_login_and_registration(client, idp) -> None:
    await _register(client, "early@acmecorp.io")  # registered before SSO existed
    await _org_with_sso(client, required=True)
    creds = {"email": "early@acmecorp.io", "password": "password123"}
    assert (await client.post("/api/auth/login", json=creds)).status_code == 403
    r = await client.post(
        "/api/auth/register", json={"email": "new@acmecorp.io", "password": "password123", "name": "N"}
    )
    assert r.status_code == 403
    # The platform admin keeps password login as the way back in.
    assert (await client.post("/api/auth/login", json={"email": ADMIN, "password": "password123"})).status_code == 200
    # Other domains are untouched.
    await _register(client, "free@elsewhere2.org")
    assert (await client.post("/api/auth/login", json={"email": "free@elsewhere2.org", "password": "password123"})).status_code == 200


async def test_first_sso_sign_in_retires_the_old_password_and_sessions(client, idp) -> None:
    """Someone registered the address with a password before SSO was set up. The person
    the provider vouches for takes the account, and the earlier password stops working."""
    r = await client.post(
        "/api/auth/register", json={"email": "dana@acmecorp.io", "password": "password123", "name": "Squatter"}
    )
    old_cookies = dict(client.cookies)
    await _org_with_sso(client)
    assert (await _sso_login(client, idp, "dana@acmecorp.io")).headers["location"] == "/app"

    client.cookies.clear()
    creds = {"email": "dana@acmecorp.io", "password": "password123"}
    assert (await client.post("/api/auth/login", json=creds)).status_code == 401
    for k, v in old_cookies.items():
        client.cookies.set(k, v)
    assert (await client.post("/api/auth/refresh")).status_code == 401
    client.cookies.clear()
    assert r.status_code == 201


async def test_same_email_with_a_different_subject_is_refused(client, idp) -> None:
    await _org_with_sso(client)
    assert (await _sso_login(client, idp, "dana@acmecorp.io")).headers["location"] == "/app"
    r = await _sso_login(client, idp, "dana@acmecorp.io", sub="a-different-person")
    assert r.headers["location"] == "/login?sso_error=identity"


async def test_unknown_domain_and_disabled_sso_do_not_start(client, idp) -> None:
    ws = await _org_with_sso(client)
    r = await client.get("/api/auth/sso/start", params={"email": "x@nowhereco.org"})
    assert r.headers["location"] == "/login?sso_error=not_configured"
    body = {"issuer": ISSUER, "clientId": CLIENT_ID, "domains": ["acmecorp.io"], "enabled": False}
    r = await client.put(f"/api/admin/orgs/{ws['org_id']}/sso", json=body, headers=ws["admin"]["headers"])
    assert r.status_code == 200 and r.json()["hasSecret"] is True  # secret kept when omitted
    r = await client.get("/api/auth/sso/start", params={"email": "dana@acmecorp.io"})
    assert r.headers["location"] == "/login?sso_error=not_configured"


async def test_issuer_must_be_https(client, idp) -> None:
    ws = await _org_with_sso(client)
    body = {"issuer": "http://idp.example.com", "clientId": "x", "clientSecret": "y", "domains": ["acmecorp.io"]}
    r = await client.put(f"/api/admin/orgs/{ws['org_id']}/sso", json=body, headers=ws["admin"]["headers"])
    assert r.status_code == 400


async def test_removing_a_member_revokes_the_keys_they_created(client, idp) -> None:
    ws = await _org_with_sso(client, defaultRole="admin")
    await _sso_login(client, idp, "dana@acmecorp.io")
    session = (await client.post("/api/auth/refresh")).json()
    dana = {"Authorization": f"Bearer {session['accessToken']}"}
    client.cookies.clear()
    keys = f"/api/orgs/{ws['org_id']}/keys"
    made = await client.post(keys, json={"name": "dana-laptop", "scopes": ["memory:read"]}, headers=dana)
    assert made.status_code == 201, made.text
    kept = await client.post(keys, json={"name": "ci", "scopes": ["memory:read"]}, headers=ws["owner"]["headers"])
    agent = {"Authorization": f"Bearer {made.json()['key']}"}
    assert (await client.get("/api/v1/teams", headers=agent)).status_code == 200

    r = await client.delete(f"/api/orgs/{ws['org_id']}/members/{session['user']['id']}", headers=ws["owner"]["headers"])
    assert r.status_code == 204
    assert (await client.get("/api/v1/teams", headers=agent)).status_code == 401
    assert (await client.get(f"/api/orgs/{ws['org_id']}", headers=dana)).status_code == 403
    other = {"Authorization": f"Bearer {kept.json()['key']}"}
    assert (await client.get("/api/v1/teams", headers=other)).status_code == 200
