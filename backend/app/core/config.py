import os

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_WEAK_SECRETS = {"change-me-in-production", "change-this-secret-before-production", "secret", ""}


class Settings(BaseSettings):
    mongo_uri: str = Field(default="mongodb://mongo:27017", alias="MONGO_URI")
    mongo_db: str = Field(default="cognivio", alias="MONGO_DB")
    jwt_secret: str = Field(default="", alias="JWT_SECRET")
    # Short-lived access JWT; refreshed via the long-lived refresh-token cookie below.
    access_token_minutes: int = Field(default=30, alias="ACCESS_TOKEN_MINUTES")
    refresh_token_days: int = Field(default=30, alias="REFRESH_TOKEN_DAYS")
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
    # Optional address shown in the Free-plan limit messages. Empty = the message tells
    # the user to ask their administrator.
    contact_email: str = Field(default="", alias="CONTACT_EMAIL")
    # Public URL of the app. Links in emails are built from it, never from the request's
    # Host header, so it is required when RESEND_API_KEY is set.
    public_url: str = Field(default="", alias="PUBLIC_URL")

    # Platform-admin allowlist: comma-separated emails granted access to the admin
    # console. An allowlist (not a self-service flag) so no one can escalate themselves.
    admin_emails: str = Field(default="", alias="ADMIN_EMAILS")

    # true (the default) means no plans: every org gets unlimited orgs, teams, members and
    # top-level projects. Set false to run a hosted service with Free and Enterprise plans.
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
            return f"Contact {self.contact_email} to upgrade."
        return "Ask your administrator to upgrade the plan."

    @property
    def admin_email_set(self) -> set[str]:
        return {e.strip().lower() for e in self.admin_emails.split(",") if e.strip()}


def is_platform_admin(email: str | None) -> bool:
    return bool(email) and email.lower() in settings.admin_email_set


settings = Settings()

if settings.jwt_secret in _WEAK_SECRETS or len(settings.jwt_secret) < 32:
    if os.getenv("TESTING"):
        settings.jwt_secret = "test-secret-not-for-production-use-only-for-testing-1234"
    else:
        raise RuntimeError(
            "JWT_SECRET is missing or too weak. "
            "Set a cryptographically random string of at least 32 characters."
        )

if settings.resend_api_key and not os.getenv("TESTING"):
    missing = [n for n, v in (("PUBLIC_URL", settings.public_url), ("EMAIL_FROM", settings.email_from)) if not v]
    if missing:
        raise RuntimeError(
            f"RESEND_API_KEY is set, so {' and '.join(missing)} must be set too. "
            "Email links are built from PUBLIC_URL and sent from EMAIL_FROM."
        )
