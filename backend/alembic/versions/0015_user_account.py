"""Add Manager-owned human identity and role.

Revision ID: 0015
Revises: 0014
"""

import sqlalchemy as sa

from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_account",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("discord_user_id", sa.String(length=20), nullable=False),
        sa.Column("display_name", sa.String(length=256), nullable=False),
        sa.Column("app_role", sa.String(length=16), server_default=sa.text("'viewer'"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("member_id", sa.Integer(), sa.ForeignKey("member.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("app_role IN ('viewer','manager','admin')", name="ck_user_account_app_role"),
        sa.UniqueConstraint("discord_user_id", name="uq_user_account_discord_user_id"),
        sa.UniqueConstraint("member_id", name="uq_user_account_member_id"),
    )
    connection = op.get_bind()
    rows = connection.execute(
        sa.text("SELECT id, name, discord_id FROM member WHERE discord_id IS NOT NULL ORDER BY id")
    ).mappings()
    for row in rows:
        discord_id = row["discord_id"]
        if not discord_id.isdigit() or len(discord_id) > 20:
            raise ValueError(f"Invalid Member Discord ID for backfill: member id {row['id']}")
        connection.execute(
            sa.text(
                "INSERT INTO user_account (discord_user_id, display_name, app_role, is_active, member_id) "
                "VALUES (:discord_id, :display_name, 'viewer', true, :member_id)"
            ),
            {"discord_id": discord_id, "display_name": row["name"], "member_id": row["id"]},
        )


def downgrade() -> None:
    op.drop_table("user_account")
