"""HUMAN_VIEWER projection of Scanner evidence for a specific Siege."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.dependencies.auth import require_viewer
from app.models.siege import Siege
from app.schemas.scanner_observations import (
    ObservedBuildingResponse,
    ObservedPostResponse,
)
from app.schemas.siege_scanner_evidence import (
    SiegeEvidenceSourceSnapshot,
    SiegeScannerEvidenceResponse,
)
from app.services.siege_scanner_evidence import latest_matched_snapshot

router = APIRouter(tags=["siege-scanner-evidence"])


@router.get(
    "/sieges/{siege_id}/scanner-evidence",
    response_model=SiegeScannerEvidenceResponse,
    summary="Get latest matched Scanner evidence for a Siege",
    dependencies=[Depends(require_viewer)],
)
async def get_siege_scanner_evidence(
    siege_id: int,
    db: AsyncSession = Depends(get_db),
) -> SiegeScannerEvidenceResponse:
    if await db.get(Siege, siege_id) is None:
        raise HTTPException(status_code=404, detail="Siege not found")

    snapshot = await latest_matched_snapshot(db, siege_id)
    if snapshot is None:
        return SiegeScannerEvidenceResponse(
            siege_id=siege_id,
            has_evidence=False,
            source_snapshot=None,
            buildings_present=None,
            posts_present=None,
            buildings=[],
            posts=[],
        )

    buildings = sorted(snapshot.buildings, key=lambda row: (row.external_building_id, row.id))
    posts = sorted(snapshot.posts, key=lambda row: (row.external_post_id, row.id))
    return SiegeScannerEvidenceResponse(
        siege_id=siege_id,
        has_evidence=True,
        source_snapshot=SiegeEvidenceSourceSnapshot(
            id=snapshot.id,
            snapshot_id=snapshot.snapshot_id,
            scanner_id=snapshot.scanner_id,
            scanner_version=snapshot.scanner_version,
            schema_version=snapshot.schema_version,
            observed_at=snapshot.observed_at,
            received_at=snapshot.received_at,
            cycle_ref=snapshot.cycle_ref,
        ),
        buildings_present=snapshot.buildings_present,
        posts_present=snapshot.posts_present,
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
