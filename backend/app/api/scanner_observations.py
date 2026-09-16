"""HUMAN_VIEWER read-only access to historical Scanner evidence."""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.dependencies.auth import require_viewer
from app.models.scanner import ScannerSnapshot
from app.schemas.scanner_observations import (
    ObservedBuildingResponse,
    ObservedPostResponse,
    ScannerSnapshotDetail,
    ScannerSnapshotSummary,
)
from app.services import scanner_observations as observation_service

router = APIRouter(prefix="/scanner-observations", tags=["scanner-observations"])


def _summary(snapshot: ScannerSnapshot) -> ScannerSnapshotSummary:
    return ScannerSnapshotSummary(
        id=snapshot.id,
        snapshot_id=snapshot.snapshot_id,
        scanner_id=snapshot.scanner_id,
        scanner_version=snapshot.scanner_version,
        schema_version=snapshot.schema_version,
        observed_at=snapshot.observed_at,
        received_at=snapshot.received_at,
        siege_id=snapshot.siege_id,
        association_status=snapshot.association_status,
        cycle_ref=snapshot.cycle_ref,
        buildings_present=snapshot.buildings_present,
        posts_present=snapshot.posts_present,
    )


@router.get(
    "/snapshots",
    response_model=list[ScannerSnapshotSummary],
    summary="List Scanner snapshots",
    dependencies=[Depends(require_viewer)],
)
async def list_snapshots(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    scanner_id: str | None = Query(default=None, min_length=1, max_length=128),
    siege_id: int | None = Query(default=None, ge=1),
    association_status: Literal["matched", "unmatched"] | None = None,
    db: AsyncSession = Depends(get_db),
) -> list[ScannerSnapshotSummary]:
    snapshots = await observation_service.list_snapshots(
        db,
        limit=limit,
        offset=offset,
        scanner_id=scanner_id,
        siege_id=siege_id,
        association_status=association_status,
    )
    return [_summary(snapshot) for snapshot in snapshots]


@router.get(
    "/snapshots/latest",
    response_model=ScannerSnapshotSummary,
    summary="Get the latest Scanner snapshot",
    dependencies=[Depends(require_viewer)],
)
async def get_latest_snapshot(
    scanner_id: str | None = Query(default=None, min_length=1, max_length=128),
    siege_id: int | None = Query(default=None, ge=1),
    association_status: Literal["matched", "unmatched"] | None = None,
    db: AsyncSession = Depends(get_db),
) -> ScannerSnapshotSummary:
    snapshot = await observation_service.latest_snapshot(
        db,
        scanner_id=scanner_id,
        siege_id=siege_id,
        association_status=association_status,
    )
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Scanner snapshot not found")
    return _summary(snapshot)


@router.get(
    "/snapshots/{snapshot_db_id}",
    response_model=ScannerSnapshotDetail,
    summary="Get Scanner snapshot evidence",
    dependencies=[Depends(require_viewer)],
)
async def get_snapshot_detail(
    snapshot_db_id: int,
    db: AsyncSession = Depends(get_db),
) -> ScannerSnapshotDetail:
    snapshot = await observation_service.get_snapshot_detail(db, snapshot_db_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Scanner snapshot not found")
    summary = _summary(snapshot).model_dump()
    buildings = sorted(snapshot.buildings, key=lambda row: (row.external_building_id, row.id))
    posts = sorted(snapshot.posts, key=lambda row: (row.external_post_id, row.id))
    return ScannerSnapshotDetail(
        **summary,
        buildings=[
            ObservedBuildingResponse(
                external_building_id=row.external_building_id,
                level=row.level,
                is_broken=row.is_broken,
            )
            for row in buildings
        ],
        posts=[
            ObservedPostResponse(
                external_post_id=row.external_post_id,
                modifier_ids=row.modifier_ids,
            )
            for row in posts
        ],
    )
