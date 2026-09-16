"""Safe ADMIN contracts for Scanner identity and credential lifecycle."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ScannerCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scanner_id: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$",
    )


class ScannerMetadata(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    created_at: datetime
    credential_revoked_at: datetime | None
    is_active: bool


class ScannerCredentialIssued(BaseModel):
    scanner: ScannerMetadata
    credential: str = Field(repr=False)
