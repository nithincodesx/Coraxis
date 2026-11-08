"""Firebase Authentication integration.

Firebase owns identity (GitHub OAuth, email/password). The backend's only job
is to verify the Firebase ID token the frontend sends as the bearer token and
map it to a Coraxis ``User`` record by email, so runs, teams and credentials
keep belonging to an account.
"""

from __future__ import annotations

import firebase_admin
from firebase_admin import auth
from pydantic import BaseModel

from coraxis.core.config import get_settings
from coraxis.core.errors import AuthenticationError
from coraxis.db.models import User
from coraxis.repositories import users as user_repo

_app: firebase_admin.App | None = None


class FirebaseUser(BaseModel):
    """Decoded Firebase ID token claims the backend trusts."""

    uid: str
    email: str | None
    email_verified: bool = False
    display_name: str | None = None
    picture: str | None = None
    provider: list[str] | None = None


def initialize_firebase() -> None:
    """Initialize the Firebase Admin SDK once (safe to call repeatedly).

    Only the project id is required to verify ID tokens — the Admin SDK fetches
    Google's public certs itself. Set ``FIREBASE_PROJECT_ID`` in the environment.
    """
    global _app
    if _app is not None:
        return
    settings = get_settings()
    project_id = settings.firebase_project_id
    if not project_id:
        return
    _app = firebase_admin.initialize_app(options={"projectId": project_id})


def firebase_app() -> firebase_admin.App:
    """Return the initialized app, initializing on first use."""
    if _app is None:
        initialize_firebase()
    if _app is None:
        raise AuthenticationError("Firebase is not configured. Set FIREBASE_PROJECT_ID.")
    return _app


def verify_id_token(id_token: str) -> FirebaseUser:
    """Verify a Firebase ID token and return its trusted claims."""
    try:
        decoded = auth.verify_id_token(id_token, app=firebase_app())
    except Exception as exc:
        raise AuthenticationError(
            "Your sign-in session is no longer valid. Sign in again.",
            code="invalid_firebase_token",
        ) from exc

    providers = decoded.get("firebase", {}).get("identities", {})
    provider_keys = (
        [key for key in providers if key != "email"] if isinstance(providers, dict) else []
    )

    return FirebaseUser(
        uid=decoded["uid"],
        email=decoded.get("email"),
        email_verified=bool(decoded.get("email_verified")),
        display_name=decoded.get("name"),
        picture=decoded.get("picture"),
        provider=provider_keys or None,
    )


async def get_or_create_user(session, firebase_user: FirebaseUser) -> User:
    """Resolve a Coraxis user for a Firebase account, creating one on first sight.

    The first account created on an instance becomes its administrator.
    """
    email = firebase_user.email
    if not email:
        raise AuthenticationError("Firebase account has no email address.", code="no_email")

    user = await user_repo.get_by_email(session, email)
    if user is not None:
        if not user.is_active:
            raise AuthenticationError("This account is disabled.", code="account_disabled")
        # Keep the profile in sync with Firebase.
        if firebase_user.display_name and user.display_name != firebase_user.display_name:
            user.display_name = firebase_user.display_name
        await session.flush()
        return user

    existing = await user_repo.count(session)
    is_first_user = existing == 0
    settings = get_settings()
    if not settings.allow_registration and not is_first_user:
        raise AuthenticationError(
            "Registration is closed on this instance.", code="registration_closed"
        )

    # Firebase manages the password; store an unusable placeholder so the
    # column stays non-null without ever being verified against.
    user = await user_repo.create(
        session,
        email=email,
        password_hash="!firebase",
        display_name=firebase_user.display_name or "",
        is_superuser=is_first_user,
    )
    await session.flush()
    return user
