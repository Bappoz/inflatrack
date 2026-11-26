from uuid import UUID

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from web.backend import database


def test_save_user_updates_existing_profile_without_duplicates(monkeypatch):
    engine = create_engine(
        "sqlite://", execution_options={"schema_translate_map": {"public": None}}
    )
    database.Base.metadata.create_all(engine)
    monkeypatch.setattr(database, "get_engine", lambda: engine)
    user_id = UUID("adfb6a89-3f53-4c72-9b10-ff65dd8b1eea")
    try:
        database.check_user_store()
        database.save_user(user_id=user_id, email="ANA@example.com", name="Ana", state="DF")
        database.save_user(user_id=user_id, email="novo@example.com", name="Ana Silva", state="BA")
        with Session(engine) as session:
            users = session.scalars(select(database.User)).all()
            assert len(users) == 1
            assert users[0].user_id == user_id
            assert users[0].email == "novo@example.com"
            assert users[0].name == "Ana Silva"
            assert users[0].state == "BA"
            assert users[0].created_at is not None
    finally:
        engine.dispose()


def test_database_url_is_required(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(database.DatabaseConfigurationError, match="DATABASE_URL"):
        database.get_engine()


def test_prisma_pooler_option_is_not_forwarded_to_psycopg():
    engine = database._engine(
        "DATABASE_URL", "postgresql://localhost/postgres?pgbouncer=true&sslmode=require"
    )
    try:
        assert engine.url.drivername == "postgresql+psycopg"
        assert "pgbouncer" not in engine.url.query
        assert engine.url.query["sslmode"] == "require"
    finally:
        engine.dispose()
        database._engine.cache_clear()


def test_migration_uses_direct_url(monkeypatch):
    events = []

    class Connection:
        def execution_options(self, **options):
            events.append(options)
            return self

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def exec_driver_sql(self, script):
            events.append(script)

    class Engine:
        def connect(self):
            return Connection()

    def get_engine(variable):
        events.append(variable)
        return Engine()

    monkeypatch.setattr(database, "get_engine", get_engine)
    database.migrate()
    assert events[0] == "DIRECT_URL"
    assert events[1] == {"isolation_level": "AUTOCOMMIT"}
    assert "create table if not exists public.users" in events[2]
