"""Characterization tests for current per-Siege planning boundaries.

Post condition definitions are global, but assignments to Posts belong to a
Siege rotation. No Raid identity or Scanner behavior is assumed here.
"""

import datetime

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401 - register all tables in Base.metadata
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.building import Building
from app.models.building_group import BuildingGroup
from app.models.building_type_config import BuildingTypeConfig
from app.models.enums import BuildingType, MemberRole, SiegeStatus
from app.models.member import Member
from app.models.position import Position
from app.models.post import Post
from app.models.post_active_condition import post_active_condition
from app.models.post_condition import PostCondition
from app.models.siege import Siege
from app.models.siege_member import SiegeMember
from app.schemas.building import BuildingUpdate
from app.services.buildings import update_building
from app.services.comparison import compare_sieges, get_most_recent_completed
from app.services.lifecycle import clone_siege
from app.services.posts import set_post_conditions


def _enable_foreign_keys(connection, _record):
    connection.execute("PRAGMA foreign_keys = ON")


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    event.listen(engine.sync_engine, "connect", _enable_foreign_keys)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db:
        yield db
    await engine.dispose()


async def _siege(db, date, status=SiegeStatus.planning):
    siege = Siege(date=date, status=status, defense_scroll_count=0)
    db.add(siege)
    await db.flush()
    return siege


async def _building(db, siege, kind, number=1, level=1, group_slots=()):
    building = Building(
        siege_id=siege.id,
        building_type=kind,
        building_number=number,
        level=level,
        is_broken=False,
    )
    db.add(building)
    await db.flush()
    for group_number, slot_count in enumerate(group_slots, start=1):
        group = BuildingGroup(
            building_id=building.id,
            group_number=group_number,
            slot_count=slot_count,
        )
        db.add(group)
        await db.flush()
        for position_number in range(1, slot_count + 1):
            db.add(
                Position(
                    building_group_id=group.id,
                    position_number=position_number,
                    is_reserve=False,
                    is_disabled=False,
                )
            )
    await db.flush()
    return building


async def _post(db, siege, number=1):
    building = await _building(db, siege, BuildingType.post, number, group_slots=(3,))
    post = Post(siege_id=siege.id, building_id=building.id, priority=2)
    db.add(post)
    await db.flush()
    return post, building


async def _condition_ids(db, post_id):
    rows = await db.execute(
        select(post_active_condition.c.post_condition_id)
        .where(post_active_condition.c.post_id == post_id)
        .order_by(post_active_condition.c.post_condition_id)
    )
    return list(rows.scalars())


async def _layout(db, building_id):
    rows = await db.execute(
        select(
            BuildingGroup.group_number,
            BuildingGroup.slot_count,
            Position.position_number,
            Position.id,
            Position.member_id,
        )
        .join(Position, Position.building_group_id == BuildingGroup.id)
        .where(BuildingGroup.building_id == building_id)
        .order_by(BuildingGroup.group_number, Position.position_number)
    )
    return list(rows.all())


@pytest.mark.asyncio
async def test_post_conditions_are_rotation_scoped_and_catalog_is_unchanged(session):
    old = await _siege(session, datetime.date(2026, 1, 1))
    new = await _siege(session, datetime.date(2026, 2, 1))
    old_post, _ = await _post(session, old)
    new_post, _ = await _post(session, new)
    other_new_post, _ = await _post(session, new, number=2)
    conditions = [
        PostCondition(
            description=f"Rotation condition {number}", stronghold_level=1, condition_type="role"
        )
        for number in range(1, 7)
    ]
    session.add_all(conditions)
    await session.commit()
    catalog_before = (
        await session.execute(
            select(PostCondition.id, PostCondition.description).order_by(PostCondition.id)
        )
    ).all()

    await set_post_conditions(session, old.id, old_post.id, [c.id for c in conditions[:3]])
    await set_post_conditions(session, new.id, new_post.id, [c.id for c in conditions[3:]])
    await set_post_conditions(session, new.id, other_new_post.id, [conditions[0].id])
    assert await _condition_ids(session, old_post.id) == sorted(c.id for c in conditions[:3])
    assert await _condition_ids(session, new_post.id) == sorted(c.id for c in conditions[3:])
    assert await _condition_ids(session, other_new_post.id) == [conditions[0].id]

    # Replacement in the newer rotation must not rewrite the older rotation or catalog.
    await set_post_conditions(session, new.id, new_post.id, [conditions[3].id])
    assert await _condition_ids(session, old_post.id) == sorted(c.id for c in conditions[:3])
    assert await _condition_ids(session, new_post.id) == [conditions[3].id]
    assert (
        await session.execute(
            select(PostCondition.id, PostCondition.description).order_by(PostCondition.id)
        )
    ).all() == catalog_before


@pytest.mark.asyncio
async def test_post_condition_limit_siege_identity_and_completed_lock(session):
    old = await _siege(session, datetime.date(2026, 1, 1))
    new = await _siege(session, datetime.date(2026, 2, 1))
    old_post, _ = await _post(session, old)
    new_post, _ = await _post(session, new)
    conditions = [
        PostCondition(
            description=f"Limit condition {number}", stronghold_level=1, condition_type="role"
        )
        for number in range(4)
    ]
    session.add_all(conditions)
    await session.commit()
    await set_post_conditions(session, old.id, old_post.id, [conditions[0].id])

    with pytest.raises(HTTPException) as too_many:
        await set_post_conditions(session, new.id, new_post.id, [c.id for c in conditions])
    assert too_many.value.status_code == 400
    with pytest.raises(HTTPException) as wrong_rotation:
        await set_post_conditions(session, new.id, old_post.id, [conditions[1].id])
    assert wrong_rotation.value.status_code == 404
    old.status = SiegeStatus.complete
    await session.commit()
    with pytest.raises(HTTPException) as completed:
        await set_post_conditions(session, old.id, old_post.id, [conditions[1].id])
    assert completed.value.status_code == 400
    assert await _condition_ids(session, old_post.id) == [conditions[0].id]
    assert await _condition_ids(session, new_post.id) == []


@pytest.mark.asyncio
async def test_replacing_post_conditions_keeps_existing_position_match(session):
    siege = await _siege(session, datetime.date(2026, 1, 1))
    post, building = await _post(session, siege)
    first = PostCondition(description="Matched first", stronghold_level=1, condition_type="role")
    second = PostCondition(description="Matched second", stronghold_level=1, condition_type="role")
    session.add_all([first, second])
    await session.flush()
    position = (
        await session.execute(
            select(Position)
            .join(BuildingGroup)
            .where(BuildingGroup.building_id == building.id)
            .where(Position.position_number == 1)
        )
    ).scalar_one()
    position.matched_condition_id = first.id
    await session.commit()
    await set_post_conditions(session, siege.id, post.id, [first.id])
    await set_post_conditions(session, siege.id, post.id, [second.id])
    await session.refresh(position)
    assert position.matched_condition_id == first.id
    assert await _condition_ids(session, post.id) == [second.id]


@pytest.mark.asyncio
async def test_building_identity_is_unique_within_rotation_but_reusable_across_rotations(session):
    old = await _siege(session, datetime.date(2026, 1, 1))
    new = await _siege(session, datetime.date(2026, 2, 1))
    old_building = await _building(session, old, BuildingType.magic_tower, level=1)
    new_building = await _building(session, new, BuildingType.magic_tower, level=2)
    await session.commit()
    assert old_building.id != new_building.id
    assert (
        await session.execute(select(Building.level).where(Building.siege_id == old.id))
    ).scalar_one() == 1
    assert (
        await session.execute(select(Building.level).where(Building.siege_id == new.id))
    ).scalar_one() == 2
    from sqlalchemy.exc import IntegrityError

    session.add(
        Building(
            siege_id=new.id,
            building_type=BuildingType.magic_tower,
            building_number=1,
            level=1,
            is_broken=False,
        )
    )
    with pytest.raises(IntegrityError):
        await session.flush()
    await session.rollback()


@pytest.mark.asyncio
async def test_level_rebuild_preserves_retained_positions_and_deletes_trimmed_groups(session):
    old = await _siege(session, datetime.date(2026, 1, 1))
    new = await _siege(session, datetime.date(2026, 2, 1))
    session.add(
        BuildingTypeConfig(
            building_type=BuildingType.stronghold,
            count=1,
            base_group_count=4,
            base_last_group_slots=3,
        )
    )
    member = Member(name="Level baseline member", role=MemberRole.advanced, is_active=True)
    session.add(member)
    await session.flush()
    old_building = await _building(session, old, BuildingType.stronghold, group_slots=(3, 3, 3, 3))
    new_building = await _building(session, new, BuildingType.stronghold, group_slots=(3, 3, 3, 3))
    old_layout = await _layout(session, old_building.id)
    new_layout = await _layout(session, new_building.id)
    retained_id = new_layout[0][3]
    group_four_id = new_layout[-1][3]
    position = await session.get(Position, retained_id)
    position.member_id = member.id
    await session.commit()

    await update_building(session, new.id, new_building.id, BuildingUpdate(level=2))
    expanded = await _layout(session, new_building.id)
    assert len(expanded) == 16
    assert expanded[0][3] == retained_id
    assert expanded[0][4] == member.id
    assert any(row[3] == group_four_id for row in expanded)
    assert [row[1] for row in expanded if row[0] == 6] == [1]
    assert await _layout(session, old_building.id) == old_layout

    added_ids = {row[3] for row in expanded} - {row[3] for row in new_layout}
    await update_building(session, new.id, new_building.id, BuildingUpdate(level=1))
    shrunk = await _layout(session, new_building.id)
    assert len(shrunk) == 12
    assert {row[3] for row in shrunk} == {row[3] for row in new_layout}
    assert not added_ids.intersection({row[3] for row in shrunk})
    assert await _layout(session, old_building.id) == old_layout


@pytest.mark.asyncio
async def test_break_and_unbreak_remove_and_recreate_positions_only_in_selected_rotation(session):
    old = await _siege(session, datetime.date(2026, 1, 1))
    new = await _siege(session, datetime.date(2026, 2, 1))
    session.add(
        BuildingTypeConfig(
            building_type=BuildingType.stronghold,
            count=1,
            base_group_count=1,
            base_last_group_slots=2,
        )
    )
    old_building = await _building(
        session, old, BuildingType.stronghold, level=2, group_slots=(3, 3, 3, 3, 3, 1)
    )
    new_building = await _building(
        session, new, BuildingType.stronghold, level=2, group_slots=(3, 3, 3, 3, 3, 1)
    )
    member = Member(name="Break baseline member", role=MemberRole.advanced, is_active=True)
    session.add(member)
    await session.flush()
    old_layout = await _layout(session, old_building.id)
    original = await _layout(session, new_building.id)
    retained_id, trimmed_id = original[0][3], original[2][3]
    trimmed_position = await session.get(Position, trimmed_id)
    trimmed_position.member_id = member.id
    await session.commit()

    await update_building(session, new.id, new_building.id, BuildingUpdate(is_broken=True))
    broken = await _layout(session, new_building.id)
    assert len(broken) == 2
    assert broken[0][3] == retained_id
    assert trimmed_id not in {row[3] for row in broken}
    assert await _layout(session, old_building.id) == old_layout

    await update_building(session, new.id, new_building.id, BuildingUpdate(is_broken=False))
    restored = await _layout(session, new_building.id)
    assert len(restored) == 16
    assert restored[0][3] == retained_id
    # SQLite may reuse the deleted integer PK; the planning assignment must
    # still be gone, which is the relevant invariant for PostgreSQL as well.
    assert restored[2][4] is None
    assert await _layout(session, old_building.id) == old_layout


@pytest.mark.asyncio
async def test_active_and_completed_sieges_reject_building_mutations(session):
    siege = await _siege(session, datetime.date(2026, 1, 1))
    building = await _building(session, siege, BuildingType.post, group_slots=(3,))
    await session.commit()
    for status in (SiegeStatus.active, SiegeStatus.complete):
        siege.status = status
        await session.commit()
        for change in (BuildingUpdate(level=2), BuildingUpdate(is_broken=True)):
            with pytest.raises(HTTPException) as locked:
                await update_building(session, siege.id, building.id, change)
            assert locked.value.status_code == 400
        assert (
            await session.execute(
                select(Building.level, Building.is_broken).where(Building.id == building.id)
            )
        ).one() == (1, False)


@pytest.mark.asyncio
async def test_post_level_change_does_not_rebuild_its_single_group(session):
    siege = await _siege(session, datetime.date(2026, 1, 1))
    building = await _building(session, siege, BuildingType.post, group_slots=(3,))
    original = await _layout(session, building.id)
    await session.commit()
    await update_building(session, siege.id, building.id, BuildingUpdate(level=2))
    assert building.level == 2
    assert await _layout(session, building.id) == original


@pytest.mark.asyncio
async def test_clone_keeps_source_rotation_while_clearing_new_post_conditions(session):
    source = await _siege(session, datetime.date(2026, 1, 1), SiegeStatus.complete)
    member = Member(name="Clone baseline member", role=MemberRole.advanced, is_active=True)
    condition = PostCondition(
        description="Clone source condition", stronghold_level=1, condition_type="role"
    )
    session.add_all([member, condition])
    await session.flush()
    building = await _building(session, source, BuildingType.stronghold, group_slots=(3,))
    post, _ = await _post(session, source)
    first_position = (
        await session.execute(
            select(Position)
            .join(BuildingGroup)
            .where(BuildingGroup.building_id == building.id)
            .where(Position.position_number == 1)
        )
    ).scalar_one()
    first_position.member_id = member.id
    session.add(
        SiegeMember(
            siege_id=source.id,
            member_id=member.id,
            attack_day=1,
            has_reserve_set=True,
            attack_day_override=False,
        )
    )
    await session.commit()
    # The completed source is immutable through the planning Post API; seed its
    # existing historical link directly, then clone using the production service.
    await session.execute(
        post_active_condition.insert().values(
            post_id=post.id,
            post_condition_id=condition.id,
        )
    )
    await session.commit()
    source_layout = await _layout(session, building.id)
    source_conditions = await _condition_ids(session, post.id)

    cloned = await clone_siege(session, source.id)
    cloned_post = (
        await session.execute(select(Post).where(Post.siege_id == cloned.id))
    ).scalar_one()
    cloned_building = (
        await session.execute(
            select(Building)
            .where(Building.siege_id == cloned.id)
            .where(Building.building_type == BuildingType.stronghold)
        )
    ).scalar_one()
    cloned_layout = await _layout(session, cloned_building.id)
    assert cloned.id != source.id
    assert await _condition_ids(session, cloned_post.id) == []
    assert await _condition_ids(session, post.id) == source_conditions
    assert len(cloned_layout) == len(source_layout)
    assert cloned_layout[0][4] == member.id
    assert cloned_layout[0][3] != source_layout[0][3]
    assert (
        await session.execute(
            select(func.count()).select_from(SiegeMember).where(SiegeMember.siege_id == cloned.id)
        )
    ).scalar_one() == 1
    assert await _layout(session, building.id) == source_layout


@pytest.mark.asyncio
async def test_compare_default_selects_most_recent_completed_rotation_before_target(session):
    target = await _siege(session, datetime.date(2026, 1, 1), SiegeStatus.planning)
    previous = await _siege(session, datetime.date(2025, 12, 1), SiegeStatus.complete)
    later = await _siege(session, datetime.date(2026, 2, 1), SiegeStatus.complete)
    await session.commit()
    selected = await get_most_recent_completed(session, exclude_siege_id=target.id)
    assert selected.id == previous.id
    assert selected.id != later.id


@pytest.mark.asyncio
async def test_compare_default_has_no_previous_when_only_later_rotation_is_complete(session):
    target = await _siege(session, datetime.date(2026, 1, 1), SiegeStatus.planning)
    await _siege(session, datetime.date(2026, 2, 1), SiegeStatus.complete)
    await session.commit()
    assert await get_most_recent_completed(session, exclude_siege_id=target.id) is None


@pytest.mark.asyncio
async def test_compare_default_chooses_latest_earlier_date_then_highest_id(session):
    target = await _siege(session, datetime.date(2026, 1, 1), SiegeStatus.planning)
    await _siege(session, datetime.date(2025, 11, 1), SiegeStatus.complete)
    await _siege(session, datetime.date(2025, 12, 1), SiegeStatus.complete)
    latest_tied = await _siege(session, datetime.date(2025, 12, 1), SiegeStatus.complete)
    await session.commit()
    selected = await get_most_recent_completed(session, exclude_siege_id=target.id)
    assert selected.id == latest_tied.id


@pytest.mark.asyncio
async def test_compare_default_excludes_target_noncompleted_and_same_date_candidates(session):
    target = await _siege(session, datetime.date(2026, 1, 1), SiegeStatus.complete)
    previous = await _siege(session, datetime.date(2025, 12, 1), SiegeStatus.complete)
    await _siege(session, datetime.date(2025, 12, 31), SiegeStatus.planning)
    await _siege(session, datetime.date(2025, 12, 31), SiegeStatus.active)
    await _siege(session, datetime.date(2026, 1, 1), SiegeStatus.complete)
    await session.commit()
    selected = await get_most_recent_completed(session, exclude_siege_id=target.id)
    assert selected.id == previous.id


@pytest.mark.asyncio
async def test_compare_default_has_no_previous_for_undated_target(session):
    target = await _siege(session, None, SiegeStatus.planning)
    await _siege(session, datetime.date(2025, 12, 1), SiegeStatus.complete)
    await session.commit()
    assert await get_most_recent_completed(session, exclude_siege_id=target.id) is None


@pytest.mark.asyncio
async def test_compare_api_default_uses_previous_but_explicit_allows_later_siege(session):
    target = await _siege(session, datetime.date(2026, 1, 1), SiegeStatus.planning)
    previous = await _siege(session, datetime.date(2025, 12, 1), SiegeStatus.complete)
    later = await _siege(session, datetime.date(2026, 2, 1), SiegeStatus.complete)
    await session.commit()

    async def override_get_db():
        yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            automatic = await client.get(f"/api/sieges/{target.id}/compare")
            explicit = await client.get(f"/api/sieges/{target.id}/compare/{later.id}")
    finally:
        app.dependency_overrides.pop(get_db, None)
    assert automatic.status_code == 200
    assert automatic.json() == {
        "siege_a_id": previous.id,
        "siege_b_id": target.id,
        "members": [],
    }
    assert explicit.status_code == 200
    assert explicit.json() == {
        "siege_a_id": later.id,
        "siege_b_id": target.id,
        "members": [],
    }


@pytest.mark.asyncio
async def test_compare_api_undated_target_has_no_automatic_previous(session):
    target = await _siege(session, None, SiegeStatus.planning)
    await _siege(session, datetime.date(2025, 12, 1), SiegeStatus.complete)
    await session.commit()

    async def override_get_db():
        yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(f"/api/sieges/{target.id}/compare")
    finally:
        app.dependency_overrides.pop(get_db, None)
    assert response.status_code == 404
    assert response.json()["detail"] == "No completed siege found to compare against"


@pytest.mark.asyncio
async def test_compare_history_is_unchanged_by_global_member_deactivation(session):
    old = await _siege(session, datetime.date(2026, 1, 1), SiegeStatus.complete)
    new = await _siege(session, datetime.date(2026, 2, 1), SiegeStatus.planning)
    member = Member(name="Compare historical member", role=MemberRole.advanced, is_active=True)
    session.add(member)
    await session.flush()
    old_building = await _building(session, old, BuildingType.stronghold, group_slots=(1,))
    new_building = await _building(session, new, BuildingType.stronghold, group_slots=(1,))
    for building in (old_building, new_building):
        position = (
            await session.execute(
                select(Position).join(BuildingGroup).where(BuildingGroup.building_id == building.id)
            )
        ).scalar_one()
        position.member_id = member.id
    await session.commit()

    before = await compare_sieges(session, old.id, new.id)
    assert [diff.member_id for diff in before.members] == [member.id]
    member.is_active = False
    await session.commit()
    after = await compare_sieges(session, old.id, new.id)
    assert after == before


@pytest.mark.asyncio
async def test_compare_inactive_member_retains_added_and_removed_assignments(session):
    old = await _siege(session, datetime.date(2026, 1, 1), SiegeStatus.complete)
    new = await _siege(session, datetime.date(2026, 2, 1), SiegeStatus.complete)
    member = Member(
        name="Inactive historical diff member", role=MemberRole.advanced, is_active=False
    )
    session.add(member)
    await session.flush()
    old_building = await _building(session, old, BuildingType.stronghold, group_slots=(1, 1))
    new_building = await _building(session, new, BuildingType.stronghold, group_slots=(1, 1))
    old_position = (
        await session.execute(
            select(Position)
            .join(BuildingGroup)
            .where(BuildingGroup.building_id == old_building.id)
            .where(BuildingGroup.group_number == 1)
        )
    ).scalar_one()
    new_position = (
        await session.execute(
            select(Position)
            .join(BuildingGroup)
            .where(BuildingGroup.building_id == new_building.id)
            .where(BuildingGroup.group_number == 2)
        )
    ).scalar_one()
    old_position.member_id = member.id
    new_position.member_id = member.id
    await session.commit()
    result = await compare_sieges(session, old.id, new.id)
    assert len(result.members) == 1
    diff = result.members[0]
    assert diff.member_id == member.id
    assert [item.group_number for item in diff.added] == [2]
    assert [item.group_number for item in diff.removed] == [1]
