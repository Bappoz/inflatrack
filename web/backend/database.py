import os
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from uuid import UUID

from dotenv import load_dotenv
from sqlalchemy import DateTime, String, create_engine, func, select
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column
from sqlalchemy.pool import NullPool

load_dotenv(Path(__file__).with_name(".env"))


class DatabaseConfigurationError(RuntimeError):
    pass


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    __table_args__ = {"schema": "public"}

    email: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), unique=True)
    name: Mapped[str] = mapped_column(String)
    state: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


@lru_cache(maxsize=2)
def _engine(variable: str, value: str) -> Engine:
    url = make_url(value)
    if url.drivername not in ("postgres", "postgresql", "postgresql+psycopg"):
        raise DatabaseConfigurationError(f"{variable} deve apontar para PostgreSQL.")
    url = url.difference_update_query(["pgbouncer"])
    return create_engine(
        url.set(drivername="postgresql+psycopg"),
        connect_args={"connect_timeout": 5, "prepare_threshold": None},
        poolclass=NullPool,
        hide_parameters=True,
    )


def get_engine(variable: str = "DATABASE_URL") -> Engine:
    value = os.getenv(variable, "").strip()
    if not value:
        raise DatabaseConfigurationError(f"Configure {variable} no ambiente do backend.")
    return _engine(variable, value)


def check_user_store() -> None:
    with Session(get_engine()) as session:
        session.execute(select(User).limit(0))


def save_user(*, user_id: UUID, email: str, name: str, state: str | None) -> None:
    statement = insert(User).values(user_id=user_id, email=email.lower(), name=name, state=state)
    statement = statement.on_conflict_do_update(
        index_elements=[User.user_id],
        set_={
            "email": statement.excluded.email,
            "name": statement.excluded.name,
            "state": statement.excluded.state,
        },
    )
    with Session(get_engine()) as session, session.begin():
        session.execute(statement)


def migrate() -> None:
    script = Path(__file__).with_name("migrations") / "002_users.sql"
    with (
        get_engine("DIRECT_URL")
        .connect()
        .execution_options(isolation_level="AUTOCOMMIT") as connection
    ):
        connection.exec_driver_sql(script.read_text())


if __name__ == "__main__":
    from sqlalchemy.exc import SQLAlchemyError

    try:
        migrate()
    except (DatabaseConfigurationError, SQLAlchemyError):
        raise SystemExit(
            "Falha ao aplicar o esquema. Confira DIRECT_URL, a conexão e as permissões "
            "de acesso aos schemas auth e public."
        ) from None
    print("Tabela public.users e sincronização com Supabase Auth atualizadas.")
