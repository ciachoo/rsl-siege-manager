"""Read-only queries for historical Scanner evidence."""

from typing import Literal

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.scanner import ScannerSnapshot

AssociationStatus = Literal["matched", "unmatched"]


def _filtered_snapshots(
    *,
    scanner_id: str | None,
    siege_id: int | None,
    association_status: AssociationStatus | None,
) -> Select:
    query = select(ScannerSnapshot)
    if scanner_id is not None:
        query = query.where(ScannerSnapshot.scanner_id == scanner_id)
    if siege_id is not None:
        query = query.where(ScannerSnapshot.siege_id == siege_id)
    if association_status is not None:
        query = query.where(ScannerSnapshot.association_status == association_status)
    return query


async def list_snapshots(
    session: AsyncSession,
    *,
    limit: int,
    offset: int,
    scanner_id: str | None = None,
    siege_id: int | None = None,
    association_status: AssociationStatus | None = None,
) -> list[ScannerSnapshot]:
    query = (
        _filtered_snapshots(
            scanner_id=scanner_id,
            siege_id=siege_id,
            association_status=association_status,
        )
        .order_by(ScannerSnapshot.observed_at.desc(), ScannerSnapshot.id.desc())
        .offset(offset)
        .limit(limit)
    )
    return list((await session.execute(query)).scalars().all())


async def latest_snapshot(
    session: AsyncSession,
    *,
    scanner_id: str | None = None,
    siege_id: int | None = None,
    association_status: AssociationStatus | None = None,
) -> ScannerSnapshot | None:
    query = (
        _filtered_snapshots(
            scanner_id=scanner_id,
            siege_id=siege_id,
            association_status=association_status,
        )
        .order_by(ScannerSnapshot.observed_at.desc(), ScannerSnapshot.id.desc())
        .limit(1)
    )
    return (await session.execute(query)).scalar_one_or_none()


async def get_snapshot_detail(session: AsyncSession, snapshot_db_id: int) -> ScannerSnapshot | None:
    query = (
        select(ScannerSnapshot)
        .where(ScannerSnapshot.id == snapshot_db_id)
        .options(
            selectinload(ScannerSnapshot.buildings),
            selectinload(ScannerSnapshot.posts),
        )
    )
    return (await session.execute(query)).scalar_one_or_none()
