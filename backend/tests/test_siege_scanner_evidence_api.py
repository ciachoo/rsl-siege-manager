"""Read-only Scanner evidence projection in one explicit Siege context."""

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
from app.models.building import Building
from app.models.building_group import BuildingGroup
from app.models.enums import BuildingType, MemberRole
from app.models.member import Member
from app.models.member_post_preference import member_post_preference
from app.models.position import Position
from app.models.post import Post
from app.models.post_active_condition import post_active_condition
from app.models.post_condition import PostCondition
from app.models.scanner import ObservedBuilding, ObservedPost, ScannerIdentity, ScannerSnapshot
from app.models.siege import Siege
from app.models.siege_member import SiegeMember
from app.models.user_account import UserAccount
from app.schemas.scanner import BuildingObservation, PostObservation, SnapshotEnvelope
from app.schemas.siege_scanner_evidence import (
    SiegeEvidenceSourceSnapshot,
    SiegeScannerEvidenceResponse,
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
        scanner_version=f"{scanner_id}-version",
        observed_at=observed_at,
        siege_id=siege_id,
        cycle_ref="synthetic-cycle",
        buildings=buildings,
        posts=posts,
    )


async def _seed(db):
    accounts = []
    for index, role in enumerate(("viewer", "manager", "admin"), start=1):
        account = UserAccount(
            discord_user_id=f"22345678901234567{index}",
            display_name=role,
            app_role=role,
        )
        db.add(account)
        accounts.append(account)

    target = Siege(defense_scroll_count=7)
    no_evidence = Siege(defense_scroll_count=0)
    absent = Siege(defense_scroll_count=1)
    empty = Siege(defense_scroll_count=2)
    other = Siege(defense_scroll_count=3)
    member = Member(name="Planned Member", role=MemberRole.advanced)
    condition = PostCondition(
        description="Planned condition", stronghold_level=1, condition_type="other"
    )
    db.add_all([target, no_evidence, absent, empty, other, member, condition])
    await db.flush()
    building = Building(
        siege_id=target.id,
        building_type=BuildingType.post,
        building_number=1,
        level=3,
        is_broken=False,
    )
    db.add(building)
    await db.flush()
    group = BuildingGroup(building_id=building.id, group_number=1, slot_count=1)
    post = Post(siege_id=target.id, building_id=building.id, priority=5)
    db.add_all([group, post])
    await db.flush()
    db.add_all(
        [
            Position(
                building_group_id=group.id,
                position_number=1,
                member_id=member.id,
                matched_condition_id=condition.id,
            ),
            SiegeMember(
                siege_id=target.id,
                member_id=member.id,
                attack_day=1,
                has_reserve_set=False,
            ),
        ]
    )
    await db.execute(
        post_active_condition.insert().values(post_id=post.id, post_condition_id=condition.id)
    )
    await db.execute(
        member_post_preference.insert().values(member_id=member.id, post_condition_id=condition.id)
    )
    await db.commit()

    _, credential_a = await provision_scanner(db, "scanner-a")
    _, credential_b = await provision_scanner(db, "scanner-b")
    base = datetime(2026, 9, 16, 10, tzinfo=UTC)
    unmatched = await record_snapshot(
        db,
        _envelope(
            "scanner-a",
            "unmatched-newer",
            base + timedelta(hours=5),
            buildings=[],
            posts=[],
        ),
    )
    other_snapshot = await record_snapshot(
        db,
        _envelope(
            "scanner-a",
            "other-siege-newer",
            base + timedelta(hours=4),
            siege_id=other.id,
            buildings=[],
            posts=[],
        ),
    )
    older = await record_snapshot(
        db,
        _envelope(
            "scanner-a",
            "target-older",
            base,
            siege_id=target.id,
            buildings=[],
            posts=[],
        ),
    )
    tie_lower = await record_snapshot(
        db,
        _envelope(
            "scanner-a",
            "target-tie-lower-id",
            base + timedelta(hours=1),
            siege_id=target.id,
            buildings=[],
            posts=[],
        ),
    )
    tie_winner = await record_snapshot(
        db,
        _envelope(
            "scanner-b",
            "target-tie-higher-id",
            base + timedelta(hours=1),
            siege_id=target.id,
            buildings=[
                BuildingObservation(external_building_id="building-z", level=None, is_broken=None),
                BuildingObservation(external_building_id="building-a", level=2, is_broken=False),
            ],
            posts=[
                PostObservation(external_post_id="post-z", modifier_ids=None),
                PostObservation(external_post_id="post-m", modifier_ids=[]),
                PostObservation(
                    external_post_id="post-a", modifier_ids=["modifier-B", "modifier-A"]
                ),
            ],
        ),
    )
    late_insert_old_observation = await record_snapshot(
        db,
        _envelope(
            "scanner-a",
            "target-late-insert-old-observation",
            base - timedelta(hours=1),
            siege_id=target.id,
            buildings=[],
            posts=[],
        ),
    )
    absent_snapshot = await record_snapshot(
        db,
        _envelope("scanner-a", "categories-absent", base, siege_id=absent.id),
    )
    empty_snapshot = await record_snapshot(
        db,
        _envelope(
            "scanner-a",
            "categories-empty",
            base,
            siege_id=empty.id,
            buildings=[],
            posts=[],
        ),
    )
    await revoke_scanner(db, "scanner-b")
    return {
        "accounts": accounts,
        "credentials": (credential_a, credential_b),
        "sieges": (target, no_evidence, absent, empty, other),
        "snapshots": (
            unmatched,
            other_snapshot,
            older,
            tie_lower,
            tie_winner,
            late_insert_old_observation,
            absent_snapshot,
            empty_snapshot,
        ),
    }


async def _state(db) -> dict[str, list[tuple]]:
    tables = (
        Siege.__table__,
        Building.__table__,
        BuildingGroup.__table__,
        Position.__table__,
        Post.__table__,
        PostCondition.__table__,
        Member.__table__,
        SiegeMember.__table__,
        post_active_condition,
        member_post_preference,
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
        "credential_revoked_at",
        "authorization",
        "content_digest",
        "secret",
        "token",
    ):
        assert forbidden not in serialized


@pytest.mark.asyncio
async def test_existing_siege_without_evidence_is_distinct_from_unknown_siege(db, monkeypatch):
    monkeypatch.setattr(settings, "auth_disabled", True)
    seeded = await _seed(db)
    no_evidence = seeded["sieges"][1]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/sieges/{no_evidence.id}/scanner-evidence")
        missing = await client.get("/api/sieges/99999/scanner-evidence")
        invalid = await client.get("/api/sieges/not-an-integer/scanner-evidence")

    assert response.status_code == 200
    assert response.json() == {
        "siege_id": no_evidence.id,
        "has_evidence": False,
        "source_snapshot": None,
        "buildings_present": None,
        "posts_present": None,
        "buildings": [],
        "posts": [],
    }
    assert missing.status_code == 404
    assert invalid.status_code == 422


@pytest.mark.asyncio
async def test_projection_uses_latest_explicit_match_across_scanners_and_revoked_history(
    db, monkeypatch
):
    monkeypatch.setattr(settings, "auth_disabled", True)
    seeded = await _seed(db)
    target = seeded["sieges"][0]
    (
        unmatched,
        other_snapshot,
        older,
        tie_lower,
        tie_winner,
        late_insert_old_observation,
        _,
        _,
    ) = seeded["snapshots"]
    tie_lower.received_at = datetime(2026, 9, 16, 20, tzinfo=UTC)
    tie_winner.received_at = datetime(2026, 9, 16, 19, tzinfo=UTC)
    await db.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/sieges/{target.id}/scanner-evidence")

    assert response.status_code == 200
    body = response.json()
    assert body["has_evidence"] is True
    assert body["siege_id"] == target.id
    assert body["source_snapshot"]["id"] == tie_winner.id
    assert body["source_snapshot"]["snapshot_id"] == "target-tie-higher-id"
    assert body["source_snapshot"]["scanner_id"] == "scanner-b"
    assert body["source_snapshot"]["scanner_version"] == "scanner-b-version"
    assert body["source_snapshot"]["schema_version"] == 1
    assert body["source_snapshot"]["cycle_ref"] == "synthetic-cycle"
    assert tie_winner.id > tie_lower.id
    assert tie_lower.received_at > tie_winner.received_at
    assert late_insert_old_observation.id > tie_winner.id
    assert body["source_snapshot"]["id"] not in {
        unmatched.id,
        other_snapshot.id,
        older.id,
        late_insert_old_observation.id,
    }
    scanner_b = await db.get(ScannerIdentity, "scanner-b")
    assert scanner_b.credential_revoked_at is not None
    _assert_safe(body)


@pytest.mark.asyncio
async def test_projection_preserves_presence_unknown_empty_false_and_modifier_order(
    db, monkeypatch
):
    monkeypatch.setattr(settings, "auth_disabled", True)
    seeded = await _seed(db)
    target, _, absent, empty, _ = seeded["sieges"]

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        target_body = (await client.get(f"/api/sieges/{target.id}/scanner-evidence")).json()
        absent_body = (await client.get(f"/api/sieges/{absent.id}/scanner-evidence")).json()
        empty_body = (await client.get(f"/api/sieges/{empty.id}/scanner-evidence")).json()

    assert absent_body["buildings_present"] is False
    assert absent_body["posts_present"] is False
    assert absent_body["buildings"] == absent_body["posts"] == []
    assert empty_body["buildings_present"] is True
    assert empty_body["posts_present"] is True
    assert empty_body["buildings"] == empty_body["posts"] == []
    assert target_body["buildings_present"] is True
    assert target_body["posts_present"] is True
    assert [row["external_building_id"] for row in target_body["buildings"]] == [
        "building-a",
        "building-z",
    ]
    assert target_body["buildings"][0]["is_broken"] is False
    assert target_body["buildings"][1]["level"] is None
    assert target_body["buildings"][1]["is_broken"] is None
    assert [row["external_post_id"] for row in target_body["posts"]] == [
        "post-a",
        "post-m",
        "post-z",
    ]
    assert target_body["posts"][0]["modifier_ids"] == ["modifier-B", "modifier-A"]
    assert target_body["posts"][1]["modifier_ids"] == []
    assert target_body["posts"][2]["modifier_ids"] is None


@pytest.mark.asyncio
async def test_human_roles_can_read_projection_without_any_persistence_mutation(db, monkeypatch):
    monkeypatch.setattr(settings, "auth_disabled", False)
    monkeypatch.setattr(settings, "session_secret", "task-nine-session-secret-at-least-32-bytes")
    seeded = await _seed(db)
    target = seeded["sieges"][0]
    state_before = await _state(db)

    for account in seeded["accounts"]:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            client.cookies.set("session", _session_token(account))
            response = await client.get(f"/api/sieges/{target.id}/scanner-evidence")
        assert response.status_code == 200
        assert response.json()["has_evidence"] is True

    assert await _state(db) == state_before


@pytest.mark.asyncio
async def test_anonymous_scanner_and_bot_principals_are_denied(db, monkeypatch):
    monkeypatch.setattr(settings, "auth_disabled", False)
    monkeypatch.setattr(settings, "bot_service_token", "synthetic-bot-token")
    seeded = await _seed(db)
    target = seeded["sieges"][0]
    scanner_credential = seeded["credentials"][0]
    path = f"/api/sieges/{target.id}/scanner-evidence"

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get(path)).status_code == 401
        scanner = await client.get(path, headers={"Authorization": f"Bearer {scanner_credential}"})
        bot = await client.get(path, headers={"Authorization": "Bearer synthetic-bot-token"})
    assert scanner.status_code == 401
    assert bot.status_code == 403


def test_projection_response_models_exclude_credentials_digest_and_auth_fields():
    forbidden = {
        "credential",
        "credential_selector",
        "credential_verifier",
        "credential_revoked_at",
        "content_digest",
        "authorization",
        "secret",
        "token",
    }
    assert forbidden.isdisjoint(SiegeEvidenceSourceSnapshot.model_fields)
    assert forbidden.isdisjoint(SiegeScannerEvidenceResponse.model_fields)
