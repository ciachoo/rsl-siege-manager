"""Add scanner identity, snapshots and isolated building/Post observations.

Revision ID: 0013
Revises: 0012
"""

import sqlalchemy as sa

from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "scanner_identity",
        sa.Column("id", sa.String(length=128), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_table(
        "scanner_snapshot",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("scanner_id", sa.String(length=128), sa.ForeignKey("scanner_identity.id"), nullable=False),
        sa.Column("snapshot_id", sa.String(length=128), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("scanner_version", sa.String(length=64), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("siege_id", sa.Integer(), sa.ForeignKey("siege.id", ondelete="SET NULL"), nullable=True),
        sa.Column("cycle_ref", sa.String(length=256), nullable=True),
        sa.Column("association_status", sa.String(length=16), nullable=False),
        sa.Column("buildings_present", sa.Boolean(), nullable=False),
        sa.Column("posts_present", sa.Boolean(), nullable=False),
        sa.Column("content_digest", sa.String(length=64), nullable=False),
        sa.UniqueConstraint("scanner_id", "snapshot_id", name="uq_scanner_snapshot_identity"),
        sa.CheckConstraint("association_status IN ('matched','unmatched')", name="scanner_association_valid"),
    )
    op.create_table(
        "observed_building",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("snapshot_id", sa.Integer(), sa.ForeignKey("scanner_snapshot.id", ondelete="CASCADE"), nullable=False),
        sa.Column("external_building_id", sa.String(length=128), nullable=False),
        sa.Column("level", sa.Integer(), nullable=True),
        sa.Column("is_broken", sa.Boolean(), nullable=True),
        sa.UniqueConstraint("snapshot_id", "external_building_id", name="uq_observed_building_snapshot_external"),
    )
    op.create_table(
        "observed_post",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("snapshot_id", sa.Integer(), sa.ForeignKey("scanner_snapshot.id", ondelete="CASCADE"), nullable=False),
        sa.Column("external_post_id", sa.String(length=128), nullable=False),
        sa.Column("modifier_ids", sa.JSON(none_as_null=True), nullable=True),
        sa.UniqueConstraint("snapshot_id", "external_post_id", name="uq_observed_post_snapshot_external"),
    )


def downgrade() -> None:
    op.drop_table("observed_post")
    op.drop_table("observed_building")
    op.drop_table("scanner_snapshot")
    op.drop_table("scanner_identity")
