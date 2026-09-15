"""Internal normalized scanner contract; not a public delivery API."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class BuildingObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    external_building_id: str = Field(min_length=1, max_length=128)
    level: int | None = Field(default=None, ge=1)
    is_broken: bool | None = None


class PostObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    external_post_id: str = Field(min_length=1, max_length=128)
    modifier_ids: list[str] | None = None

    @field_validator("modifier_ids")
    @classmethod
    def unique_bounded_modifiers(cls, value: list[str] | None) -> list[str] | None:
        if value is not None and (
            len(value) > 3
            or len(set(value)) != len(value)
            or any(not x or len(x) > 128 for x in value)
        ):
            raise ValueError("modifier_ids must contain at most three distinct nonempty IDs")
        return value


class SnapshotEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: int = Field(ge=1)
    snapshot_id: str = Field(min_length=1, max_length=128)
    scanner_id: str = Field(min_length=1, max_length=128)
    scanner_version: str = Field(min_length=1, max_length=64)
    observed_at: datetime
    siege_id: int | None = Field(default=None, ge=1)
    cycle_ref: str | None = Field(default=None, max_length=256)
    buildings: list[BuildingObservation] | None = Field(default=None, max_length=100)
    posts: list[PostObservation] | None = Field(default=None, max_length=100)

    @field_validator("observed_at")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("observed_at must include a timezone")
        return value

    @model_validator(mode="after")
    def unique_external_ids(self) -> "SnapshotEnvelope":
        for observations, field in (
            (self.buildings or [], "external_building_id"),
            (self.posts or [], "external_post_id"),
        ):
            identifiers = [getattr(row, field) for row in observations]
            if len(identifiers) != len(set(identifiers)):
                raise ValueError(f"duplicate {field} in snapshot")
        return self
