"""First authenticated Scanner-to-Manager HTTP contract."""

from datetime import UTC, datetime, timedelta

import jwt
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, func, select
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


def _snapshot(scanner_id: str, snapshot_id: str, siege_id: int | None) -> dict:
    return {
        "schema_version": 1,
        "snapshot_id": snapshot_id,
        "scanner_id": scanner_id,
        "scanner_version": "windows-client-contract-test",
        "observed_at": datetime.now(UTC).isoformat(),
        "siege_id": siege_id,
        "cycle_ref": "synthetic-cycle-2026-09",
        "buildings": [
            {
                "external_building_id": "raid-building-3001",
                "level": 1,
                "is_broken": True,
            }
        ],
        "posts": [
            {
                "external_post_id": "raid-post-3001",
                "modifier_ids": ["modifier-B", "modifier-A"],
            }
        ],
    }


async def _seed_planning_state(db) -> tuple[Siege, UserAccount]:
    siege = Siege(defense_scroll_count=7)
    member = Member(name="Planned Member", role=MemberRole.advanced, power_level="16_20m")
    condition = PostCondition(
        description="Planned condition", stronghold_level=1, condition_type="other"
    )
    admin = UserAccount(
        discord_user_id="123456789012345678",
        display_name="Task Seven Admin",
        app_role="admin",
    )
    db.add_all([siege, member, condition, admin])
    await db.flush()
    building = Building(
        siege_id=siege.id,
        building_type=BuildingType.post,
        building_number=1,
        level=3,
        is_broken=False,
    )
    db.add(building)
    await db.flush()
    group = BuildingGroup(building_id=building.id, group_number=1, slot_count=1)
    post = Post(siege_id=siege.id, building_id=building.id, priority=9)
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
                siege_id=siege.id,
                member_id=member.id,
                attack_day=2,
                has_reserve_set=True,
                attack_day_override=True,
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
    return siege, admin


async def _planning_state(db) -> dict[str, list[tuple]]:
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
    )
    state = {}
    for table in tables:
        order = list(table.primary_key.columns)
        rows = (await db.execute(select(table).order_by(*order))).all()
        state[table.name] = [tuple(row) for row in rows]
    return state


@pytest.mark.asyncio
async def test_admin_provisions_authenticated_scanner_and_evidence_stays_isolated(db, monkeypatch):
    monkeypatch.setattr(settings, "auth_disabled", False)
    monkeypatch.setattr(settings, "session_secret", "task-seven-session-secret-at-least-32-bytes")
    siege, admin = await _seed_planning_state(db)
    planning_before = await _planning_state(db)
    origin = settings.allowed_origins.split(",")[0].strip()

    async with (
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as admin_client,
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as scanner_client,
    ):
        admin_client.cookies.set("session", _session_token(admin))
        provisioned = await admin_client.post(
            "/api/scanners",
            json={"scanner_id": "windows-scanner-one"},
            headers={"Origin": origin},
        )
        assert provisioned.status_code == 201
        credential_one = provisioned.json()["credential"]

        body = _snapshot("windows-scanner-one", "snapshot-one", siege.id)
        created = await scanner_client.post(
            "/api/scanner/snapshots",
            json=body,
            headers={"Authorization": f"Bearer {credential_one}"},
        )
        assert created.status_code == 201
        assert created.json()["status"] == "created"
        assert created.json()["association_status"] == "matched"
        assert created.json()["siege_id"] == siege.id

        retried = await scanner_client.post(
            "/api/scanner/snapshots",
            json=body,
            headers={"Authorization": f"Bearer {credential_one}"},
        )
        assert retried.status_code == 200
        assert retried.json()["status"] == "duplicate"
        assert retried.json()["snapshot_id"] == created.json()["snapshot_id"]
        assert retried.json()["siege_id"] == created.json()["siege_id"]

        rotated = await admin_client.post(
            "/api/scanners/windows-scanner-one/rotate-credential",
            headers={"Origin": origin},
        )
        assert rotated.status_code == 200
        credential_two = rotated.json()["credential"]
        assert credential_two != credential_one
        assert (
            await scanner_client.post(
                "/api/scanner/snapshots",
                json=_snapshot("windows-scanner-one", "old-credential", siege.id),
                headers={"Authorization": f"Bearer {credential_one}"},
            )
        ).status_code == 401
        assert (
            await scanner_client.post(
                "/api/scanner/snapshots",
                json=_snapshot("windows-scanner-one", "snapshot-two", siege.id),
                headers={"Authorization": f"Bearer {credential_two}"},
            )
        ).status_code == 201

        revoked = await admin_client.post(
            "/api/scanners/windows-scanner-one/revoke",
            headers={"Origin": origin},
        )
        assert revoked.status_code == 200
        assert (
            await scanner_client.post(
                "/api/scanner/snapshots",
                json=_snapshot("windows-scanner-one", "revoked-credential", siege.id),
                headers={"Authorization": f"Bearer {credential_two}"},
            )
        ).status_code == 401

    assert await db.scalar(select(func.count()).select_from(ScannerIdentity)) == 1
    assert await db.scalar(select(func.count()).select_from(ScannerSnapshot)) == 2
    assert await db.scalar(select(func.count()).select_from(ObservedBuilding)) == 2
    assert await db.scalar(select(func.count()).select_from(ObservedPost)) == 2
    posts = (await db.execute(select(ObservedPost).order_by(ObservedPost.id))).scalars().all()
    assert [post.modifier_ids for post in posts] == [
        ["modifier-B", "modifier-A"],
        ["modifier-B", "modifier-A"],
    ]
    scanner = await db.get(ScannerIdentity, "windows-scanner-one")
    assert scanner is not None and scanner.credential_revoked_at is not None
    assert await _planning_state(db) == planning_before


@pytest.mark.asyncio
async def test_scanner_http_failure_contract(db, monkeypatch):
    monkeypatch.setattr(settings, "auth_disabled", False)
    _, credential = await provision_scanner(db, "failure-contract")
    valid = _snapshot("failure-contract", "failure-base", None)
    selector = credential.removeprefix("ssm_scanner_").split(".", 1)[0]

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.post("/api/scanner/snapshots", json=valid)).status_code == 401
        assert (
            await client.post(
                "/api/scanner/snapshots",
                json=valid,
                headers={"Authorization": "Bearer malformed"},
            )
        ).status_code == 401
        assert (
            await client.post(
                "/api/scanner/snapshots",
                json=valid,
                headers={"Authorization": f"Bearer ssm_scanner_{'0' * 32}.synthetic-secret"},
            )
        ).status_code == 401
        assert (
            await client.post(
                "/api/scanner/snapshots",
                json=valid,
                headers={"Authorization": f"Bearer ssm_scanner_{selector}.wrong-secret"},
            )
        ).status_code == 401
        malformed_json = await client.post(
            "/api/scanner/snapshots",
            content=b"{not-json",
            headers={"Authorization": f"Bearer {credential}"},
        )
        assert malformed_json.status_code == 422
        invalid_schema = await client.post(
            "/api/scanner/snapshots",
            json={"schema_version": 1},
            headers={"Authorization": f"Bearer {credential}"},
        )
        assert invalid_schema.status_code == 422
        oversized = await client.post(
            "/api/scanner/snapshots",
            content=b"x" * (256 * 1024 + 1),
            headers={"Authorization": f"Bearer {credential}"},
        )
        assert oversized.status_code == 413
