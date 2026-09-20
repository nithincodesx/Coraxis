"""Database models.

One module, because the schema is small enough to read in one sitting and the
relationships between these tables are the interesting part. Each model
documents *why* it exists, not just what columns it has.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from coraxis.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, new_id, utcnow
from coraxis.db.enums import AgentKind, RunStatus, RunTrigger

# ─────────────────────────────────────────────────────────────────────
#  Identity
# ─────────────────────────────────────────────────────────────────────


class User(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """An account.

    ``token_version`` is the blunt revocation lever: bumping it invalidates
    every access and refresh token issued for the user, which is what you want
    on password change or a suspected compromise.
    """

    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_superuser: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    token_version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    credentials: Mapped[list[ProviderCredential]] = relationship(
        back_populates="user", cascade="all, delete-orphan", lazy="selectin"
    )
    refresh_tokens: Mapped[list[RefreshToken]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<User {self.email}>"


class RefreshToken(Base, UUIDPrimaryKeyMixin):
    """A persisted refresh-token session.

    Storing the ``jti`` (not the token itself) lets a single device be logged
    out without touching the others, and lets us detect reuse of a rotated
    token.
    """

    __tablename__ = "refresh_tokens"

    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    jti: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    user_agent: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    client_ip: Mapped[str] = mapped_column(String(64), default="", nullable=False)

    user: Mapped[User] = relationship(back_populates="refresh_tokens")

    @property
    def is_revoked(self) -> bool:
        return self.revoked_at is not None


class ProviderCredential(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """An encrypted provider API key belonging to one user.

    ``encrypted_key`` is a Fernet token — never the plaintext. ``key_hint``
    holds the last four characters so the UI can show *which* key is stored
    without the API ever returning a usable secret.
    """

    __tablename__ = "provider_credentials"
    __table_args__ = (
        UniqueConstraint("user_id", "provider", name="uq_provider_credentials_user_provider"),
    )

    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    encrypted_key: Mapped[str] = mapped_column(Text, nullable=False, default="")
    key_hint: Mapped[str] = mapped_column(String(16), default="", nullable=False)
    base_url: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    #: The user's chosen model for this provider. Empty means "use the built-in
    #: default", so an unset column never blocks a run.
    default_model: Mapped[str] = mapped_column(String(160), default="", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_validated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_validation_error: Mapped[str] = mapped_column(Text, default="", nullable=False)

    user: Mapped[User] = relationship(back_populates="credentials")

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<ProviderCredential {self.provider} user={self.user_id[:8]}>"


# ─────────────────────────────────────────────────────────────────────
#  Agent & team definitions
# ─────────────────────────────────────────────────────────────────────


class AgentDefinition(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A role definition — what an agent *is*, independent of how it is run.

    Built-in agents have ``user_id IS NULL`` and are seeded at migration time;
    every user sees them. Custom agents belong to one user.
    """

    __tablename__ = "agent_definitions"
    __table_args__ = (
        UniqueConstraint("user_id", "slug", name="uq_agent_definitions_user_slug"),
        Index("ix_agent_definitions_kind", "kind"),
    )

    user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    slug: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    role: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    goal: Mapped[str] = mapped_column(Text, default="", nullable=False)
    backstory: Mapped[str] = mapped_column(Text, default="", nullable=False)
    kind: Mapped[str] = mapped_column(String(16), default=AgentKind.CUSTOM.value, nullable=False)
    tools: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    @property
    def is_builtin(self) -> bool:
        return self.kind == AgentKind.BUILTIN.value


class AgentLLMSettings(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """How one user wants one agent to be run.

    Split from :class:`AgentDefinition` because two users share the built-in
    ``researcher`` role but almost never share a model or a provider key.
    """

    __tablename__ = "agent_llm_settings"
    __table_args__ = (
        UniqueConstraint("user_id", "agent_slug", name="uq_agent_llm_settings_user_agent"),
    )

    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    agent_slug: Mapped[str] = mapped_column(String(64), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), default="groq", nullable=False)
    model: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    temperature: Mapped[float] = mapped_column(Float, default=0.2, nullable=False)
    max_tokens: Mapped[int] = mapped_column(Integer, default=4096, nullable=False)
    base_url: Mapped[str] = mapped_column(String(255), default="", nullable=False)


class Team(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A user-composed group of agents that runs as one unit."""

    __tablename__ = "teams"

    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    coordinator_slug: Mapped[str | None] = mapped_column(String(64), nullable=True)
    coordinator_instructions: Mapped[str] = mapped_column(Text, default="", nullable=False)

    members: Mapped[list[TeamMember]] = relationship(
        back_populates="team",
        cascade="all, delete-orphan",
        order_by="TeamMember.position",
        lazy="selectin",
    )
    steps: Mapped[list[TeamStep]] = relationship(
        back_populates="team",
        cascade="all, delete-orphan",
        order_by="TeamStep.position",
        lazy="selectin",
    )


class TeamMember(Base, UUIDPrimaryKeyMixin):
    """Ordered membership of a team."""

    __tablename__ = "team_members"
    __table_args__ = (UniqueConstraint("team_id", "agent_slug", name="uq_team_members_team_agent"),)

    team_id: Mapped[str] = mapped_column(
        ForeignKey("teams.id", ondelete="CASCADE"), nullable=False, index=True
    )
    agent_slug: Mapped[str] = mapped_column(String(64), nullable=False)
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    team: Mapped[Team] = relationship(back_populates="members")


class TeamStep(Base, UUIDPrimaryKeyMixin):
    """One step of a team's workflow."""

    __tablename__ = "team_steps"

    team_id: Mapped[str] = mapped_column(
        ForeignKey("teams.id", ondelete="CASCADE"), nullable=False, index=True
    )
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    agent_slug: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    expected_output: Mapped[str] = mapped_column(Text, default="", nullable=False)

    team: Mapped[Team] = relationship(back_populates="steps")


# ─────────────────────────────────────────────────────────────────────
#  Runs
# ─────────────────────────────────────────────────────────────────────


class Run(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """One execution of the research pipeline or a team workflow.

    This is the durable record the old implementation lacked entirely: it
    survives a restart, it can be listed, filtered, and re-opened, and its
    terminal state is written exactly once.
    """

    __tablename__ = "runs"
    __table_args__ = (
        Index("ix_runs_user_status", "user_id", "status"),
        Index("ix_runs_user_created", "user_id", "created_at"),
    )

    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    team_id: Mapped[str | None] = mapped_column(
        ForeignKey("teams.id", ondelete="SET NULL"), nullable=True
    )

    query: Mapped[str] = mapped_column(Text, nullable=False)
    trigger: Mapped[str] = mapped_column(
        String(16), default=RunTrigger.PIPELINE.value, nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(16), default=RunStatus.QUEUED.value, nullable=False, index=True
    )

    # Options captured at submission so a run can be replayed identically.
    options: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    # Outcome
    error: Mapped[str] = mapped_column(Text, default="", nullable=False)
    report_markdown: Mapped[str] = mapped_column(Text, default="", nullable=False)
    executive_summary: Mapped[str] = mapped_column(Text, default="", nullable=False)
    key_findings: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    citations_markdown: Mapped[str] = mapped_column(Text, default="", nullable=False)
    stats: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    # Timing
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    runtime_seconds: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    # Cooperative cancellation. The worker checks this between agent steps.
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    event_seq: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    events: Mapped[list[RunEvent]] = relationship(
        back_populates="run", cascade="all, delete-orphan", passive_deletes=True
    )
    sources: Mapped[list[RunSource]] = relationship(
        back_populates="run", cascade="all, delete-orphan", lazy="selectin"
    )
    claims: Mapped[list[RunClaim]] = relationship(
        back_populates="run", cascade="all, delete-orphan", lazy="selectin"
    )

    @property
    def is_terminal(self) -> bool:
        return RunStatus(self.status).is_terminal


class RunEvent(Base, UUIDPrimaryKeyMixin):
    """An append-only event in a run's timeline.

    ``seq`` is a per-run monotonic counter. It is the cursor the SSE endpoint
    uses for ``Last-Event-ID`` resumption, which is why it is a plain integer
    rather than a timestamp: timestamps are not guaranteed unique or ordered.
    """

    __tablename__ = "run_events"
    __table_args__ = (Index("ix_run_events_run_seq", "run_id", "seq"),)

    run_id: Mapped[str] = mapped_column(
        ForeignKey("runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    type: Mapped[str] = mapped_column(String(48), nullable=False)
    agent: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    level: Mapped[str] = mapped_column(String(16), default="info", nullable=False)
    message: Mapped[str] = mapped_column(Text, default="", nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, nullable=False, index=True
    )

    run: Mapped[Run] = relationship(back_populates="events")


class RunSource(Base, UUIDPrimaryKeyMixin):
    """A web source that contributed to a run's report.

    Separate from ``RunClaim`` because the many-to-many between sources and
    claims is genuinely many-to-many, and flattening it would lose the
    per-source relevance score the UI renders as a bar.
    """

    __tablename__ = "run_sources"
    __table_args__ = (Index("ix_run_sources_run_relevance", "run_id", "relevance"),)

    run_id: Mapped[str] = mapped_column(
        ForeignKey("runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    url: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, default="", nullable=False)
    relevance: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    snippet: Mapped[str] = mapped_column(Text, default="", nullable=False)
    word_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    fetch_success: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    run: Mapped[Run] = relationship(back_populates="sources")

    @property
    def relevance_pct(self) -> int:
        return round(self.relevance * 100)


class RunClaim(Base, UUIDPrimaryKeyMixin):
    """A synthesised claim and the sources supporting it."""

    __tablename__ = "run_claims"

    run_id: Mapped[str] = mapped_column(
        ForeignKey("runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    #: Stable identifier assigned by the citation tracker, e.g. ``claim_9f2c1a``.
    claim_ref: Mapped[str] = mapped_column(String(64), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    relevance: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    agent: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    source_urls: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)

    run: Mapped[Run] = relationship(back_populates="claims")


# ─────────────────────────────────────────────────────────────────────
#  Semantic memory
# ─────────────────────────────────────────────────────────────────────


class MemoryRecord(Base, UUIDPrimaryKeyMixin):
    """A relational mirror of what was written to the vector store.

    Chroma owns the embeddings; this table owns the *facts*. Keeping both means
    the vector index can be rebuilt from the database if it is ever corrupted
    or the embedding model changes, which is otherwise a silent data loss.
    """

    __tablename__ = "memory_records"
    __table_args__ = (
        Index("ix_memory_records_user_topic", "user_id", "topic"),
        Index("ix_memory_records_vector_id", "vector_id"),
    )

    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    run_id: Mapped[str | None] = mapped_column(
        ForeignKey("runs.id", ondelete="SET NULL"), nullable=True
    )
    topic: Mapped[str] = mapped_column(String(255), nullable=False)
    claim: Mapped[str] = mapped_column(Text, nullable=False)
    sources: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    relevance: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    agent: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    #: Identifier inside the Chroma collection, so the two stores can be reconciled.
    vector_id: Mapped[str] = mapped_column(String(64), default=new_id, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, nullable=False, index=True
    )
