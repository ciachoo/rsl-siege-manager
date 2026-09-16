"""Explicit read-only contracts for persisted Scanner evidence."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class ScannerSnapshotSummary(BaseModel):
    id: int
    snapshot_id: str
    scanner_id: str
    scanner_version: str
    schema_version: int
    observed_at: datetime
    received_at: datetime
    siege_id: int | None
    association_status: Literal["matched", "unmatched"]
    cycle_ref: str | None
    buildings_present: bool
    posts_present: bool


class ObservedBuildingResponse(BaseModel):
    external_building_id: str
    level: int | None
    is_broken: bool | None


class ObservedPostResponse(BaseModel):
    external_post_id: str
    modifier_ids: list[str] | None


class ScannerSnapshotDetail(ScannerSnapshotSummary):
    buildings: list[ObservedBuildingResponse]
    posts: list[ObservedPostResponse]
