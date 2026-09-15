"""0015 backfill against an isolated database; no production downgrade."""

import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.exc import IntegrityError


def _revision():
    path = Path(__file__).parents[1] / "alembic" / "versions" / "0015_user_account.py"
    spec = importlib.util.spec_from_file_location("user_account_revision", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_0015_backfills_only_discord_members_as_active_viewers():
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        connection.exec_driver_sql(
            "CREATE TABLE member (id INTEGER PRIMARY KEY, name VARCHAR NOT NULL, "
            "discord_id VARCHAR UNIQUE, role VARCHAR NOT NULL, is_active BOOLEAN NOT NULL)"
        )
        connection.exec_driver_sql(
            "INSERT INTO member VALUES "
            "(1,'Inactive player','123456789012345678','heavy_hitter',false), "
            "(2,'No Discord',NULL,'advanced',true)"
        )
        revision = _revision()
        revision.op = Operations(MigrationContext.configure(connection))
        revision.upgrade()
        rows = connection.exec_driver_sql(
            "SELECT discord_user_id, display_name, app_role, is_active, member_id, last_login_at "
            "FROM user_account"
        ).all()
        assert rows == [("123456789012345678", "Inactive player", "viewer", 1, 1, None)]
        with pytest.raises(IntegrityError):
            connection.exec_driver_sql(
                "INSERT INTO user_account (discord_user_id, display_name, app_role, member_id) "
                "VALUES ('999999999999999999','Wrong','powerful',2)"
            )
        with pytest.raises(IntegrityError):
            connection.exec_driver_sql(
                "INSERT INTO user_account (discord_user_id, display_name, member_id) "
                "VALUES ('123456789012345678','Duplicate',2)"
            )
        with pytest.raises(IntegrityError):
            connection.exec_driver_sql(
                "INSERT INTO user_account (discord_user_id, display_name, member_id) "
                "VALUES ('888888888888888888','Duplicate link',1)"
            )


def test_0015_rejects_malformed_existing_discord_identity():
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE member (id INTEGER PRIMARY KEY, name VARCHAR, discord_id VARCHAR)"
        )
        connection.exec_driver_sql("INSERT INTO member VALUES (1,'A','not-a-snowflake')")
        revision = _revision()
        revision.op = Operations(MigrationContext.configure(connection))
        with pytest.raises(ValueError, match="Invalid Member Discord ID"):
            revision.upgrade()
