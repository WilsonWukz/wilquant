from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, Engine, String, Text, create_engine, event, text
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


def create_sqlite_engine(settings: Settings) -> Engine:
    """Create a SQLite engine with conservative local-process settings."""

    settings.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
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
