"""Scanner evidence is separate from Siege planning records."""

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class ScannerIdentity(Base):
    __tablename__ = "scanner_identity"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    snapshots: Mapped[list["ScannerSnapshot"]] = relationship(back_populates="scanner")


class ScannerSnapshot(Base):
    __tablename__ = "scanner_snapshot"
    __table_args__ = (
        UniqueConstraint("scanner_id", "snapshot_id", name="uq_scanner_snapshot_identity"),
        CheckConstraint(
            "association_status IN ('matched','unmatched')", name="scanner_association_valid"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scanner_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("scanner_identity.id"), nullable=False
    )
    snapshot_id: Mapped[str] = mapped_column(String(128), nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    scanner_version: Mapped[str] = mapped_column(String(64), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    siege_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("siege.id", ondelete="SET NULL"), nullable=True
    )
    cycle_ref: Mapped[str | None] = mapped_column(String(256), nullable=True)
    association_status: Mapped[str] = mapped_column(String(16), nullable=False)
    buildings_present: Mapped[bool] = mapped_column(Boolean, nullable=False)
    posts_present: Mapped[bool] = mapped_column(Boolean, nullable=False)
    content_digest: Mapped[str] = mapped_column(String(64), nullable=False)

    scanner: Mapped[ScannerIdentity] = relationship(back_populates="snapshots")
    buildings: Mapped[list["ObservedBuilding"]] = relationship(
        back_populates="snapshot", cascade="all, delete-orphan"
    )
    posts: Mapped[list["ObservedPost"]] = relationship(
        back_populates="snapshot", cascade="all, delete-orphan"
    )


class ObservedBuilding(Base):
    __tablename__ = "observed_building"
    __table_args__ = (
        UniqueConstraint(
            "snapshot_id", "external_building_id", name="uq_observed_building_snapshot_external"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("scanner_snapshot.id", ondelete="CASCADE"), nullable=False
    )
    external_building_id: Mapped[str] = mapped_column(String(128), nullable=False)
    level: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_broken: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    snapshot: Mapped[ScannerSnapshot] = relationship(back_populates="buildings")


class ObservedPost(Base):
    __tablename__ = "observed_post"
    __table_args__ = (
        UniqueConstraint(
            "snapshot_id", "external_post_id", name="uq_observed_post_snapshot_external"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("scanner_snapshot.id", ondelete="CASCADE"), nullable=False
    )
    external_post_id: Mapped[str] = mapped_column(String(128), nullable=False)
    modifier_ids: Mapped[list[str] | None] = mapped_column(JSON(none_as_null=True), nullable=True)

    snapshot: Mapped[ScannerSnapshot] = relationship(back_populates="posts")
