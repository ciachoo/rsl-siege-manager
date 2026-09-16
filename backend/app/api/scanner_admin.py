"""ADMIN-only Scanner identity and credential management."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.dependencies.auth import require_admin
from app.models.scanner import ScannerIdentity
from app.schemas.scanner_admin import (
    ScannerCreateRequest,
    ScannerCredentialIssued,
    ScannerMetadata,
)
from app.services.scanner_credentials import (
    list_scanners,
    provision_scanner,
    revoke_scanner,
    rotate_scanner_credential,
)

router = APIRouter(prefix="/scanners", tags=["scanner-admin"])


def _metadata(scanner: ScannerIdentity) -> ScannerMetadata:
    return ScannerMetadata(
        id=scanner.id,
        created_at=scanner.created_at,
        credential_revoked_at=scanner.credential_revoked_at,
        is_active=(
            scanner.credential_selector is not None
            and scanner.credential_verifier is not None
            and scanner.credential_revoked_at is None
        ),
    )


@router.post(
    "",
    response_model=ScannerCredentialIssued,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_admin)],
)
async def create_scanner(
    body: ScannerCreateRequest,
    db: AsyncSession = Depends(get_db),
) -> ScannerCredentialIssued:
    try:
        scanner, credential = await provision_scanner(db, body.scanner_id)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Scanner provisioning conflict") from None
    except ValueError as exc:
        if str(exc) == "scanner is already provisioned; rotate instead":
            raise HTTPException(status_code=409, detail="Scanner is already provisioned") from None
        raise
    return ScannerCredentialIssued(scanner=_metadata(scanner), credential=credential)


@router.get(
    "",
    response_model=list[ScannerMetadata],
    dependencies=[Depends(require_admin)],
)
async def get_scanners(db: AsyncSession = Depends(get_db)) -> list[ScannerMetadata]:
    return [_metadata(scanner) for scanner in await list_scanners(db)]


@router.get(
    "/{scanner_id}",
    response_model=ScannerMetadata,
    dependencies=[Depends(require_admin)],
)
async def get_scanner(
    scanner_id: str,
    db: AsyncSession = Depends(get_db),
) -> ScannerMetadata:
    scanner = await db.get(ScannerIdentity, scanner_id)
    if scanner is None:
        raise HTTPException(status_code=404, detail="Scanner not found")
    return _metadata(scanner)


@router.post(
    "/{scanner_id}/rotate-credential",
    response_model=ScannerCredentialIssued,
    dependencies=[Depends(require_admin)],
)
async def rotate_scanner(
    scanner_id: str,
    db: AsyncSession = Depends(get_db),
) -> ScannerCredentialIssued:
    try:
        credential = await rotate_scanner_credential(db, scanner_id)
    except ValueError as exc:
        if str(exc) == "scanner not found":
            raise HTTPException(status_code=404, detail="Scanner not found") from None
        raise
    scanner = await db.get(ScannerIdentity, scanner_id)
    assert scanner is not None
    return ScannerCredentialIssued(scanner=_metadata(scanner), credential=credential)


@router.post(
    "/{scanner_id}/revoke",
    response_model=ScannerMetadata,
    dependencies=[Depends(require_admin)],
)
async def revoke_scanner_credential(
    scanner_id: str,
    db: AsyncSession = Depends(get_db),
) -> ScannerMetadata:
    if not await revoke_scanner(db, scanner_id):
        raise HTTPException(status_code=404, detail="Scanner not found")
    scanner = await db.get(ScannerIdentity, scanner_id)
    assert scanner is not None
    return _metadata(scanner)
