"""Scanner evidence stays independent of Manager planning state."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.db.base import Base
from app.models.building import Building
from app.models.enums import BuildingType
from app.models.post import Post
from app.models.post_active_condition import post_active_condition
from app.models.post_condition import PostCondition
from app.models.siege import Siege
from app.schemas.scanner import BuildingObservation, PostObservation, SnapshotEnvelope
from app.services.scanner import SnapshotConflict, record_snapshot


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    event.listen(
        engine.sync_engine, "connect", lambda conn, _: conn.execute("PRAGMA foreign_keys=ON")
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db:
        yield db
    await engine.dispose()


async def _rotation(db):
    siege = Siege(defense_scroll_count=0)
    db.add(siege)
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
    post = Post(siege_id=siege.id, building_id=building.id)
    db.add(post)
    await db.flush()
    return siege, building, post


def _envelope(snapshot_id, siege_id=None, conditions=None):
    return SnapshotEnvelope(
        schema_version=1,
        snapshot_id=snapshot_id,
        scanner_id="install-1",
        scanner_version="0.1.0",
        observed_at=datetime(2026, 9, 15, 10, tzinfo=UTC),
        siege_id=siege_id,
        cycle_ref="cycle-example",
        buildings=[
            BuildingObservation(external_building_id="raid-building-3001", level=2, is_broken=False)
        ],
        posts=[PostObservation(external_post_id="raid-post-3001", modifier_ids=conditions)],
    )


@pytest.mark.asyncio
async def test_evidence_is_historical_idempotent_and_does_not_change_planning(session):
    first, first_building, first_post = await _rotation(session)
    second, _, _ = await _rotation(session)
    condition = PostCondition(description="manual", stronghold_level=1, condition_type="other")
    session.add(condition)
    await session.flush()
    await session.execute(
        post_active_condition.insert().values(post_id=first_post.id, post_condition_id=condition.id)
    )
    await session.commit()

    a = await record_snapshot(session, _envelope("snapshot-a", first.id, ["modifier-X"]))
    retry = await record_snapshot(session, _envelope("snapshot-a", first.id, ["modifier-X"]))
    b = await record_snapshot(session, _envelope("snapshot-b", second.id, ["modifier-Y"]))
    assert retry.id == a.id
    assert a.id != b.id
    assert a.scanner_id == b.scanner_id == "install-1"
    assert a.siege_id == first.id and b.siege_id == second.id
    assert a.observed_at != a.received_at

    await session.refresh(first_building)
    assert (first_building.level, first_building.is_broken) == (3, False)
    links = (await session.execute(select(post_active_condition))).all()
    assert len(links) == 1 and links[0].post_id == first_post.id
    from app.models.scanner import ObservedBuilding, ObservedPost, ScannerSnapshot

    assert len((await session.execute(select(ScannerSnapshot))).scalars().all()) == 2
    assert len((await session.execute(select(ObservedBuilding))).scalars().all()) == 2
    posts = (await session.execute(select(ObservedPost).order_by(ObservedPost.id))).scalars().all()
    assert [p.modifier_ids for p in posts] == [["modifier-X"], ["modifier-Y"]]


@pytest.mark.asyncio
async def test_unknown_empty_false_and_unmatched_remain_distinct(session):
    unknown_envelope = _envelope("unknown", conditions=None)
    unknown_envelope.buildings[0].level = None
    unknown_envelope.buildings[0].is_broken = None
    unknown = await record_snapshot(session, unknown_envelope)
    empty = await record_snapshot(session, _envelope("empty", conditions=[]))
    assert unknown.siege_id is None and empty.siege_id is None
    assert unknown.association_status == "unmatched"
    from app.models.scanner import ObservedBuilding, ObservedPost

    buildings = (
        (await session.execute(select(ObservedBuilding).order_by(ObservedBuilding.id)))
        .scalars()
        .all()
    )
    assert buildings[0].level is None and buildings[0].is_broken is None
    assert buildings[1].level == 2 and buildings[1].is_broken is False
    posts = (await session.execute(select(ObservedPost).order_by(ObservedPost.id))).scalars().all()
    assert posts[0].modifier_ids is None and posts[1].modifier_ids == []


@pytest.mark.asyncio
async def test_reused_snapshot_key_with_different_facts_is_conflict(session):
    await record_snapshot(session, _envelope("same", conditions=["modifier-X"]))
    with pytest.raises(SnapshotConflict):
        await record_snapshot(session, _envelope("same", conditions=["modifier-Y"]))


@pytest.mark.asyncio
async def test_unknown_explicit_siege_is_rejected_without_guessing(session):
    with pytest.raises(ValueError, match="siege_id"):
        await record_snapshot(session, _envelope("unresolvable", siege_id=999))
    from app.models.scanner import ScannerSnapshot

    assert (await session.execute(select(ScannerSnapshot))).scalars().all() == []


def test_contract_rejects_auth_material_and_invalid_building_zero():
    data = _envelope("unsafe").model_dump()
    data["raid_jwt"] = "fake-secret"
    with pytest.raises(ValidationError):
        SnapshotEnvelope.model_validate(data)
    with pytest.raises(ValidationError):
        BuildingObservation(external_building_id="building", level=0)


@pytest.mark.asyncio
async def test_omitted_categories_differ_from_explicit_empty_categories(session):
    omitted = _envelope("omitted")
    omitted.buildings = None
    omitted.posts = None
    empty = _envelope("present-empty")
    empty.buildings = []
    empty.posts = []
    unknown = await record_snapshot(session, omitted)
    observed_empty = await record_snapshot(session, empty)
    assert (unknown.buildings_present, unknown.posts_present) == (False, False)
    assert (observed_empty.buildings_present, observed_empty.posts_present) == (True, True)
