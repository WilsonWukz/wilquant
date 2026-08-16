from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import DateTime, Engine, String, Text, create_engine, event, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from quant_lab.core.config import Settings


class Base(DeclarativeBase):
    """Declarative base for the SQLite control plane."""


class AppMetadata(Base):
    """Non-sensitive application metadata created by the initial migration."""

    __tablename__ = "app_metadata"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )


def ensure_sqlite_database_parent(database_url: str) -> None:
    """Create only the direct parent directory of a local SQLite file database.

    This is the narrow SQLite bootstrap contract. FastAPI owns the full runtime
    tree via lifespan startup, but Alembic can run before that tree exists, so
    the database file's immediate parent must be ensured right before the engine
    opens it. In-memory and non-SQLite URLs are no-ops, and importing this module
    has no filesystem side effect.
    """

    url = make_url(database_url)
    if url.get_backend_name() != "sqlite":
        return
    database = url.database
    if not database or database == ":memory:":
        return
    Path(database).parent.mkdir(parents=True, exist_ok=True)


def create_sqlite_engine(settings: Settings) -> Engine:
    """Create a SQLite engine with conservative local-process settings."""

    ensure_sqlite_database_parent(settings.sqlite_url)
    engine = create_engine(
        settings.sqlite_url,
        connect_args={"check_same_thread": False, "timeout": 5.0},
    )

    @event.listens_for(engine, "connect")
    def configure_connection(dbapi_connection, _connection_record) -> None:  # type: ignore[no-untyped-def]
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=5000")
        finally:
            cursor.close()

    return engine


def probe_sqlite(engine: Engine) -> bool:
    """Raise on connection failure and return true after a successful probe."""

    with engine.connect() as connection:
        result = connection.execute(text("SELECT 1")).scalar_one()
    return result == 1
