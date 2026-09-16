"""Read-only selection of one explicit Scanner evidence source for a Siege."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.scanner import ScannerSnapshot


async def latest_matched_snapshot(session: AsyncSession, siege_id: int) -> ScannerSnapshot | None:
    query = (
        select(ScannerSnapshot)
        .where(ScannerSnapshot.siege_id == siege_id)
        .order_by(ScannerSnapshot.observed_at.desc(), ScannerSnapshot.id.desc())
        .limit(1)
        .options(
            selectinload(ScannerSnapshot.buildings),
            selectinload(ScannerSnapshot.posts),
        )
    )
    return (await session.execute(query)).scalar_one_or_none()
