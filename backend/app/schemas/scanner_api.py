"""Safe Scanner ingestion acknowledgement."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class SnapshotReceipt(BaseModel):
    snapshot_id: str
    status: Literal["created", "duplicate"]
    received_at: datetime
    association_status: Literal["matched", "unmatched"]
    siege_id: int | None
