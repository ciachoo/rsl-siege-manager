"""Read-only Scanner observation API contract and authorization tests."""

from datetime import UTC, datetime, timedelta

import jwt
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.config import settings
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.scanner import ObservedBuilding, ObservedPost, ScannerIdentity, ScannerSnapshot
from app.models.siege import Siege
from app.models.user_account import UserAccount
from app.schemas.scanner import BuildingObservation, PostObservation, SnapshotEnvelope
from app.schemas.scanner_observations import (
    ObservedBuildingResponse,
    ObservedPostResponse,
    ScannerSnapshotDetail,
    ScannerSnapshotSummary,
)
from app.services.scanner import record_snapshot
from app.services.scanner_credentials import provision_scanner, revoke_scanner


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


def _envelope(
    scanner_id: str,
    snapshot_id: str,
    observed_at: datetime,
    *,
    siege_id: int | None = None,
    buildings: list[BuildingObservation] | None = None,
    posts: list[PostObservation] | None = None,
) -> SnapshotEnvelope:
    return SnapshotEnvelope(
        schema_version=1,
        snapshot_id=snapshot_id,
        scanner_id=scanner_id,
        scanner_version="read-api-test",
        observed_at=observed_at,
        siege_id=siege_id,
        cycle_ref="synthetic-cycle",
        buildings=buildings,
        posts=posts,
    )


async def _seed(db):
    monkey_accounts = []
    for index, role in enumerate(("viewer", "manager", "admin"), start=1):
        account = UserAccount(
            discord_user_id=f"12345678901234567{index}",
            display_name=role,
            app_role=role,
        )
        db.add(account)
        monkey_accounts.append(account)
    siege_one = Siege(defense_scroll_count=5)
    siege_two = Siege(defense_scroll_count=9)
    db.add_all([siege_one, siege_two])
    await db.commit()

    _, credential_a = await provision_scanner(db, "scanner-a")
    _, credential_b = await provision_scanner(db, "scanner-b")
    base = datetime(2026, 9, 16, 8, tzinfo=UTC)
    absent = await record_snapshot(
        db,
        _envelope("scanner-a", "shared-external-id", base),
    )
    empty = await record_snapshot(
        db,
        _envelope(
            "scanner-b",
            "shared-external-id",
            base + timedelta(hours=1),
            siege_id=siege_one.id,
            buildings=[],
            posts=[],
        ),
    )
    detail = await record_snapshot(
        db,
        _envelope(
            "scanner-a",
            "detail-evidence",
            base + timedelta(hours=2),
            siege_id=siege_one.id,
            buildings=[
                BuildingObservation(external_building_id="building-z", level=None, is_broken=None),
                BuildingObservation(external_building_id="building-a", level=2, is_broken=False),
            ],
            posts=[
                PostObservation(external_post_id="post-z", modifier_ids=None),
                PostObservation(
                    external_post_id="post-a", modifier_ids=["modifier-B", "modifier-A"]
                ),
            ],
        ),
    )
    latest = await record_snapshot(
        db,
        _envelope(
            "scanner-b",
            "latest-by-id-tiebreaker",
            base + timedelta(hours=2),
            siege_id=siege_two.id,
            buildings=[],
            posts=[],
        ),
    )
    await revoke_scanner(db, "scanner-a")
    return {
        "accounts": monkey_accounts,
        "credentials": (credential_a, credential_b),
        "sieges": (siege_one, siege_two),
        "snapshots": (absent, empty, detail, latest),
    }


async def _state(db) -> dict[str, list[tuple]]:
    tables = (
        Siege.__table__,
        ScannerIdentity.__table__,
        ScannerSnapshot.__table__,
        ObservedBuilding.__table__,
        ObservedPost.__table__,
    )
    state = {}
    for table in tables:
        rows = (await db.execute(select(table).order_by(*table.primary_key.columns))).all()
        state[table.name] = [tuple(row) for row in rows]
    return state


def _assert_safe(body) -> None:
    serialized = str(body).lower()
    for forbidden in (
        "credential",
        "credential_selector",
        "credential_verifier",
        "authorization",
        "content_digest",
        "secret",
        "token",
    ):
        assert forbidden not in serialized


@pytest.mark.asyncio
async def test_human_roles_can_list_latest_and_detail_without_mutation(db, monkeypatch):
    monkeypatch.setattr(settings, "auth_disabled", False)
    monkeypatch.setattr(settings, "session_secret", "task-eight-session-secret-at-least-32-bytes")
    seeded = await _seed(db)
    detail = seeded["snapshots"][2]
    state_before = await _state(db)

    for account in seeded["accounts"]:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            client.cookies.set("session", _session_token(account))
            listed = await client.get("/api/scanner-observations/snapshots")
            latest = await client.get("/api/scanner-observations/snapshots/latest")
            detailed = await client.get(f"/api/scanner-observations/snapshots/{detail.id}")
        assert listed.status_code == latest.status_code == detailed.status_code == 200
        assert len(listed.json()) == 4
        assert latest.json()["snapshot_id"] == "latest-by-id-tiebreaker"
        assert detailed.json()["snapshot_id"] == "detail-evidence"
        _assert_safe(listed.json())
        _assert_safe(latest.json())
        _assert_safe(detailed.json())

    assert await _state(db) == state_before


@pytest.mark.asyncio
async def test_list_pagination_filters_and_summary_shape(db, monkeypatch):
    monkeypatch.setattr(settings, "auth_disabled", True)
    seeded = await _seed(db)
    absent, empty, detail, latest = seeded["snapshots"]
    siege_one, _ = seeded["sieges"]

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        page = await client.get(
            "/api/scanner-observations/snapshots", params={"limit": 2, "offset": 1}
        )
        scanner_a = await client.get(
            "/api/scanner-observations/snapshots", params={"scanner_id": "scanner-a"}
        )
        siege = await client.get(
            "/api/scanner-observations/snapshots", params={"siege_id": siege_one.id}
        )
        unmatched = await client.get(
            "/api/scanner-observations/snapshots",
            params={"association_status": "unmatched"},
        )
        unknown = await client.get(
            "/api/scanner-observations/snapshots", params={"scanner_id": "unknown"}
        )
        excessive_limit = await client.get(
            "/api/scanner-observations/snapshots", params={"limit": 101}
        )
        invalid_association = await client.get(
            "/api/scanner-observations/snapshots",
            params={"association_status": "guessed"},
        )

    assert [row["id"] for row in page.json()] == [detail.id, empty.id]
    assert [row["id"] for row in scanner_a.json()] == [detail.id, absent.id]
    assert [row["id"] for row in siege.json()] == [detail.id, empty.id]
    assert [row["id"] for row in unmatched.json()] == [absent.id]
    assert unknown.json() == []
    assert excessive_limit.status_code == 422
    assert invalid_association.status_code == 422
    assert [row["id"] for row in page.json()] != [latest.id, detail.id]
    for row in page.json():
        assert "buildings" not in row and "posts" not in row
        _assert_safe(row)


@pytest.mark.asyncio
async def test_latest_filters_are_deterministic_and_missing_is_404(db, monkeypatch):
    monkeypatch.setattr(settings, "auth_disabled", True)
    seeded = await _seed(db)
    absent, _, detail, latest = seeded["snapshots"]
    siege_one, _ = seeded["sieges"]

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        global_latest = await client.get("/api/scanner-observations/snapshots/latest")
        scanner_latest = await client.get(
            "/api/scanner-observations/snapshots/latest",
            params={"scanner_id": "scanner-a"},
        )
        siege_latest = await client.get(
            "/api/scanner-observations/snapshots/latest",
            params={"siege_id": siege_one.id},
        )
        unmatched_latest = await client.get(
            "/api/scanner-observations/snapshots/latest",
            params={"association_status": "unmatched"},
        )
        missing = await client.get(
            "/api/scanner-observations/snapshots/latest",
            params={"scanner_id": "unknown"},
        )
        missing_detail = await client.get("/api/scanner-observations/snapshots/99999")

    assert global_latest.json()["id"] == latest.id
    assert scanner_latest.json()["id"] == detail.id
    assert siege_latest.json()["id"] == detail.id
    assert unmatched_latest.json()["id"] == absent.id
    assert missing.status_code == missing_detail.status_code == 404


@pytest.mark.asyncio
async def test_detail_preserves_presence_unknown_false_empty_and_modifier_order(db, monkeypatch):
    monkeypatch.setattr(settings, "auth_disabled", True)
    seeded = await _seed(db)
    absent, empty, detail, _ = seeded["snapshots"]

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        absent_body = (await client.get(f"/api/scanner-observations/snapshots/{absent.id}")).json()
        empty_body = (await client.get(f"/api/scanner-observations/snapshots/{empty.id}")).json()
        detail_body = (await client.get(f"/api/scanner-observations/snapshots/{detail.id}")).json()

    assert absent_body["buildings_present"] is False
    assert absent_body["posts_present"] is False
    assert absent_body["buildings"] == absent_body["posts"] == []
    assert empty_body["buildings_present"] is True
    assert empty_body["posts_present"] is True
    assert empty_body["buildings"] == empty_body["posts"] == []
    assert [row["external_building_id"] for row in detail_body["buildings"]] == [
        "building-a",
        "building-z",
    ]
    assert detail_body["buildings"][0]["is_broken"] is False
    assert detail_body["buildings"][1]["level"] is None
    assert detail_body["buildings"][1]["is_broken"] is None
    assert [row["external_post_id"] for row in detail_body["posts"]] == [
        "post-a",
        "post-z",
    ]
    assert detail_body["posts"][0]["modifier_ids"] == ["modifier-B", "modifier-A"]
    assert detail_body["posts"][1]["modifier_ids"] is None


@pytest.mark.asyncio
async def test_anonymous_scanner_and_bot_are_denied_but_development_read_is_allowed(
    db, monkeypatch
):
    monkeypatch.setattr(settings, "auth_disabled", False)
    monkeypatch.setattr(settings, "bot_service_token", "synthetic-bot-token")
    seeded = await _seed(db)
    scanner_credential = seeded["credentials"][1]
    path = "/api/scanner-observations/snapshots"

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get(path)).status_code == 401
        scanner = await client.get(path, headers={"Authorization": f"Bearer {scanner_credential}"})
        bot = await client.get(path, headers={"Authorization": "Bearer synthetic-bot-token"})
        assert scanner.status_code == 401
        assert bot.status_code == 403

    monkeypatch.setattr(settings, "auth_disabled", True)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get(path)).status_code == 200


@pytest.mark.asyncio
async def test_same_external_snapshot_id_is_scoped_to_scanner_identity(db, monkeypatch):
    monkeypatch.setattr(settings, "auth_disabled", True)
    await _seed(db)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/scanner-observations/snapshots")
    shared = [row for row in response.json() if row["snapshot_id"] == "shared-external-id"]
    assert len(shared) == 2
    assert {row["scanner_id"] for row in shared} == {"scanner-a", "scanner-b"}
    assert shared[0]["id"] != shared[1]["id"]


def test_response_models_explicitly_exclude_auth_and_internal_digest_fields():
    schemas = (
        ScannerSnapshotSummary,
        ScannerSnapshotDetail,
        ObservedBuildingResponse,
        ObservedPostResponse,
    )
    forbidden = {
        "credential",
        "credential_selector",
        "credential_verifier",
        "credential_revoked_at",
        "authorization",
        "content_digest",
        "secret",
        "token",
    }
    for schema in schemas:
        assert forbidden.isdisjoint(schema.model_fields)
