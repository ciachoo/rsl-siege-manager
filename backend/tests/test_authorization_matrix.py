"""Task #5C authorization inventory and principal-isolation regressions."""

import pytest
from fastapi import HTTPException
from fastapi.routing import APIRoute
from httpx import ASGITransport, AsyncClient

from app.dependencies.auth import (
    AuthenticatedUser,
    require_admin,
    require_bot_service_or_human_viewer,
    require_manager,
    require_viewer,
)
from app.main import app

PUBLIC = {
    ("GET", "/api/health"),
    ("GET", "/api/version"),
    ("GET", "/api/config"),
    ("GET", "/api/auth/login"),
    ("GET", "/api/auth/callback"),
    ("POST", "/api/auth/logout"),
}
SCANNER = {("POST", "/api/scanner/snapshots")}
DUAL_BOT_VIEWER = {
    ("GET", "/api/post-conditions"),
    ("GET", "/api/members/me/preferences"),
    ("PUT", "/api/members/me/preferences"),
}
ADMIN = {
    ("POST", "/api/scanners"),
    ("GET", "/api/scanners"),
    ("GET", "/api/scanners/{scanner_id}"),
    ("POST", "/api/scanners/{scanner_id}/rotate-credential"),
    ("POST", "/api/scanners/{scanner_id}/revoke"),
    ("POST", "/api/members/discord-sync/preview"),
    ("POST", "/api/members/discord-sync/apply"),
    ("POST", "/api/members"),
    ("PUT", "/api/members/{member_id}"),
    ("DELETE", "/api/members/{member_id}"),
    ("PUT", "/api/members/{member_id}/preferences"),
    ("PUT", "/api/post-priorities/{post_number}"),
}
MANAGER = {
    ("POST", "/api/sieges"),
    ("PUT", "/api/sieges/{siege_id}"),
    ("DELETE", "/api/sieges/{siege_id}"),
    ("POST", "/api/sieges/{siege_id}/buildings"),
    ("PUT", "/api/sieges/{siege_id}/buildings/{building_id}"),
    ("DELETE", "/api/sieges/{siege_id}/buildings/{building_id}"),
    ("POST", "/api/sieges/{siege_id}/buildings/{building_id}/groups"),
    ("DELETE", "/api/sieges/{siege_id}/buildings/{building_id}/groups/{group_id}"),
    ("POST", "/api/sieges/{siege_id}/members"),
    ("DELETE", "/api/sieges/{siege_id}/members/{member_id}"),
    ("PUT", "/api/sieges/{siege_id}/members/{member_id}"),
    ("PUT", "/api/sieges/{siege_id}/positions/{position_id}"),
    ("POST", "/api/sieges/{siege_id}/assignments/bulk"),
    ("POST", "/api/sieges/{siege_id}/activate"),
    ("POST", "/api/sieges/{siege_id}/complete"),
    ("POST", "/api/sieges/{siege_id}/reopen"),
    ("POST", "/api/sieges/{siege_id}/clone"),
    ("PUT", "/api/sieges/{siege_id}/posts/{post_id}"),
    ("PUT", "/api/sieges/{siege_id}/posts/{post_id}/conditions"),
    ("POST", "/api/sieges/{siege_id}/auto-fill"),
    ("POST", "/api/sieges/{siege_id}/auto-fill/apply"),
    ("POST", "/api/sieges/{siege_id}/post-suggestions"),
    ("POST", "/api/sieges/{siege_id}/post-suggestions/apply"),
    ("POST", "/api/sieges/{siege_id}/members/auto-assign-attack-day"),
    ("POST", "/api/sieges/{siege_id}/members/auto-assign-attack-day/apply"),
    ("POST", "/api/sieges/{siege_id}/notify"),
    ("POST", "/api/sieges/{siege_id}/post-to-channel"),
}
VIEWER = {
    ("GET", "/api/auth/me"),
    ("GET", "/api/scanner-observations/snapshots"),
    ("GET", "/api/scanner-observations/snapshots/latest"),
    ("GET", "/api/scanner-observations/snapshots/{snapshot_db_id}"),
    ("GET", "/api/building-types"),
    ("GET", "/api/member-roles"),
    ("GET", "/api/members"),
    ("GET", "/api/members/{member_id}"),
    ("GET", "/api/members/{member_id}/preferences"),
    ("GET", "/api/sieges"),
    ("GET", "/api/sieges/{siege_id}"),
    ("GET", "/api/sieges/{siege_id}/buildings"),
    ("GET", "/api/sieges/{siege_id}/members/preferences"),
    ("GET", "/api/sieges/{siege_id}/members"),
    ("GET", "/api/sieges/{siege_id}/board"),
    ("GET", "/api/sieges/{siege_id}/posts"),
    ("POST", "/api/sieges/{siege_id}/validate"),
    ("GET", "/api/sieges/{siege_id}/compare"),
    ("GET", "/api/sieges/{siege_id}/compare/{other_id}"),
    ("GET", "/api/changelog/status"),
    ("POST", "/api/changelog/mark-seen"),
    ("POST", "/api/sieges/{siege_id}/generate-images"),
    ("GET", "/api/sieges/{siege_id}/notify/{batch_id}"),
    ("GET", "/api/post-priorities"),
}


def _application_routes():
    for included in app.routes:
        if type(included).__name__ != "_IncludedRouter":
            continue
        prefix = included.include_context.prefix
        include_dependencies = [
            dependency.dependency for dependency in included.include_context.dependencies
        ]
        for route in included.original_router.routes:
            if not isinstance(route, APIRoute):
                continue
            route_dependencies = [item.call for item in route.dependant.dependencies]
            for method in route.methods:
                yield (method, prefix + route.path), include_dependencies + route_dependencies


def test_all_application_routes_have_the_classified_authorization_dependency():
    routes = dict(_application_routes())
    expected = PUBLIC | SCANNER | DUAL_BOT_VIEWER | VIEWER | MANAGER | ADMIN

    assert len(routes) == 73
    assert set(routes) == expected

    for key, dependencies in routes.items():
        names = {dependency.__name__ for dependency in dependencies}
        if key in PUBLIC:
            assert not names & {
                "get_current_user",
                "get_authenticated_scanner",
                "require_viewer",
                "require_manager",
                "require_admin",
                "require_bot_service_or_human_viewer",
            }
        elif key in SCANNER:
            assert "get_authenticated_scanner" in names
            assert not names & {
                "get_current_user",
                "require_viewer",
                "require_manager",
                "require_admin",
            }
        elif key in DUAL_BOT_VIEWER:
            assert "require_bot_service_or_human_viewer" in names
        elif key in VIEWER:
            assert "require_viewer" in names
        elif key in MANAGER:
            assert "require_manager" in names
        else:
            assert "require_admin" in names


def _principal(principal_type: str, app_role: str | None = None) -> AuthenticatedUser:
    return AuthenticatedUser(
        member_id=None,
        name=principal_type,
        is_service=principal_type == "bot_service",
        user_account_id=1 if principal_type == "human" else None,
        app_role=app_role,
        principal_type=principal_type,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("dependency", "principal", "allowed"),
    [
        (require_viewer, _principal("human", "viewer"), True),
        (require_viewer, _principal("human", "manager"), True),
        (require_viewer, _principal("human", "admin"), True),
        (require_manager, _principal("human", "viewer"), False),
        (require_manager, _principal("human", "manager"), True),
        (require_manager, _principal("human", "admin"), True),
        (require_admin, _principal("human", "manager"), False),
        (require_admin, _principal("human", "admin"), True),
        (require_viewer, _principal("bot_service"), False),
        (require_viewer, _principal("scanner"), False),
        (require_manager, _principal("development", "manager"), True),
        (require_admin, _principal("development", "manager"), False),
        (require_bot_service_or_human_viewer, _principal("bot_service"), True),
        (require_bot_service_or_human_viewer, _principal("human", "viewer"), True),
        (require_bot_service_or_human_viewer, _principal("scanner"), False),
    ],
)
async def test_role_and_principal_matrix(dependency, principal, allowed):
    if allowed:
        assert await dependency(principal) is principal
    else:
        with pytest.raises(HTTPException) as error:
            await dependency(principal)
        assert error.value.status_code == 403


@pytest.mark.asyncio
async def test_anonymous_cannot_read_human_viewer_endpoint(monkeypatch):
    monkeypatch.setattr("app.config.settings.auth_disabled", False)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/member-roles")
    assert response.status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["viewer", "manager", "admin"])
async def test_human_roles_can_read_viewer_endpoint(role):
    from app.dependencies.auth import get_current_user

    principal = _principal("human", role)

    async def override_current_user():
        return principal

    app.dependency_overrides[get_current_user] = override_current_user
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/member-roles")
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    assert response.status_code == 200


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["viewer", "manager", "admin"])
async def test_human_roles_can_read_post_conditions_catalog(role, monkeypatch):
    from app.dependencies.auth import get_current_user
    from app.services import reference as reference_service

    principal = _principal("human", role)

    async def override_current_user():
        return principal

    async def empty_catalog(_db, _stronghold_level):
        return []

    monkeypatch.setattr(reference_service, "get_post_conditions", empty_catalog)
    app.dependency_overrides[get_current_user] = override_current_user
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/post-conditions")
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_anonymous_cannot_read_post_conditions_catalog(monkeypatch):
    monkeypatch.setattr("app.config.settings.auth_disabled", False)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/post-conditions")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_development_principal_can_read_post_conditions_catalog(monkeypatch):
    from app.services import reference as reference_service

    async def empty_catalog(_db, _stronghold_level):
        return []

    monkeypatch.setattr(reference_service, "get_post_conditions", empty_catalog)
    monkeypatch.setattr("app.config.settings.auth_disabled", True)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/post-conditions")
    assert response.status_code == 200
    assert response.json() == []
