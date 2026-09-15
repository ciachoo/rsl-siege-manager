"""Add nullable Scanner credential verifier and revocation metadata.

Revision ID: 0014
Revises: 0013
"""

import sqlalchemy as sa

from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("scanner_identity", sa.Column("credential_selector", sa.String(length=32), nullable=True))
    op.add_column("scanner_identity", sa.Column("credential_verifier", sa.String(length=64), nullable=True))
    op.add_column("scanner_identity", sa.Column("credential_revoked_at", sa.DateTime(timezone=True), nullable=True))
    with op.batch_alter_table("scanner_identity") as batch_op:
        batch_op.create_unique_constraint("uq_scanner_credential_selector", ["credential_selector"])


def downgrade() -> None:
    with op.batch_alter_table("scanner_identity") as batch_op:
        batch_op.drop_constraint("uq_scanner_credential_selector", type_="unique")
        batch_op.drop_column("credential_revoked_at")
        batch_op.drop_column("credential_verifier")
        batch_op.drop_column("credential_selector")
