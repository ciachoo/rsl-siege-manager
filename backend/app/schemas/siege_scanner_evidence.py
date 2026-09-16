"""Explicit read-only projection of Scanner evidence for one Siege."""

from datetime import datetime

from pydantic import BaseModel

from app.schemas.scanner_observations import (
    ObservedBuildingResponse,
    ObservedPostResponse,
)


class SiegeEvidenceSourceSnapshot(BaseModel):
    id: int
    snapshot_id: str
    scanner_id: str
    scanner_version: str
    schema_version: int
    observed_at: datetime
    received_at: datetime
    cycle_ref: str | None


class SiegeScannerEvidenceResponse(BaseModel):
    siege_id: int
    has_evidence: bool
    source_snapshot: SiegeEvidenceSourceSnapshot | None
    buildings_present: bool | None
    posts_present: bool | None
    buildings: list[ObservedBuildingResponse]
    posts: list[ObservedPostResponse]
