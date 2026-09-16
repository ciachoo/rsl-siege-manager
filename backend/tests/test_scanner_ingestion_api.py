"""Scanner credentials are independent of browser and bot authentication."""

from datetime import UTC, datetime, timedelta

import jwt
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.config import settings
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.building import Building
from app.models.enums import BuildingType, MemberRole
from app.models.member import Member
from app.models.post import Post
from app.models.post_active_condition import post_active_condition
from app.models.post_condition import PostCondition
from app.models.scanner import ObservedBuilding, ObservedPost, ScannerIdentity, ScannerSnapshot
from app.models.siege import Siege
from app.models.user_account import UserAccount
from app.schemas.scanner import SnapshotEnvelope
from app.services.scanner import record_snapshot_with_status
from app.services.scanner_credentials import (
    authenticate_scanner,
    provision_scanner,
    revoke_scanner,
    rotate_scanner_credential,
)


@pytest.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    event.listen(
        engine.sync_engine, "connect", lambda conn, _: conn.execute("PRAGMA foreign_keys=ON")
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


def payload(scanner_id="scanner-one", snapshot_id="snap-one", siege_id=None):
    return {
        "schema_version": 1,
        "snapshot_id": snapshot_id,
        "scanner_id": scanner_id,
        "scanner_version": "0.1",
        "observed_at": datetime(2026, 9, 15, 10, tzinfo=UTC).isoformat(),
        "siege_id": siege_id,
        "buildings": [{"external_building_id": "building-1", "level": None, "is_broken": False}],
        "posts": [{"external_post_id": "post-1", "modifier_ids": []}],
    }


async def post(body, credential=None):
    headers = {"Authorization": f"Bearer {credential}"} if credential else {}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.post("/api/scanner/snapshots", json=body, headers=headers)


@pytest.mark.asyncio
async def test_provision_rotate_revoke_and_history(db):
    scanner, secret = await provision_scanner(db, "scanner-one")
    assert scanner.id == "scanner-one"
    assert secret not in scanner.credential_verifier
    assert await authenticate_scanner(db, secret) == scanner
    assert await authenticate_scanner(db, "wrong") is None
    created = await post(payload(), secret)
    assert created.status_code == 201
    retry = await post(payload(), secret)
    assert retry.status_code == 200 and retry.json()["status"] == "duplicate"
    assert created.json()["status"] == "created"
    assert "credential" not in str(created.json()).lower()
    assert "verifier" not in str(created.json()).lower()

    new_secret = await rotate_scanner_credential(db, scanner.id)
    assert new_secret != secret
    assert (await post(payload(snapshot_id="old-fails"), secret)).status_code == 401
    assert (await post(payload(snapshot_id="new-works"), new_secret)).status_code == 201
    assert await revoke_scanner(db, scanner.id) is True
    assert (await post(payload(snapshot_id="revoked"), new_secret)).status_code == 401
    assert len((await db.execute(select(ScannerSnapshot))).scalars().all()) == 2
    assert (await db.get(ScannerIdentity, scanner.id)).id == "scanner-one"


@pytest.mark.asyncio
async def test_auth_disabled_does_not_bypass_scanner_auth_and_identity_is_bound(db):
    _, first_secret = await provision_scanner(db, "scanner-one")
    await provision_scanner(db, "scanner-two")
    assert (await post(payload())).status_code == 401
    assert (await post(payload(), "invalid")).status_code == 401
    assert (await post(payload(scanner_id="scanner-two"), first_secret)).status_code == 403
    assert (await post(payload(), first_secret)).status_code == 201


@pytest.mark.asyncio
async def test_human_bot_and_scanner_credentials_remain_separate(db, monkeypatch):
    import jwt

    from app.config import settings

    _, scanner_secret = await provision_scanner(db, "scanner-one")
    monkeypatch.setattr(settings, "auth_disabled", False)
    monkeypatch.setattr(settings, "bot_service_token", "bot-example")
    monkeypatch.setattr(settings, "session_secret", "test-session-secret")
    human_token = jwt.encode(
        {
            "typ": "manager-user-v2",
            "sub": "1",
            "iat": datetime.now(UTC),
            "exp": datetime.now(UTC) + timedelta(hours=1),
        },
        settings.session_secret,
        algorithm="HS256",
    )
    assert (await post(payload(), "bot-example")).status_code == 401
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        client.cookies.set("session", human_token)
        assert (
            await client.post(
                "/api/scanner/snapshots",
                json=payload(),
                headers={"Origin": settings.allowed_origins.split(",")[0].strip()},
            )
        ).status_code == 401
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        assert (
            await client.get("/api/auth/me", headers={"Authorization": f"Bearer {scanner_secret}"})
        ).status_code == 401


@pytest.mark.asyncio
async def test_http_bot_and_scanner_cross_principal_isolation(db, monkeypatch):
    """Real HTTP requests keep bot, scanner and human role boundaries separate."""
    _, scanner_secret = await provision_scanner(db, "scanner-one")
    member = Member(
        name="Bot Subject",
        discord_id="123456789012345678",
        discord_username="bot_subject",
        role=MemberRole.advanced,
    )
    db.add(member)
    await db.commit()

    monkeypatch.setattr(settings, "auth_disabled", False)
    monkeypatch.setattr(settings, "bot_service_token", "bot-example")
    bot_headers = {
        "Authorization": "Bearer bot-example",
        "X-Acting-Discord-Id": member.discord_id,
    }
    scanner_headers = {"Authorization": f"Bearer {scanner_secret}"}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        assert (
            await client.get("/api/members/me/preferences", headers=bot_headers)
        ).status_code == 200
        assert (await client.get("/api/member-roles", headers=bot_headers)).status_code == 403
        assert (await client.post("/api/sieges/1/activate", headers=bot_headers)).status_code == 403
        assert (
            await client.post("/api/members/discord-sync/preview", headers=bot_headers)
        ).status_code == 403
        assert (
            await client.post("/api/scanner/snapshots", json=payload(), headers=bot_headers)
        ).status_code == 401

        assert (
            await client.post(
                "/api/scanner/snapshots",
                json=payload(snapshot_id="scanner-valid"),
                headers=scanner_headers,
            )
        ).status_code == 201
        assert (await client.get("/api/member-roles", headers=scanner_headers)).status_code == 401
        assert (
            await client.post("/api/sieges/1/activate", headers=scanner_headers)
        ).status_code == 401
        assert (
            await client.post("/api/members/discord-sync/preview", headers=scanner_headers)
        ).status_code == 401
        assert (
            await client.get("/api/members/me/preferences", headers=scanner_headers)
        ).status_code == 401


@pytest.mark.asyncio
async def test_http_human_roles_and_development_cannot_cross_scanner_boundary(db, monkeypatch):
    """Every human role and the development principal remain outside SCANNER."""
    monkeypatch.setattr(settings, "auth_disabled", False)
    monkeypatch.setattr(settings, "session_secret", "test-session-secret")
    origin = settings.allowed_origins.split(",")[0].strip()

    accounts = []
    for index, role in enumerate(("viewer", "manager", "admin"), start=1):
        account = UserAccount(
            discord_user_id=f"12345678901234567{index}",
            display_name=role,
            app_role=role,
        )
        db.add(account)
        accounts.append(account)
    await db.commit()

    for account in accounts:
        token = jwt.encode(
            {
                "typ": "manager-user-v2",
                "sub": str(account.id),
                "iat": datetime.now(UTC),
                "exp": datetime.now(UTC) + timedelta(hours=1),
            },
            settings.session_secret,
            algorithm="HS256",
        )
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            client.cookies.set("session", token)
            response = await client.post(
                "/api/scanner/snapshots",
                json=payload(snapshot_id=f"human-{account.app_role}"),
                headers={"Origin": origin},
            )
            assert response.status_code == 401

    monkeypatch.setattr(settings, "auth_disabled", True)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get("/api/member-roles")).status_code == 200
        assert (await client.post("/api/sieges/999/activate")).status_code == 404
        assert (await client.post("/api/members/discord-sync/preview")).status_code == 403
        assert (
            await client.post(
                "/api/scanner/snapshots",
                json=payload(snapshot_id="development"),
            )
        ).status_code == 401


@pytest.mark.asyncio
async def test_validation_conflict_and_unknown_semantics(db):
    _, secret = await provision_scanner(db, "scanner-one")
    body = payload()
    assert (await post(body, secret)).status_code == 201
    changed = payload()
    changed["posts"][0]["modifier_ids"] = ["different"]
    assert (await post(changed, secret)).status_code == 409
    assert (await post(payload(snapshot_id="bad-siege", siege_id=999), secret)).status_code == 422
    assert (
        await post({**payload(snapshot_id="version"), "schema_version": 2}, secret)
    ).status_code == 422
    duplicate_building = payload(snapshot_id="duplicate-building")
    duplicate_building["buildings"].append(duplicate_building["buildings"][0])
    assert (await post(duplicate_building, secret)).status_code == 422
    duplicate_post = payload(snapshot_id="duplicate-post")
    duplicate_post["posts"].append(duplicate_post["posts"][0])
    assert (await post(duplicate_post, secret)).status_code == 422
    duplicate_modifier = payload(snapshot_id="duplicate-modifier")
    duplicate_modifier["posts"][0]["modifier_ids"] = ["x", "x"]
    assert (await post(duplicate_modifier, secret)).status_code == 422
    future = payload(snapshot_id="future")
    future["observed_at"] = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    assert (await post(future, secret)).status_code == 422

    omitted = payload(snapshot_id="omitted")
    omitted.pop("buildings")
    omitted.pop("posts")
    empty = payload(snapshot_id="empty")
    empty["buildings"] = []
    empty["posts"] = []
    assert (await post(omitted, secret)).status_code == 201
    assert (await post(empty, secret)).status_code == 201
    snapshots = (
        (await db.execute(select(ScannerSnapshot).order_by(ScannerSnapshot.id))).scalars().all()
    )
    assert snapshots[-2].buildings_present is False and snapshots[-2].posts_present is False
    assert snapshots[-1].buildings_present is True and snapshots[-1].posts_present is True
    assert snapshots[0].observed_at != snapshots[0].received_at
    assert snapshots[0].observed_at.isoformat().startswith("2026-09-15T10:00:00")
    buildings = (await db.execute(select(ObservedBuilding))).scalars().all()
    posts = (await db.execute(select(ObservedPost))).scalars().all()
    assert buildings[0].level is None and buildings[0].is_broken is False
    assert posts[0].modifier_ids == []


@pytest.mark.asyncio
async def test_matched_rotations_preserve_manual_buildings_and_conditions(db):
    _, secret = await provision_scanner(db, "scanner-one")
    rotations = []
    for planned_level in (3, 2):
        siege = Siege(defense_scroll_count=0)
        db.add(siege)
        await db.flush()
        building = Building(
            siege_id=siege.id,
            building_type=BuildingType.post,
            building_number=1,
            level=planned_level,
            is_broken=False,
        )
        db.add(building)
        await db.flush()
        post_record = Post(siege_id=siege.id, building_id=building.id)
        db.add(post_record)
        await db.flush()
        rotations.append((siege, building, post_record))
    condition = PostCondition(
        description="manual-condition", stronghold_level=1, condition_type="other"
    )
    db.add(condition)
    await db.flush()
    await db.execute(
        post_active_condition.insert().values(
            post_id=rotations[0][2].id,
            post_condition_id=condition.id,
        )
    )
    await db.commit()

    for (siege, _, _), modifier, snapshot_id in zip(
        rotations, ("modifier-A", "modifier-B"), ("rotation-A", "rotation-B"), strict=True
    ):
        body = payload(snapshot_id=snapshot_id, siege_id=siege.id)
        body["posts"][0]["modifier_ids"] = [modifier]
        body["buildings"][0]["level"] = 1
        response = await post(body, secret)
        assert response.status_code == 201
        assert response.json()["association_status"] == "matched"
        assert response.json()["siege_id"] == siege.id

    for _, building, _ in rotations:
        await db.refresh(building)
    assert [building.level for _, building, _ in rotations] == [3, 2]
    assert len((await db.execute(select(post_active_condition))).all()) == 1
    observed = (await db.execute(select(ObservedPost).order_by(ObservedPost.id))).scalars().all()
    assert [row.modifier_ids for row in observed] == [["modifier-A"], ["modifier-B"]]
    snapshots = (
        (await db.execute(select(ScannerSnapshot).order_by(ScannerSnapshot.id))).scalars().all()
    )
    assert [row.siege_id for row in snapshots] == [rotations[0][0].id, rotations[1][0].id]


@pytest.mark.asyncio
async def test_payload_size_and_raid_auth_material_are_rejected(db, monkeypatch):
    _, secret = await provision_scanner(db, "scanner-one")
    monkeypatch.setattr("app.config.settings.bot_service_token", "bot-example")
    assert (await post(payload(), "bot-example")).status_code == 401
    unsafe = {**payload(snapshot_id="unsafe"), "signin-session": "fake-not-real"}
    assert (await post(unsafe, secret)).status_code == 422
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        oversized = await client.post(
            "/api/scanner/snapshots",
            content=b"x" * (256 * 1024 + 1),
            headers={"Authorization": f"Bearer {secret}"},
        )
    assert oversized.status_code == 413


@pytest.mark.asyncio
async def test_child_constraint_failure_rolls_back_entire_snapshot(db):
    await provision_scanner(db, "scanner-one")
    invalid_internal_batch = SnapshotEnvelope.model_validate(payload(snapshot_id="atomic"))
    invalid_internal_batch.posts.append(invalid_internal_batch.posts[0].model_copy())
    with pytest.raises(IntegrityError):
        await record_snapshot_with_status(db, invalid_internal_batch)
    assert (await db.execute(select(ScannerSnapshot))).scalars().all() == []
    assert (await db.execute(select(ObservedBuilding))).scalars().all() == []
    assert (await db.execute(select(ObservedPost))).scalars().all() == []
