import os
import secrets
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_WEAK_SECRETS = {"change-me-in-production", "change-this-secret-before-production", "secret", ""}


class Settings(BaseSettings):
    mongo_uri: str = Field(default="mongodb://mongo:27017", alias="MONGO_URI")
    mongo_db: str = Field(default="cognivio", alias="MONGO_DB")
    jwt_secret: str = Field(default="", alias="JWT_SECRET")
    # Opt-in for single-machine installs: when JWT_SECRET is empty, read the secret from
    # this file and create it with a random value on first start. The file must be on
    # storage that outlives the container, or every restart signs everyone out and the
    # stored repo tokens and single sign-on client secrets become unreadable.
    jwt_secret_file: str = Field(default="", alias="JWT_SECRET_FILE")
    # Short-lived access JWT; refreshed via the long-lived refresh-token cookie below.
    access_token_minutes: int = Field(default=30, alias="ACCESS_TOKEN_MINUTES")
    refresh_token_days: int = Field(default=30, alias="REFRESH_TOKEN_DAYS")
    # A single sign-on session ends this many hours after sign-in, however active it is.
    # The person then passes the identity provider again, so someone the provider has
    # deactivated loses access within this window.
    sso_session_hours: int = Field(default=12, ge=1, alias="SSO_SESSION_HOURS")
    cors_origins: str = Field(
        default="http://localhost:5173,http://127.0.0.1:5173", alias="CORS_ORIGINS"
    )
    disable_docs: bool = Field(default=False, alias="DISABLE_DOCS")
    frontend_dist: str = Field(default="/app/frontend/dist", alias="FRONTEND_DIST")
    # Directory holding the built MCP connector wheel, served at /connector so users
    # can `pipx install <url>` without cloning the repo or publishing to PyPI.
    connector_dir: str = Field(default="/app/connector", alias="CONNECTOR_DIR")
    api_key_prefix: str = Field(default="ak_", alias="API_KEY_PREFIX")

    # Transactional email via Resend. Empty key = email disabled (sends are skipped,
    # never an error) so local dev and tests work without it.
    resend_api_key: str = Field(default="", alias="RESEND_API_KEY")
    # Sender address on your Resend-verified domain. Required when RESEND_API_KEY is set.
    email_from: str = Field(default="", alias="EMAIL_FROM")
    # Contact address for the Teams plan, shown in the plan limit messages when
    # SELF_HOSTED is false. Empty = the messages say to ask an administrator.
    contact_email: str = Field(default="", alias="CONTACT_EMAIL")
    # Public URL of the app. Links in emails are built from it, never from the request's
    # Host header, so it is required when RESEND_API_KEY is set.
    public_url: str = Field(default="", alias="PUBLIC_URL")

    # Platform-admin allowlist: comma-separated emails granted access to the admin
    # console. An allowlist (not a self-service flag) so no one can escalate themselves.
    admin_emails: str = Field(default="", alias="ADMIN_EMAILS")

    # true (the default) means no plans: every org gets unlimited orgs, teams, members and
    # top-level projects. Set false to run a hosted service with a free plan and a Teams plan.
    self_hosted: bool = Field(default=True, alias="SELF_HOSTED")

    # false closes sign-up: only existing accounts can log in. Use it once your team has
    # registered, on any instance reachable from the internet.
    registration_open: bool = Field(default=True, alias="REGISTRATION_OPEN")

    # Self-hosted semantic embeddings (fastembed / ONNX, no PyTorch). Disabled = retrieval
    # falls back to lexical only. The model is loaded in-process and runs on CPU; KB content
    # never leaves the server, preserving the "no third-party model calls on KB content"
    # stance. Auto-disabled under TESTING (see app.core.embeddings).
    embeddings_enabled: bool = Field(default=True, alias="EMBEDDINGS_ENABLED")
    embedding_model: str = Field(default="BAAI/bge-small-en-v1.5", alias="EMBEDDING_MODEL")
    # Where fastembed caches the ONNX model. The Docker build pre-downloads here so cold
    # starts (and offline runtimes) don't fetch it. Empty = fastembed's default location.
    embedding_cache_dir: str = Field(default="", alias="FASTEMBED_CACHE_PATH")

    model_config = SettingsConfigDict(env_file=("../.env", ".env"), extra="ignore")

    @property
    def email_enabled(self) -> bool:
        return bool(self.resend_api_key)

    @property
    def upgrade_hint(self) -> str:
        if self.contact_email:
            return f"Contact {self.contact_email} to turn on Teams."
        return "Ask your administrator to turn on Teams."

    @property
    def admin_email_set(self) -> set[str]:
        return {e.strip().lower() for e in self.admin_emails.split(",") if e.strip()}


def is_platform_admin(email: str | None) -> bool:
    return bool(email) and email.lower() in settings.admin_email_set


def load_or_create_secret(path: str) -> str:
    """Return the secret stored at `path`, writing a new random one if the file is
    missing or empty. A file that holds a short value is an error, never overwritten."""
    file = Path(path)
    try:
        existing = file.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        existing = ""
    except OSError as exc:
        raise RuntimeError(f"Could not read JWT_SECRET_FILE ({path}): {exc}") from exc
    if len(existing) >= 32:
        return existing
    if existing:
        raise RuntimeError(
            f"JWT_SECRET_FILE ({path}) holds a secret shorter than 32 characters. "
            "Replace its contents or delete the file to have a new one created."
        )
    secret = secrets.token_hex(32)
    try:
        file.parent.mkdir(parents=True, exist_ok=True)
        # 0600: the secret signs every session, so only the server's user may read it.
        fd = os.open(file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(secret + "\n")
    except OSError as exc:
        raise RuntimeError(
            f"Could not write JWT_SECRET_FILE ({path}): {exc}. "
            "Make the directory writable by the server, or set JWT_SECRET instead."
        ) from exc
    return secret


settings = Settings()

if not settings.jwt_secret and settings.jwt_secret_file and not os.getenv("TESTING"):
    settings.jwt_secret = load_or_create_secret(settings.jwt_secret_file)

if settings.jwt_secret in _WEAK_SECRETS or len(settings.jwt_secret) < 32:
    if os.getenv("TESTING"):
        settings.jwt_secret = "test-secret-not-for-production-use-only-for-testing-1234"
    else:
        raise RuntimeError(
            "JWT_SECRET is missing or too weak. "
            "Set a cryptographically random string of at least 32 characters, or set "
            "JWT_SECRET_FILE to a path on persistent storage to have one created."
        )

if settings.resend_api_key and not os.getenv("TESTING"):
    missing = [n for n, v in (("PUBLIC_URL", settings.public_url), ("EMAIL_FROM", settings.email_from)) if not v]
    if missing:
        raise RuntimeError(
            f"RESEND_API_KEY is set, so {' and '.join(missing)} must be set too. "
            "Email links are built from PUBLIC_URL and sent from EMAIL_FROM."
        )
