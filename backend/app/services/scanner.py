"""Transactional internal recording of normalized scanner evidence."""

import hashlib
import json
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.scanner import ObservedBuilding, ObservedPost, ScannerIdentity, ScannerSnapshot
from app.models.siege import Siege
from app.schemas.scanner import SnapshotEnvelope


class SnapshotConflict(ValueError):
    """A snapshot key was reused for different facts."""


async def record_snapshot(session: AsyncSession, envelope: SnapshotEnvelope) -> ScannerSnapshot:
    """Persist a batch without touching Manager planning tables.

    Caller must establish scanner identity/auth before invoking this internal service.
    Database uniqueness is the final deduplication guard for concurrent writers.
    """
    canonical = envelope.model_dump(mode="json")
    digest = hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    existing = (
        await session.execute(
            select(ScannerSnapshot).where(
                ScannerSnapshot.scanner_id == envelope.scanner_id,
                ScannerSnapshot.snapshot_id == envelope.snapshot_id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        if existing.content_digest != digest:
            raise SnapshotConflict("snapshot identity reused with different content")
        return existing

    if envelope.siege_id is not None and await session.get(Siege, envelope.siege_id) is None:
        raise ValueError("explicit siege_id does not exist")

    scanner = await session.get(ScannerIdentity, envelope.scanner_id)
    if scanner is None:
        scanner = ScannerIdentity(id=envelope.scanner_id)
        session.add(scanner)

    snapshot = ScannerSnapshot(
        scanner_id=envelope.scanner_id,
        snapshot_id=envelope.snapshot_id,
        schema_version=envelope.schema_version,
        scanner_version=envelope.scanner_version,
        observed_at=envelope.observed_at.astimezone(UTC),
        received_at=datetime.now(UTC),
        siege_id=envelope.siege_id,
        cycle_ref=envelope.cycle_ref,
        association_status="matched" if envelope.siege_id is not None else "unmatched",
        buildings_present=envelope.buildings is not None,
        posts_present=envelope.posts is not None,
        content_digest=digest,
    )
    session.add(snapshot)
    await session.flush()
    for row in envelope.buildings or []:
        session.add(ObservedBuilding(snapshot_id=snapshot.id, **row.model_dump()))
    for row in envelope.posts or []:
        session.add(ObservedPost(snapshot_id=snapshot.id, **row.model_dump()))
    await session.commit()
    return snapshot
