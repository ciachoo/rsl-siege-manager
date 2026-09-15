"""Application human identity, separate from Siege participant Member."""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class UserAccount(Base):
    __tablename__ = "user_account"
    __table_args__ = (
        CheckConstraint(
            "app_role IN ('viewer','manager','admin')", name="ck_user_account_app_role"
        ),
        UniqueConstraint("discord_user_id", name="uq_user_account_discord_user_id"),
        UniqueConstraint("member_id", name="uq_user_account_member_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    discord_user_id: Mapped[str] = mapped_column(String(20), nullable=False)
    display_name: Mapped[str] = mapped_column(String(256), nullable=False)
    app_role: Mapped[str] = mapped_column(
        String(16), nullable=False, default="viewer", server_default=text("'viewer'")
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    member_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("member.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
