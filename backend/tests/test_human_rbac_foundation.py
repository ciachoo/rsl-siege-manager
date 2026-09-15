"""Human account, session version and RBAC security boundary."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import jwt
import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings
from app.dependencies.auth import (
    AuthenticatedUser,
    get_acting_member_id,
    get_current_user,
    require_admin,
    require_manager,
    require_viewer,
)
from app.main import app
from app.models.member import Member
from app.models.user_account import UserAccount


@pytest.mark.asyncio
async def test_account_constraints_and_domain_separation():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    import app.models  # noqa: F401
    from app.db.base import Base

    event.listen(
        engine.sync_engine, "connect", lambda conn, _: conn.execute("PRAGMA foreign_keys=ON")
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db_session:
        account = UserAccount(discord_user_id="123456789012345678", display_name="A")
        db_session.add(account)
        await db_session.flush()
        assert account.app_role == "viewer"
        assert account.is_active is True
        assert account.member_id is None
        assert account.discord_user_id == "123456789012345678"
        db_session.add(UserAccount(discord_user_id=account.discord_user_id, display_name="B"))
        with pytest.raises(IntegrityError):
            await db_session.flush()
    await engine.dispose()
    assert Member.__tablename__ == "member"


@pytest.mark.asyncio
async def test_legacy_token_cannot_resolve_colliding_account(monkeypatch):
    monkeypatch.setattr(settings, "auth_disabled", False)
    monkeypatch.setattr(settings, "session_secret", "test-session-secret")
    account = SimpleNamespace(
        id=1,
        discord_user_id="123",
        display_name="A",
        member_id=None,
        app_role="admin",
        is_active=True,
    )
    db = AsyncMock()
    db.get.return_value = account
    old_token = jwt.encode(
        {"sub": "1", "iat": datetime.now(UTC), "exp": datetime.now(UTC) + timedelta(hours=1)},
        settings.session_secret,
        algorithm="HS256",
    )
    request = SimpleNamespace(headers={}, cookies={"session": old_token})
    with pytest.raises(HTTPException) as exc:
        await get_current_user(request, db)
    assert exc.value.status_code == 401
    db.get.assert_not_awaited()


@pytest.mark.asyncio
async def test_role_hierarchy_rejects_wrong_principals():
    viewer = AuthenticatedUser(
        member_id=None,
        name="A",
        is_service=False,
        app_role="viewer",
        principal_type="human",
        user_account_id=1,
    )
    manager = AuthenticatedUser(
        member_id=None,
        name="B",
        is_service=False,
        app_role="manager",
        principal_type="human",
        user_account_id=2,
    )
    admin = AuthenticatedUser(
        member_id=None,
        name="C",
        is_service=False,
        app_role="admin",
        principal_type="human",
        user_account_id=3,
    )
    dev = AuthenticatedUser(
        member_id=None, name="dev", is_service=False, principal_type="development"
    )
    bot = AuthenticatedUser(
        member_id=None, name="bot", is_service=True, principal_type="bot_service"
    )
    for user in (viewer, manager, dev, bot):
        with pytest.raises(HTTPException) as exc:
            await require_admin(user)
        assert exc.value.status_code == 403
    assert await require_manager(manager) is manager
    assert await require_manager(admin) is admin
    assert await require_admin(admin) is admin
    assert await require_viewer(viewer) is viewer


@pytest.mark.asyncio
async def test_role_and_active_state_refreshed_after_token_issuance(monkeypatch):
    monkeypatch.setattr(settings, "auth_disabled", False)
    monkeypatch.setattr(settings, "session_secret", "test-session-secret")
    account = SimpleNamespace(
        id=7,
        member_id=None,
        display_name="A",
        discord_user_id="123",
        app_role="admin",
        is_active=True,
    )
    db = AsyncMock()
    db.get.return_value = account
    token = jwt.encode(
        {
            "typ": "manager-user-v2",
            "sub": "7",
            "iat": datetime.now(UTC),
            "exp": datetime.now(UTC) + timedelta(hours=1),
        },
        settings.session_secret,
        algorithm="HS256",
    )
    request = SimpleNamespace(headers={}, cookies={"session": token})
    principal = await get_current_user(request, db)
    assert await require_admin(principal) is principal
    account.app_role = "viewer"
    principal = await get_current_user(request, db)
    with pytest.raises(HTTPException) as exc:
        await require_manager(principal)
    assert exc.value.status_code == 403
    account.is_active = False
    with pytest.raises(HTTPException) as exc:
        await get_current_user(request, db)
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_account_only_member_workflow_fails_without_fallback():
    principal = AuthenticatedUser(
        member_id=None,
        name="A",
        is_service=False,
        user_account_id=3,
        app_role="viewer",
        principal_type="human",
    )
    with pytest.raises(HTTPException) as exc:
        await get_acting_member_id(principal)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_cookie_mutation_rejects_missing_or_foreign_origin(monkeypatch):
    monkeypatch.setattr(settings, "auth_disabled", False)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        client.cookies.set("session", "cookie")
        denied = await client.post("/api/auth/logout")
        assert denied.status_code == 403
        denied = await client.post("/api/auth/logout", headers={"Origin": "https://evil.example"})
        assert denied.status_code == 403
        denied = await client.post(
            "/api/auth/logout", headers={"Authorization": "Bearer wrong-token"}
        )
        assert denied.status_code == 403
        configured_origin = settings.allowed_origins.split(",")[0].strip()
        allowed = await client.post("/api/auth/logout", headers={"Origin": configured_origin})
        assert allowed.status_code == 200


@pytest.mark.asyncio
async def test_callback_unknown_and_disabled_account_denied(monkeypatch):
    monkeypatch.setattr(settings, "auth_disabled", False)
    monkeypatch.setattr(settings, "environment", "development")
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    db.execute.return_value = result
    from app.db.session import get_db

    async def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    try:
        with (
            patch("app.api.auth._exchange_code_for_token", new=AsyncMock(return_value="token")),
            patch(
                "app.api.auth._get_discord_user",
                new=AsyncMock(return_value={"id": "123456789012345678", "username": "unknown"}),
            ),
            patch(
                "app.api.auth._check_guild_membership",
                new=AsyncMock(
                    return_value={"is_member": True, "role_names": [settings.discord_required_role]}
                ),
            ),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test", follow_redirects=False
            ) as client:
                client.cookies.set("oauth_state", "test-state")
                response = await client.get(
                    "/api/auth/callback", params={"code": "code", "state": "test-state"}
                )
                assert response.headers["location"] == "/login?error=unauthorized"
                result.scalar_one_or_none.return_value = SimpleNamespace(is_active=False)
                response = await client.get(
                    "/api/auth/callback", params={"code": "code", "state": "test-state"}
                )
                assert response.headers["location"] == "/login?error=unauthorized"
                db.commit.assert_not_awaited()
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
@pytest.mark.parametrize("app_role", ["admin", "manager"])
@pytest.mark.parametrize("member_id", [None, 7])
@pytest.mark.parametrize(
    ("global_name", "expected_name"),
    [("Current Discord Name", "Current Discord Name"), (None, "current_username")],
)
async def test_callback_active_account_updates_name_and_preserves_authorization(
    monkeypatch, app_role, member_id, global_name, expected_name
):
    monkeypatch.setattr(settings, "auth_disabled", False)
    monkeypatch.setattr(settings, "environment", "development")
    monkeypatch.setattr(settings, "session_secret", "test-session-secret-for-account-login")
    account = SimpleNamespace(
        id=42,
        discord_user_id="123456789012345678",
        display_name="Discord user 123456789012345678",
        app_role=app_role,
        is_active=True,
        member_id=member_id,
        last_login_at=None,
    )
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = account
    db.execute.return_value = result
    from app.db.session import get_db

    async def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    try:
        with (
            patch("app.api.auth._exchange_code_for_token", new=AsyncMock(return_value="token")),
            patch(
                "app.api.auth._get_discord_user",
                new=AsyncMock(
                    return_value={
                        "id": account.discord_user_id,
                        "global_name": global_name,
                        "username": "current_username",
                    }
                ),
            ),
            patch(
                "app.api.auth._check_guild_membership",
                new=AsyncMock(
                    return_value={"is_member": True, "role_names": [settings.discord_required_role]}
                ),
            ),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test", follow_redirects=False
            ) as client:
                client.cookies.set("oauth_state", "test-state")
                test_ip = (
                    1
                    + (app_role == "manager")
                    + 2 * (member_id is not None)
                    + 4 * (global_name is None)
                )
                response = await client.get(
                    "/api/auth/callback",
                    params={"code": "code", "state": "test-state"},
                    headers={"X-Forwarded-For": f"198.51.100.{test_ip}"},
                )
        assert response.status_code == 302
        assert response.headers["location"] == "/"
        assert "session" in response.cookies
        assert account.display_name == expected_name
        assert (
            jwt.decode(response.cookies["session"], settings.session_secret, algorithms=["HS256"])[
                "name"
            ]
            == expected_name
        )
        assert account.last_login_at is not None
        assert account.app_role == app_role
        assert account.is_active is True
        assert account.member_id == member_id
        db.commit.assert_awaited_once()
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_representative_siege_mutation_enforces_manager_role():
    from app.db.session import get_db
    from app.dependencies.auth import get_current_user as auth_dependency

    principal = AuthenticatedUser(
        member_id=None,
        name="Viewer",
        is_service=False,
        app_role="viewer",
        principal_type="human",
        user_account_id=1,
    )

    async def override_auth():
        return principal

    async def override_db():
        yield AsyncMock()

    app.dependency_overrides[auth_dependency] = override_auth
    app.dependency_overrides[get_db] = override_db
    try:
        with patch("app.api.sieges.sieges_service.delete_siege", new=AsyncMock()) as delete:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                denied = await client.delete("/api/sieges/4")
                assert denied.status_code == 403
                delete.assert_not_awaited()
                principal.app_role = "manager"
                allowed = await client.delete("/api/sieges/4")
                assert allowed.status_code == 204
                delete.assert_awaited_once()
    finally:
        app.dependency_overrides.pop(auth_dependency, None)
        app.dependency_overrides.pop(get_db, None)
