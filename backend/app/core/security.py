from __future__ import annotations

import base64
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from functools import lru_cache

import bcrypt
from cryptography.fernet import Fernet, InvalidToken
import jwt

from app.core.config import settings

_JWT_ALGORITHM = "HS256"


@lru_cache(maxsize=1)
def _fernet() -> Fernet:
    # Symmetric key derived from JWT_SECRET so no new config is required. JWT_SECRET is
    # already validated to be strong at startup (see app.core.config).
    key = base64.urlsafe_b64encode(hashlib.sha256(settings.jwt_secret.encode("utf-8")).digest())
    return Fernet(key)


def encrypt_secret(plaintext: str) -> str:
    """Encrypt a sensitive value (e.g. a VCS PAT) for storage at rest."""
    return _fernet().encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt_secret(value: str) -> str:
    """Decrypt a value written by `encrypt_secret`. Legacy plaintext (written before
    encryption existed) isn't a valid token and is returned as-is, so old rows keep
    working until they're next saved. ValueError covers non-base64/malformed input on
    older `cryptography` builds (which raise ValueError rather than InvalidToken)."""
    try:
        return _fernet().decrypt(value.encode("utf-8")).decode("utf-8")
    except (InvalidToken, ValueError):
        return value


def hash_password(password: str) -> str:
    password_bytes = password.encode("utf-8")
    return bcrypt.hashpw(password_bytes, bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))


def create_access_token(subject: str) -> str:
    expires_at = datetime.now(timezone.utc) + timedelta(
        minutes=settings.access_token_minutes
    )
    payload = {"sub": subject, "exp": expires_at}
    return jwt.encode(payload, settings.jwt_secret, algorithm=_JWT_ALGORITHM)


def decode_access_token(token: str) -> str | None:
    try:
        payload = jwt.decode(
            token, settings.jwt_secret, algorithms=[_JWT_ALGORITHM]
        )
    except jwt.InvalidTokenError:
        return None

    subject = payload.get("sub")
    return subject if isinstance(subject, str) else None


def hash_api_key(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def generate_api_key() -> tuple[str, str, str]:
    """Return (full_key, prefix, key_hash). The full key is shown to the
    user once; only the hash is stored."""
    secret = secrets.token_urlsafe(32)
    full_key = f"{settings.api_key_prefix}{secret}"
    prefix = full_key[: len(settings.api_key_prefix) + 6]
    return full_key, prefix, hash_api_key(full_key)
