"""ADMIN-only Scanner provisioning and credential lifecycle regressions."""

from datetime import UTC, datetime, timedelta

import jwt
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.config import settings
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.scanner import ScannerIdentity, ScannerSnapshot
from app.models.user_account import UserAccount
from app.schemas.scanner_admin import ScannerCredentialIssued, ScannerMetadata
from app.services.scanner_credentials import provision_scanner


@pytest.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    event.listen(
        engine.sync_engine,
        "connect",
        lambda conn, _: conn.execute("PRAGMA foreign_keys=ON"),
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:

        async def override_db():
            yield session

        app.dependency_overrides[get_db] = override_db
        try:
            yield session
        finally:
            app.dependency_overrides.pop(get_db, None)
    await engine.dispose()


def _session_token(account: UserAccount) -> str:
    return jwt.encode(
        {
            "typ": "manager-user-v2",
            "sub": str(account.id),
            "iat": datetime.now(UTC),
            "exp": datetime.now(UTC) + timedelta(hours=1),
        },
        settings.session_secret,
        algorithm="HS256",
    )


async def _account(db, role: str, suffix: str) -> UserAccount:
    account = UserAccount(
        discord_user_id=f"1234567890123456{suffix}",
        display_name=role,
        app_role=role,
    )
    db.add(account)
    await db.commit()
    return account


def _snapshot(scanner_id: str, snapshot_id: str) -> dict:
    return {
        "schema_version": 1,
        "snapshot_id": snapshot_id,
        "scanner_id": scanner_id,
        "scanner_version": "test",
        "observed_at": datetime.now(UTC).isoformat(),
        "buildings": [],
        "posts": [],
    }


async def _ingest(scanner_id: str, snapshot_id: str, credential: str):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.post(
            "/api/scanner/snapshots",
            json=_snapshot(scanner_id, snapshot_id),
            headers={"Authorization": f"Bearer {credential}"},
        )


@pytest.mark.asyncio
async def test_admin_create_rotate_revoke_preserves_identity_and_history(db, monkeypatch):
    monkeypatch.setattr(settings, "auth_disabled", False)
    monkeypatch.setattr(settings, "session_secret", "task-six-test-session-secret-32-bytes")
    admin = await _account(db, "admin", "01")
    origin = settings.allowed_origins.split(",")[0].strip()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        client.cookies.set("session", _session_token(admin))
        created = await client.post(
            "/api/scanners",
            json={"scanner_id": "ciachoo-main"},
            headers={"Origin": origin},
        )
        assert created.status_code == 201
        created_body = created.json()
        credential = created_body.pop("credential")
        assert credential.startswith("ssm_scanner_")
        assert created_body["scanner"]["id"] == "ciachoo-main"
        assert created_body["scanner"]["is_active"] is True
        duplicate = await client.post(
            "/api/scanners",
            json={"scanner_id": "ciachoo-main"},
            headers={"Origin": origin},
        )
        assert duplicate.status_code == 409

        scanner = await db.get(ScannerIdentity, "ciachoo-main")
        assert scanner is not None
        assert scanner.credential_verifier is not None
        assert credential != scanner.credential_verifier
        assert credential not in scanner.credential_verifier

        listed = await client.get("/api/scanners")
        detail = await client.get("/api/scanners/ciachoo-main")
        assert listed.status_code == detail.status_code == 200
        assert listed.json() == [detail.json()]
        assert "credential" not in detail.json()
        assert "credential_selector" not in detail.json()
        assert "credential_verifier" not in detail.json()
        assert credential not in detail.text

        accepted = await _ingest("ciachoo-main", "before-rotation", credential)
        assert accepted.status_code == 201
        assert (await _ingest("ciachoo-main", "bad-credential", "wrong")).status_code == 401

        rotated = await client.post(
            "/api/scanners/ciachoo-main/rotate-credential",
            headers={"Origin": origin},
        )
        assert rotated.status_code == 200
        rotated_body = rotated.json()
        new_credential = rotated_body.pop("credential")
        assert new_credential != credential
        assert rotated_body["scanner"]["id"] == "ciachoo-main"
        assert (await _ingest("ciachoo-main", "old-after-rotation", credential)).status_code == 401
        assert (await _ingest("ciachoo-main", "after-rotation", new_credential)).status_code == 201
        assert new_credential not in (await client.get("/api/scanners/ciachoo-main")).text

        revoked = await client.post(
            "/api/scanners/ciachoo-main/revoke",
            headers={"Origin": origin},
        )
        assert revoked.status_code == 200
        assert revoked.json()["is_active"] is False
        first_revoked_at = revoked.json()["credential_revoked_at"]
        repeated = await client.post(
            "/api/scanners/ciachoo-main/revoke",
            headers={"Origin": origin},
        )
        assert repeated.status_code == 200
        assert repeated.json()["credential_revoked_at"] == first_revoked_at
        assert (await _ingest("ciachoo-main", "after-revoke", new_credential)).status_code == 401

    snapshot_count = await db.scalar(select(func.count()).select_from(ScannerSnapshot))
    assert snapshot_count == 2
    assert (await db.get(ScannerIdentity, "ciachoo-main")).id == "ciachoo-main"


@pytest.mark.asyncio
async def test_admin_unknown_scanner_operations_return_404(db, monkeypatch):
    monkeypatch.setattr(settings, "auth_disabled", False)
    monkeypatch.setattr(settings, "session_secret", "task-six-test-session-secret-32-bytes")
    admin = await _account(db, "admin", "02")
    origin = settings.allowed_origins.split(",")[0].strip()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        client.cookies.set("session", _session_token(admin))
        assert (await client.get("/api/scanners/missing")).status_code == 404
        assert (
            await client.post(
                "/api/scanners/missing/rotate-credential",
                headers={"Origin": origin},
            )
        ).status_code == 404
        assert (
            await client.post(
                "/api/scanners/missing/revoke",
                headers={"Origin": origin},
            )
        ).status_code == 404


@pytest.mark.asyncio
async def test_concurrent_provisioning_conflict_returns_409(db, monkeypatch):
    monkeypatch.setattr(settings, "auth_disabled", False)
    monkeypatch.setattr(settings, "session_secret", "task-six-test-session-secret-32-bytes")
    admin = await _account(db, "admin", "03")
    origin = settings.allowed_origins.split(",")[0].strip()

    async def conflicting_provision(*_args, **_kwargs):
        raise IntegrityError("INSERT", {}, Exception("duplicate scanner identity"))

    monkeypatch.setattr("app.api.scanner_admin.provision_scanner", conflicting_provision)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        client.cookies.set("session", _session_token(admin))
        response = await client.post(
            "/api/scanners",
            json={"scanner_id": "concurrent-scanner"},
            headers={"Origin": origin},
        )

    assert response.status_code == 409
    assert response.json() == {"detail": "Scanner provisioning conflict"}


@pytest.mark.asyncio
async def test_admin_routes_reject_every_non_admin_principal(db, monkeypatch):
    monkeypatch.setattr(settings, "auth_disabled", False)
    monkeypatch.setattr(settings, "session_secret", "task-six-test-session-secret-32-bytes")
    monkeypatch.setattr(settings, "bot_service_token", "bot-example")
    viewer = await _account(db, "viewer", "11")
    manager = await _account(db, "manager", "12")
    _, scanner_credential = await provision_scanner(db, "existing-scanner")
    origin = settings.allowed_origins.split(",")[0].strip()

    routes = [
        ("POST", "/api/scanners", {"scanner_id": "denied"}),
        ("GET", "/api/scanners", None),
        ("GET", "/api/scanners/existing-scanner", None),
        ("POST", "/api/scanners/existing-scanner/rotate-credential", None),
        ("POST", "/api/scanners/existing-scanner/revoke", None),
    ]
    principals = [
        ({}, None),
        ({"Authorization": "Bearer bot-example"}, None),
        ({"Authorization": f"Bearer {scanner_credential}"}, None),
        ({"Origin": origin}, _session_token(viewer)),
        ({"Origin": origin}, _session_token(manager)),
    ]
    for method, path, body in routes:
        for headers, cookie in principals:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                if cookie is not None:
                    client.cookies.set("session", cookie)
                response = await client.request(method, path, json=body, headers=headers)
                assert response.status_code in {401, 403}, (
                    method,
                    path,
                    response.status_code,
                )

    monkeypatch.setattr(settings, "auth_disabled", True)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        for method, path, body in routes:
            response = await client.request(method, path, json=body)
            assert response.status_code == 403


@pytest.mark.asyncio
async def test_admin_session_is_not_a_scanner_credential(db, monkeypatch):
    monkeypatch.setattr(settings, "auth_disabled", False)
    monkeypatch.setattr(settings, "session_secret", "task-six-test-session-secret-32-bytes")
    admin = await _account(db, "admin", "21")
    origin = settings.allowed_origins.split(",")[0].strip()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        client.cookies.set("session", _session_token(admin))
        response = await client.post(
            "/api/scanner/snapshots",
            json=_snapshot("missing", "human-session"),
            headers={"Origin": origin},
        )
    assert response.status_code == 401


def test_credential_response_repr_and_safe_metadata_hide_secrets():
    metadata = ScannerMetadata(
        id="scanner-one",
        created_at=datetime.now(UTC),
        credential_revoked_at=None,
        is_active=True,
    )
    response = ScannerCredentialIssued(scanner=metadata, credential="plaintext-secret")
    assert "plaintext-secret" not in repr(response)
    assert "credential_selector" not in ScannerMetadata.model_fields
    assert "credential_verifier" not in ScannerMetadata.model_fields
    assert "secret" not in ScannerMetadata.model_fields
