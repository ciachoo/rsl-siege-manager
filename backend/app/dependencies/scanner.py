"""Scanner-only Bearer authentication, independent of Manager auth bypass."""

from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.scanner import ScannerIdentity
from app.services.scanner_credentials import authenticate_scanner


async def get_authenticated_scanner(
    request: Request, db: AsyncSession = Depends(get_db)
) -> ScannerIdentity:
    authorization = request.headers.get("Authorization", "")
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Scanner credential required")
    credential = authorization.removeprefix("Bearer ")
    scanner = await authenticate_scanner(db, credential)
    if scanner is None:
        raise HTTPException(status_code=401, detail="Invalid scanner credential")
    return scanner
