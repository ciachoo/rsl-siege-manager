"""Narrow normalized Scanner snapshot ingestion route."""

import json
import logging
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.dependencies.scanner import get_authenticated_scanner
from app.models.scanner import ScannerIdentity
from app.schemas.scanner import SnapshotEnvelope
from app.schemas.scanner_api import SnapshotReceipt
from app.services.scanner import SnapshotConflict, record_snapshot_with_status

router = APIRouter(prefix="/scanner", tags=["scanner"])
logger = logging.getLogger(__name__)

MAX_SNAPSHOT_BYTES = 256 * 1024
MAX_FUTURE_SKEW = timedelta(minutes=10)
SUPPORTED_SCHEMA_VERSIONS = {1}


@router.post("/snapshots", response_model=SnapshotReceipt, status_code=201)
async def ingest_snapshot(
    request: Request,
    response: Response,
    scanner: ScannerIdentity = Depends(get_authenticated_scanner),
    db: AsyncSession = Depends(get_db),
) -> SnapshotReceipt:
    content_length = request.headers.get("Content-Length")
    if content_length is not None:
        try:
            if int(content_length) > MAX_SNAPSHOT_BYTES:
                raise HTTPException(status_code=413, detail="Snapshot exceeds size limit")
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid Content-Length") from None
    raw = bytearray()
    async for chunk in request.stream():
        if len(raw) + len(chunk) > MAX_SNAPSHOT_BYTES:
            raise HTTPException(status_code=413, detail="Snapshot exceeds size limit")
        raw.extend(chunk)
    try:
        envelope = SnapshotEnvelope.model_validate(json.loads(raw))
    except (ValueError, ValidationError, UnicodeDecodeError, TypeError):
        raise HTTPException(status_code=422, detail="Invalid snapshot envelope") from None

    if envelope.schema_version not in SUPPORTED_SCHEMA_VERSIONS:
        raise HTTPException(status_code=422, detail="Unsupported scanner schema_version")
    if envelope.scanner_id != scanner.id:
        raise HTTPException(status_code=403, detail="Scanner identity mismatch")
    if envelope.observed_at.astimezone(UTC) > datetime.now(UTC) + MAX_FUTURE_SKEW:
        raise HTTPException(status_code=422, detail="observed_at is unreasonably future-dated")

    try:
        snapshot, duplicate = await record_snapshot_with_status(db, envelope)
    except SnapshotConflict:
        raise HTTPException(status_code=409, detail="Snapshot identity conflict") from None
    except ValueError as exc:
        if str(exc) == "explicit siege_id does not exist":
            raise HTTPException(status_code=422, detail="Unknown explicit siege_id") from None
        raise

    if duplicate:
        response.status_code = 200
    logger.info(
        "scanner_snapshot_result scanner_id=%r snapshot_id=%r status=%s "
        "association=%s buildings=%d posts=%d",
        scanner.id,
        envelope.snapshot_id,
        "duplicate" if duplicate else "created",
        snapshot.association_status,
        len(envelope.buildings or []),
        len(envelope.posts or []),
    )
    return SnapshotReceipt(
        snapshot_id=snapshot.snapshot_id,
        status="duplicate" if duplicate else "created",
        received_at=snapshot.received_at,
        association_status=snapshot.association_status,
        siege_id=snapshot.siege_id,
    )
