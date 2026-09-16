"""FastAPI dependency for request authentication.

Checks three paths in order:
1. AUTH_DISABLED=true (development only) → stub user
2. Authorization: Bearer <token> → service principal
3. Cookie: session=<jwt> → authenticated user
4. Otherwise → HTTP 401

The ``get_acting_member_id`` dependency extends service-token auth with an
optional ``X-Acting-Discord-Id`` header that allows the trusted bot to delegate
the Discord interaction subject for ``/me/*`` endpoints. Resolution uses only
an exact ``Member.discord_id`` match. Usernames never establish identity or
trigger automatic linking.
"""

import secrets
from dataclasses import dataclass

import jwt
from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import JWT_ALGORITHM, settings
from app.db.session import get_db
from app.models.member import Member
from app.models.user_account import UserAccount

SESSION_TYPE = "manager-user-v2"
ROLE_LEVEL = {"viewer": 1, "manager": 2, "admin": 3}

# Reused across every 404 branch so the bot sees a consistent message.
_NOT_REGISTERED_MSG = "Acting Discord user not found"


@dataclass
class AuthenticatedUser:
    """Represents the currently authenticated user or service principal.

    Attributes:
        member_id: Database PK of the authenticated member; ``None`` for
            service-token principals.
        name: Display name of the authenticated entity.
        is_service: ``True`` when authenticated via Bearer service token.
        role: Member role string, or ``None`` for service principals.
        discord_id: Discord snowflake string of the authenticated member,
            or ``None`` for service principals.
        acting_member_id: Resolved database PK of the member named by the
            ``X-Acting-Discord-Id`` header on service-token requests.  Always
            ``None`` for cookie-authenticated users and for service-token
            requests that omit the header.
    """

    member_id: int | None
    name: str
    is_service: bool
    role: str | None = None
    discord_id: str | None = None
    acting_member_id: int | None = None
    user_account_id: int | None = None
    app_role: str | None = None
    principal_type: str = "human"


async def _resolve_acting_member(
    db: AsyncSession,
    acting_discord_id: str,
) -> Member:
    """Resolve a bot-delegated subject by exact, stable Discord ID only.

    ``BOT_SERVICE_TOKEN`` authenticates the trusted bot service. The bot
    delegates the Discord interaction subject through ``X-Acting-Discord-Id``.
    Manager never uses username metadata to establish or repair identity;
    missing links must be created through the controlled Discord sync/admin
    workflow.
    """
    result = await db.execute(select(Member).where(Member.discord_id == acting_discord_id))
    member = result.scalar_one_or_none()
    if member is None:
        raise HTTPException(status_code=404, detail=_NOT_REGISTERED_MSG)
    return member


async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> AuthenticatedUser:
    """Resolve the caller's identity from the incoming request.

    Tries three mechanisms in priority order: dev bypass flag, Bearer token
    for service-to-service calls, and a signed JWT session cookie for
    browser-based users.

    For service-token requests, the optional ``X-Acting-Discord-Id`` header
    is consulted.  When present, the named Discord ID is resolved to a Member
    record and stored in ``acting_member_id``; the header is silently ignored
    on cookie-authenticated requests (cookie wins).

    Args:
        request: The incoming FastAPI/Starlette request object.
        db: Async SQLAlchemy session injected by ``get_db``.

    Returns:
        An ``AuthenticatedUser`` describing the verified caller.

    Raises:
        HTTPException: 404 when ``X-Acting-Discord-Id`` is present but names
            an unknown Discord user.  401 when no valid credential is found.
    """
    # 1. Dev bypass — only permitted when ENVIRONMENT=development
    if settings.auth_disabled:
        return AuthenticatedUser(
            member_id=None,
            name="dev-user",
            is_service=False,
            app_role="manager",
            principal_type="development",
        )

    # 2. Service token (Bearer) — timing-safe comparison prevents timing attacks
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer ") and settings.bot_service_token:
        provided = auth_header.removeprefix("Bearer ")
        if secrets.compare_digest(provided, settings.bot_service_token):
            acting_discord_id = request.headers.get("X-Acting-Discord-Id")
            acting_member_id: int | None = None
            if acting_discord_id is not None:
                if not acting_discord_id.isdigit() or len(acting_discord_id) > 20:
                    raise HTTPException(
                        status_code=400,
                        detail="X-Acting-Discord-Id must be a numeric Discord snowflake",
                    )
                acting_member = await _resolve_acting_member(db, acting_discord_id)
                acting_member_id = acting_member.id
            return AuthenticatedUser(
                member_id=None,
                name="bot-service",
                is_service=True,
                principal_type="bot_service",
                acting_member_id=acting_member_id,
                discord_id=acting_discord_id,
            )

    # 3. V2 user session cookie — version required so legacy Member IDs cannot collide.
    #    X-Acting-Discord-Id is intentionally ignored here; the cookie's
    #    UserAccount ID in the JWT is the authoritative human subject.
    session_token = request.cookies.get("session")
    if session_token:
        try:
            payload = jwt.decode(session_token, settings.session_secret, algorithms=[JWT_ALGORITHM])
            if payload.get("typ") != SESSION_TYPE:
                raise HTTPException(status_code=401, detail="Not authenticated")
            account = await db.get(UserAccount, int(payload["sub"]))
            if account and account.is_active and account.app_role in ROLE_LEVEL:
                member = await db.get(Member, account.member_id) if account.member_id else None
                return AuthenticatedUser(
                    member_id=account.member_id,
                    name=account.display_name,
                    is_service=False,
                    role=member.role.value if member and member.role else None,
                    discord_id=account.discord_user_id,
                    user_account_id=account.id,
                    app_role=account.app_role,
                    principal_type="human",
                )
        except (jwt.ExpiredSignatureError, jwt.InvalidTokenError, KeyError, ValueError):
            pass

    raise HTTPException(status_code=401, detail="Not authenticated")


async def require_human_user(
    user: AuthenticatedUser = Depends(get_current_user),
) -> AuthenticatedUser:
    if user.principal_type != "human" or user.user_account_id is None:
        raise HTTPException(status_code=403, detail="Human account required")
    return user


def require_role(minimum: str):
    """Build a dependency using the single central human role hierarchy."""
    if minimum not in ROLE_LEVEL:
        raise ValueError("Unknown application role")

    async def dependency(user: AuthenticatedUser = Depends(get_current_user)) -> AuthenticatedUser:
        if user.principal_type == "development" and minimum != "admin":
            return user
        if user.principal_type != "human" or user.user_account_id is None:
            raise HTTPException(status_code=403, detail="Human account required")
        if ROLE_LEVEL.get(user.app_role, 0) < ROLE_LEVEL[minimum]:
            raise HTTPException(status_code=403, detail="Insufficient application role")
        return user

    dependency.__name__ = f"require_{minimum}"
    return dependency


require_viewer = require_role("viewer")
require_manager = require_role("manager")
require_admin = require_role("admin")


async def require_bot_service_or_human_viewer(
    user: AuthenticatedUser = Depends(get_current_user),
) -> AuthenticatedUser:
    """Allow the documented bot preference contract and human VIEWER compatibility."""
    if user.principal_type == "bot_service":
        return user
    if user.principal_type == "development":
        return user
    if (
        user.principal_type == "human"
        and user.user_account_id is not None
        and ROLE_LEVEL.get(user.app_role, 0) >= ROLE_LEVEL["viewer"]
    ):
        return user
    raise HTTPException(status_code=403, detail="Human account or bot service required")


async def get_acting_member_id(
    user: AuthenticatedUser = Depends(get_current_user),
) -> int:
    """Resolve the subject member ID for ``/me/*`` endpoints.

    Cookie-authenticated requests resolve to the session member's ID.
    Service-token requests resolve to the member named by the
    ``X-Acting-Discord-Id`` header.  A service-token request without the
    header is rejected with 401 because there is no unambiguous subject.

    Args:
        user: The verified caller returned by ``get_current_user``.

    Returns:
        The database primary key of the acting member.

    Raises:
        HTTPException: 401 when the caller is a service principal without an
            ``X-Acting-Discord-Id`` header.
    """
    if user.member_id is not None:
        return user.member_id
    if user.acting_member_id is not None:
        return user.acting_member_id
    if user.principal_type == "human":
        raise HTTPException(status_code=404, detail="Member profile not linked")
    raise HTTPException(status_code=401, detail="Acting subject required")
