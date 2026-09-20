"""Application settings.

Every value is read from the environment (optionally via a ``.env`` file) and
validated once at import. Nothing else in the codebase should call
``os.environ`` — import :func:`get_settings` instead.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["development", "staging", "production"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]

#: Values that must never be accepted as a signing key in production.
_INSECURE_SECRETS = frozenset({"", "change-me", "changeme", "secret", "coraxis", "test"})


class ProviderEnvKeys(BaseSettings):
    """Provider credentials supplied through the environment.

    These are *fallbacks only*. Credentials stored per-user in the database are
    encrypted at rest and always take precedence over anything defined here.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    groq_api_key: str = ""
    google_api_key: str = ""
    openai_api_key: str = ""
    ollama_base_url: str = "http://localhost:11434"

    def key_for(self, provider: str) -> str:
        """Return the environment fallback key for a provider, or ``""``."""
        return {
            "groq": self.groq_api_key,
            "gemini": self.google_api_key,
            "openai": self.openai_api_key,
            "ollama": "",  # local, keyless
        }.get(provider, "").strip()


class Settings(BaseSettings):
    """Validated application configuration."""

    model_config = SettingsConfigDict(
        env_prefix="CORAXIS_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ── Runtime ──────────────────────────────────────────────────────
    env: Environment = "development"
    debug: bool = False
    log_level: LogLevel = "INFO"
    log_json: bool = False

    # ── Secrets ──────────────────────────────────────────────────────
    secret_key: SecretStr = SecretStr("")
    encryption_key: SecretStr = SecretStr("")

    # ── Database ─────────────────────────────────────────────────────
    database_url: str = "sqlite+aiosqlite:///./data/coraxis.db"
    db_echo: bool = False
    db_pool_size: int = Field(default=5, ge=1, le=100)
    db_max_overflow: int = Field(default=10, ge=0, le=100)

    # ── HTTP ─────────────────────────────────────────────────────────
    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1, le=65535)
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    api_prefix: str = "/api/v1"

    # ── Authentication ───────────────────────────────────────────────
    access_token_minutes: int = Field(default=30, ge=1, le=1440)
    refresh_token_days: int = Field(default=14, ge=1, le=365)
    allow_registration: bool = True
    jwt_issuer: str = "coraxis"
    jwt_audience: str = "coraxis-api"
    jwt_algorithm: str = "HS256"

    # ── Quotas ───────────────────────────────────────────────────────
    rate_limit_enabled: bool = True
    rate_limit_runs_per_hour: int = Field(default=20, ge=0)
    rate_limit_requests_per_minute: int = Field(default=120, ge=0)
    run_timeout_seconds: int = Field(default=900, ge=30)
    run_max_concurrent_per_user: int = Field(default=2, ge=1)

    # ── Pipeline ─────────────────────────────────────────────────────
    max_sources: int = Field(default=8, ge=1, le=50)
    max_fetch_per_query: int = Field(default=5, ge=1, le=20)
    min_word_count: int = Field(default=100, ge=0)
    http_timeout_seconds: int = Field(default=20, ge=1, le=120)
    crew_max_rpm: int = Field(default=10, ge=1, le=600)

    # ── Semantic memory ──────────────────────────────────────────────
    memory_enabled: bool = True
    chroma_path: str = "./chroma_db"
    embedding_model: str = "all-MiniLM-L6-v2"

    # ── Nested provider keys ─────────────────────────────────────────
    providers: ProviderEnvKeys = Field(default_factory=ProviderEnvKeys)

    # ── Derived helpers ──────────────────────────────────────────────

    @property
    def is_production(self) -> bool:
        return self.env == "production"

    @property
    def cors_origin_list(self) -> list[str]:
        """CORS origins as a list.

        Stored as a comma-separated string rather than a ``list[str]`` so that
        pydantic-settings never attempts a JSON decode on the raw env value —
        ``http://a,http://b`` is not valid JSON and would fail at startup.
        """
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def sqlite_path(self) -> Path | None:
        """Filesystem path backing a SQLite URL, or ``None`` for other engines."""
        prefix = "sqlite+aiosqlite:///"
        if not self.database_url.startswith(prefix):
            return None
        raw = self.database_url[len(prefix) :]
        return Path(raw) if raw and raw != ":memory:" else None

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    def ensure_directories(self) -> None:
        """Create the parent directories the database and vector store need."""
        for path in (self.sqlite_path, Path(self.chroma_path)):
            if path is None:
                continue
            target = path if path.is_absolute() else Path.cwd() / path
            if target.suffix:  # a file, create its parent
                target.parent.mkdir(parents=True, exist_ok=True)
            else:
                target.mkdir(parents=True, exist_ok=True)

    # ── Validation ───────────────────────────────────────────────────

    @model_validator(mode="after")
    def _validate_security_posture(self) -> Settings:
        secret = self.secret_key.get_secret_value()

        if self.is_production:
            if secret.strip().lower() in _INSECURE_SECRETS:
                raise ValueError(
                    "CORAXIS_SECRET_KEY must be set to a strong, unique value when "
                    "CORAXIS_ENV=production. Generate one with: "
                    'python -c "import secrets; print(secrets.token_urlsafe(64))"'
                )
            if len(secret) < 32:
                raise ValueError("CORAXIS_SECRET_KEY must be at least 32 characters in production.")
            if "*" in self.cors_origin_list:
                raise ValueError(
                    "CORAXIS_CORS_ORIGINS must not contain '*' in production: a wildcard "
                    "origin cannot be combined with credentialed requests."
                )
            if self.allow_registration:
                raise ValueError(
                    "CORAXIS_ALLOW_REGISTRATION must be false in production. Create the "
                    "first account in development, or set this to false and provision "
                    "users directly."
                )
            if self.debug:
                raise ValueError("CORAXIS_DEBUG must be false in production.")

        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings singleton."""
    return Settings()


def reset_settings_cache() -> None:
    """Drop the cached settings. Intended for tests that patch the environment."""
    get_settings.cache_clear()
