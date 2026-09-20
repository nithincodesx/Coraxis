"""Pydantic DTOs for the HTTP boundary.

Request models forbid unknown fields; response models never carry secrets.
"""

from __future__ import annotations

from coraxis.schemas.agents import (
    AgentCatalog,
    AgentCreate,
    AgentLLMSettingsIn,
    AgentLLMSettingsOut,
    AgentOut,
    AgentUpdate,
    ToolOut,
)
from coraxis.schemas.auth import (
    LoginRequest,
    LogoutRequest,
    RefreshRequest,
    RegisterRequest,
    SessionOut,
    TokenPair,
    UserOut,
)
from coraxis.schemas.common import (
    DeletedResponse,
    HealthResponse,
    Page,
    ReadyCheck,
    ReadyResponse,
    RequestModel,
    ResponseModel,
    UTCDatetime,
)
from coraxis.schemas.credentials import (
    CredentialOut,
    CredentialTestRequest,
    CredentialTestResult,
    CredentialUpsert,
    ProviderStatus,
)
from coraxis.schemas.runs import (
    ClaimOut,
    RunAccepted,
    RunCreate,
    RunDetail,
    RunEventOut,
    RunOptions,
    RunOut,
    RunStats,
    SourceOut,
)
from coraxis.schemas.teams import TeamCreate, TeamOut, TeamStepIn, TeamStepOut, TeamUpdate

__all__ = [
    "AgentCatalog",
    "AgentCreate",
    "AgentLLMSettingsIn",
    "AgentLLMSettingsOut",
    "AgentOut",
    "AgentUpdate",
    "ClaimOut",
    "CredentialOut",
    "CredentialTestRequest",
    "CredentialTestResult",
    "CredentialUpsert",
    "DeletedResponse",
    "HealthResponse",
    "LoginRequest",
    "LogoutRequest",
    "Page",
    "ProviderStatus",
    "ReadyCheck",
    "ReadyResponse",
    "RefreshRequest",
    "RegisterRequest",
    "RequestModel",
    "ResponseModel",
    "RunAccepted",
    "RunCreate",
    "RunDetail",
    "RunEventOut",
    "RunOptions",
    "RunOut",
    "RunStats",
    "SessionOut",
    "SourceOut",
    "TeamCreate",
    "TeamOut",
    "TeamStepIn",
    "TeamStepOut",
    "TeamUpdate",
    "TokenPair",
    "ToolOut",
    "UTCDatetime",
    "UserOut",
]
