"""FastAPI dependency for request authentication.

Checks three paths in order:
1. AUTH_DISABLED=true (development only) → stub user
2. Authorization: Bearer <token> → service principal
3. Cookie: session=<jwt> → authenticated user
4. Otherwise → HTTP 401

The ``get_acting_member_id`` dependency extends service-token auth with an
optional ``X-Acting-Discord-Id`` header that allows the bot to act on behalf
of a specific member for ``/me/*`` endpoints.

When ``X-Acting-Discord-Id`` is present, the member lookup follows this order:

1. Snowflake match — ``Member.discord_id == acting_discord_id``.  Hit → done.
2. Username fallback (requires ``X-Acting-Discord-Username``) — case-insensitive
   match on ``Member.discord_username``.  Multi-row → 409.  No rows → 404.
3. Backfill conflict guard — if the matched member has no ``discord_id``,
   verify no other row already owns ``acting_discord_id``.  Conflict → 404.
4. Opportunistic backfill — write ``discord_id = acting_discord_id`` and commit
   so future calls hit path 1 directly.
"""

import logging
import secrets
from dataclasses import dataclass

import jwt
from fastapi import Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import JWT_ALGORITHM, settings
from app.db.session import get_db
from app.models.member import Member
from app.models.user_account import UserAccount

SESSION_TYPE = "manager-user-v2"
ROLE_LEVEL = {"viewer": 1, "manager": 2, "admin": 3}

logger = logging.getLogger(__name__)

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
    acting_username: str | None,
) -> Member:
    """Resolve the acting member from a Discord snowflake (and optional username).

    Lookup order:

    1. Snowflake match — ``Member.discord_id == acting_discord_id``.
       Returns immediately on hit.
    2. Username fallback — case-insensitive match on
       ``Member.discord_username``.  Skipped when ``acting_username`` is
       ``None``.
    3. Multi-row guard — raises 409 when two or more rows share the same
       lowercased ``discord_username``.
    4. Backfill conflict guard — if the matched member has
       ``discord_id IS NULL``, checks that no other row already owns
       ``acting_discord_id``.  Raises 404 on conflict.
    5. Opportunistic backfill — writes ``discord_id = acting_discord_id``
       and commits so future calls hit path 1 directly.

    Args:
        db: Async SQLAlchemy session.
        acting_discord_id: Validated numeric Discord snowflake string.
        acting_username: Value of the ``X-Acting-Discord-Username`` header,
            or ``None`` when the header was absent.

    Returns:
        The resolved ``Member`` record.

    Raises:
        HTTPException: 404 when no member can be matched, or when the
            backfill conflict guard fires.  409 when two members share the
            same lowercased ``discord_username``.
    """
    # --- Step 1: snowflake lookup -------------------------------------------
    result = await db.execute(select(Member).where(Member.discord_id == acting_discord_id))
    member = result.scalar_one_or_none()
    if member is not None:
        return member

    # --- Step 2: username fallback ------------------------------------------
    if not acting_username:
        raise HTTPException(status_code=404, detail=_NOT_REGISTERED_MSG)

    if len(acting_username) > 32:
        raise HTTPException(
            status_code=400,
            detail="X-Acting-Discord-Username exceeds maximum length",
        )

    result = await db.execute(
        select(Member)
        .where(func.lower(Member.discord_username) == acting_username.lower())
        .limit(2)
    )
    rows = result.scalars().all()

    # --- Step 3: multi-row guard --------------------------------------------
    if len(rows) > 1:
        raise HTTPException(
            status_code=409,
            detail="multiple members claim this Discord username; admin must resolve",
        )

    if not rows:
        raise HTTPException(status_code=404, detail=_NOT_REGISTERED_MSG)

    matched = rows[0]

    # --- Step 4: backfill conflict guard ------------------------------------
    if matched.discord_id is None:
        conflict_result = await db.execute(
            select(Member.id).where(Member.discord_id == acting_discord_id)
        )
        if conflict_result.scalar_one_or_none() is not None:
            logger.warning(
                "Backfill conflict: acting_discord_id=%s already owned "
                "by another member; matched member id=%s left unchanged",
                acting_discord_id,
                matched.id,
            )
            raise HTTPException(status_code=404, detail=_NOT_REGISTERED_MSG)

        # --- Step 5: opportunistic backfill ---------------------------------
        # The commit here is intentional and independent of outer request
        # success.  get_db() yields a fresh session per request, so nothing
        # else is dirty.  Persisting the backfill unconditionally means a
        # user hitting transient downstream errors will not permanently pay
        # the slow username-fallback path on every retry.
        matched.discord_id = acting_discord_id
        await db.commit()

    return matched


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
                acting_member = await _resolve_acting_member(
                    db,
                    acting_discord_id,
                    request.headers.get("X-Acting-Discord-Username"),
                )
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

    return dependency


require_viewer = require_role("viewer")
require_manager = require_role("manager")
require_admin = require_role("admin")


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
