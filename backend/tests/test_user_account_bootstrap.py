"""Trusted local bootstrap promotes exact Discord identity only."""

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app import cli
from app.db.base import Base
from app.models.user_account import UserAccount


@pytest.mark.asyncio
async def test_local_admin_bootstrap_is_exact_and_idempotent(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(cli, "AsyncSessionLocal", factory)
    discord_id = "123456789012345678"
    first = await cli.grant_role(discord_id, "admin")
    second = await cli.grant_role(discord_id, "admin")
    assert first == second
    with pytest.raises(ValueError, match="last active ADMIN"):
        await cli.grant_role(discord_id, "manager")
    async with factory() as db:
        accounts = (await db.execute(select(UserAccount))).scalars().all()
    assert len(accounts) == 1
    assert accounts[0].app_role == "admin"
    assert accounts[0].is_active is True
    assert accounts[0].member_id is None
    assert accounts[0].discord_user_id == discord_id
    await engine.dispose()


@pytest.mark.asyncio
async def test_local_bootstrap_rejects_username():
    with pytest.raises(ValueError, match="numeric Snowflake"):
        await cli.grant_role("someone", "admin")
