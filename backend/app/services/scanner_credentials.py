"""Internal scanner credential lifecycle; no browser or bot credential reuse."""

import hashlib
import secrets
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.scanner import ScannerIdentity

_PREFIX = "ssm_scanner_"


def _new_credential() -> tuple[str, str, str]:
    selector = secrets.token_hex(16)
    secret = secrets.token_urlsafe(32)
    return selector, hashlib.sha256(secret.encode()).hexdigest(), f"{_PREFIX}{selector}.{secret}"


async def provision_scanner(
    session: AsyncSession, scanner_id: str | None = None
) -> tuple[ScannerIdentity, str]:
    """Issue a credential from a trusted operator context; plaintext is returned once."""
    if scanner_id is None:
        scanner_id = f"scanner_{secrets.token_hex(16)}"
    if not scanner_id or len(scanner_id) > 128:
        raise ValueError("invalid scanner_id")
    scanner = await session.get(ScannerIdentity, scanner_id)
    if scanner is None:
        scanner = ScannerIdentity(id=scanner_id)
        session.add(scanner)
    elif scanner.credential_selector is not None:
        raise ValueError("scanner is already provisioned; rotate instead")
    selector, verifier, plaintext = _new_credential()
    scanner.credential_selector = selector
    scanner.credential_verifier = verifier
    scanner.credential_revoked_at = None
    await session.commit()
    return scanner, plaintext


async def rotate_scanner_credential(session: AsyncSession, scanner_id: str) -> str:
    scanner = await session.get(ScannerIdentity, scanner_id)
    if scanner is None:
        raise ValueError("scanner not found")
    selector, verifier, plaintext = _new_credential()
    scanner.credential_selector = selector
    scanner.credential_verifier = verifier
    scanner.credential_revoked_at = None
    await session.commit()
    return plaintext


async def revoke_scanner(session: AsyncSession, scanner_id: str) -> bool:
    scanner = await session.get(ScannerIdentity, scanner_id)
    if scanner is None:
        return False
    if scanner.credential_revoked_at is not None:
        return True
    scanner.credential_revoked_at = datetime.now(UTC)
    await session.commit()
    return True


async def list_scanners(session: AsyncSession) -> list[ScannerIdentity]:
    """Return stable Scanner identities without exposing credential verifiers."""
    return list(
        (await session.execute(select(ScannerIdentity).order_by(ScannerIdentity.id)))
        .scalars()
        .all()
    )


async def authenticate_scanner(session: AsyncSession, credential: str) -> ScannerIdentity | None:
    """Resolve one installation by selector, then compare its 256-bit secret verifier."""
    if not credential.startswith(_PREFIX) or len(credential) > 128:
        return None
    selector_and_secret = credential.removeprefix(_PREFIX).split(".", 1)
    if len(selector_and_secret) != 2:
        return None
    selector, secret = selector_and_secret
    if len(selector) != 32 or not secret or len(secret) > 64:
        return None
    scanner = (
        await session.execute(
            select(ScannerIdentity).where(ScannerIdentity.credential_selector == selector)
        )
    ).scalar_one_or_none()
    if (
        scanner is None
        or scanner.credential_revoked_at is not None
        or scanner.credential_verifier is None
    ):
        return None
    provided = hashlib.sha256(secret.encode()).hexdigest()
    if not secrets.compare_digest(provided, scanner.credential_verifier):
        return None
    return scanner
