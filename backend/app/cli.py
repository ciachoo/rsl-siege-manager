"""Trusted local account bootstrap and recovery commands; no HTTP exposure."""

import argparse
import asyncio
import logging

from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.models.member import Member
from app.models.user_account import UserAccount

logger = logging.getLogger(__name__)


async def grant_role(discord_user_id: str, role: str) -> str:
    if not discord_user_id.isdigit() or len(discord_user_id) > 20 or len(discord_user_id) == 0:
        raise ValueError("Discord user ID must be a numeric Snowflake of at most 20 digits")
    async with AsyncSessionLocal() as db:
        async with db.begin():
            account = (
                await db.execute(
                    select(UserAccount)
                    .where(UserAccount.discord_user_id == discord_user_id)
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if account is None:
                member = (
                    await db.execute(select(Member).where(Member.discord_id == discord_user_id))
                ).scalar_one_or_none()
                account = UserAccount(
                    discord_user_id=discord_user_id,
                    display_name=member.name if member else f"Discord user {discord_user_id}",
                    member_id=member.id if member else None,
                )
                db.add(account)
                await db.flush()
            elif account.app_role == "admin" and account.is_active and role != "admin":
                another_admin = (
                    await db.execute(
                        select(UserAccount.id)
                        .where(
                            UserAccount.app_role == "admin",
                            UserAccount.is_active.is_(True),
                            UserAccount.id != account.id,
                        )
                        .limit(1)
                    )
                ).scalar_one_or_none()
                if another_admin is None:
                    raise ValueError("Cannot downgrade the last active ADMIN")
            account.app_role = role
            account.is_active = True
            account_id = account.id
    logger.warning("local_user_role_grant account_id=%s role=%s", account_id, role)
    return f"Account {account_id}: active {role}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Local Manager user role bootstrap")
    parser.add_argument("resource", choices=["users"])
    parser.add_argument("action", choices=["grant-admin", "grant-manager"])
    parser.add_argument("discord_user_id")
    args = parser.parse_args()
    role = "admin" if args.action == "grant-admin" else "manager"
    try:
        print(asyncio.run(grant_role(args.discord_user_id, role)))
    except ValueError as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
