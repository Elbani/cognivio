"""OpenID Connect client for single sign-on (authorization code flow with PKCE).

The identity provider is trusted only as far as its signed ID token: the token's
signature, issuer, audience, expiry and nonce are all checked here, and the caller
checks the email domain. Provider metadata and signing keys are cached in memory.
"""
from __future__ import annotations

import base64
import hashlib
import secrets
import time
from urllib.parse import urlencode, urlparse

import httpx
import jwt

# Asymmetric algorithms only. "none" and the HS* family must never be accepted: with
# HS256 an attacker could sign a token using the provider's public key as the secret.
_ALGORITHMS = {
    "RS256", "RS384", "RS512", "PS256", "PS384", "PS512", "ES256", "ES384", "ES512", "EdDSA",
}
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
_CACHE_SECONDS = 3600
_TIMEOUT = 10.0

# issuer (no trailing slash) -> (fetched at, {"meta": ..., "jwks": ...})
_cache: dict[str, tuple[float, dict]] = {}


class OidcError(Exception):
    """The provider is misconfigured or returned something we refuse to trust."""


def check_url(url: str, what: str) -> str:
    """Provider URLs must be https. Plain http is allowed for localhost only, for
    development against a local provider."""
    parsed = urlparse(url)
    if not parsed.hostname:
        raise OidcError(f"The {what} is not a valid URL.")
    if parsed.scheme == "https" or (parsed.scheme == "http" and parsed.hostname in _LOCAL_HOSTS):
        return url
    raise OidcError(f"The {what} must use https.")


async def fetch_json(url: str) -> dict:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as http:
        resp = await http.get(url, headers={"Accept": "application/json"})
    resp.raise_for_status()
    data = resp.json()
    if not isinstance(data, dict):
        raise OidcError("The identity provider returned an unexpected response.")
    return data


async def post_form(url: str, data: dict, auth: tuple[str, str] | None = None) -> dict:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as http:
        resp = await http.post(url, data=data, auth=auth, headers={"Accept": "application/json"})
    resp.raise_for_status()
    body = resp.json()
    if not isinstance(body, dict):
        raise OidcError("The identity provider returned an unexpected response.")
    return body


async def provider(issuer: str, *, refresh: bool = False) -> dict:
    """Return {"meta": discovery document, "jwks": signing keys} for an issuer."""
    key = issuer.strip().rstrip("/")
    check_url(key, "issuer URL")
    cached = _cache.get(key)
    if cached and not refresh and time.monotonic() - cached[0] < _CACHE_SECONDS:
        return cached[1]
    try:
        meta = await fetch_json(f"{key}/.well-known/openid-configuration")
        if str(meta.get("issuer", "")).rstrip("/") != key:
            raise OidcError("The issuer in the provider's metadata does not match the issuer URL.")
        for field in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
            if not meta.get(field):
                raise OidcError(f"The provider's metadata has no {field}.")
            check_url(meta[field], field)
        jwks = await fetch_json(meta["jwks_uri"])
    except (httpx.HTTPError, ValueError) as exc:
        raise OidcError("Could not read the identity provider's OpenID configuration.") from exc
    if not isinstance(jwks.get("keys"), list):
        raise OidcError("The identity provider published no signing keys.")
    entry = {"meta": meta, "jwks": jwks}
    _cache[key] = (time.monotonic(), entry)
    return entry


def new_pkce() -> tuple[str, str]:
    """Return (code_verifier, code_challenge) for the S256 method."""
    verifier = secrets.token_urlsafe(48)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return verifier, base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def authorization_url(
    meta: dict, *, client_id: str, redirect_uri: str, state: str, nonce: str,
    code_challenge: str, login_hint: str | None = None,
) -> str:
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": "openid email profile",
        "state": state,
        "nonce": nonce,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    if login_hint:
        params["login_hint"] = login_hint
    sep = "&" if "?" in meta["authorization_endpoint"] else "?"
    return f"{meta['authorization_endpoint']}{sep}{urlencode(params)}"


async def exchange_code(
    meta: dict, *, client_id: str, client_secret: str, code: str, redirect_uri: str,
    code_verifier: str,
) -> str:
    """Swap the authorization code for tokens and return the raw ID token."""
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "code_verifier": code_verifier,
    }
    # client_secret_basic is the default when the provider lists no methods.
    methods = meta.get("token_endpoint_auth_methods_supported") or ["client_secret_basic"]
    auth = None
    if "client_secret_basic" in methods:
        auth = (client_id, client_secret)
    else:
        data["client_id"] = client_id
        data["client_secret"] = client_secret
    try:
        body = await post_form(meta["token_endpoint"], data, auth)
    except (httpx.HTTPError, ValueError) as exc:
        raise OidcError("The identity provider rejected the sign-in code.") from exc
    id_token = body.get("id_token")
    if not isinstance(id_token, str) or not id_token:
        raise OidcError("The identity provider returned no ID token.")
    return id_token


def _signing_key(jwks: dict, kid: str | None, alg: str):
    for jwk in jwks.get("keys", []):
        if not isinstance(jwk, dict) or jwk.get("use", "sig") != "sig":
            continue
        if kid is not None and jwk.get("kid") != kid:
            continue
        try:
            return jwt.PyJWK.from_dict(jwk, algorithm=alg).key
        except jwt.PyJWTError:
            continue
    return None


async def verify_id_token(issuer: str, id_token: str, *, client_id: str, nonce: str) -> dict:
    """Check the ID token's signature and claims and return the claims."""
    try:
        header = jwt.get_unverified_header(id_token)
    except jwt.PyJWTError as exc:
        raise OidcError("The ID token is malformed.") from exc
    alg = header.get("alg")
    if alg not in _ALGORITHMS:
        raise OidcError("The ID token uses a signing algorithm that is not allowed.")

    prov = await provider(issuer)
    key = _signing_key(prov["jwks"], header.get("kid"), alg)
    if key is None:
        # The provider may have rotated its keys since we cached them.
        prov = await provider(issuer, refresh=True)
        key = _signing_key(prov["jwks"], header.get("kid"), alg)
    if key is None:
        raise OidcError("The ID token was signed with an unknown key.")

    try:
        claims = jwt.decode(
            id_token,
            key,
            algorithms=[alg],
            audience=client_id,
            issuer=prov["meta"]["issuer"],
            leeway=60,
            options={"require": ["exp", "iat", "sub", "aud", "iss"]},
        )
    except jwt.PyJWTError as exc:
        raise OidcError("The ID token failed verification.") from exc

    azp = claims.get("azp")
    if azp is not None and azp != client_id:
        raise OidcError("The ID token was issued to a different client.")
    token_nonce = claims.get("nonce")
    if not isinstance(token_nonce, str) or not secrets.compare_digest(token_nonce, nonce):
        raise OidcError("The ID token does not belong to this sign-in attempt.")
    return claims
