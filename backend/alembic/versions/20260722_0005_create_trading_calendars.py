from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260722_0005"
down_revision: str | None = "20260720_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "trading_calendars",
        sa.Column("calendar_id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("market", sa.String(32), nullable=False),
        sa.Column("exchange", sa.String(32), nullable=False),
        sa.Column("timezone", sa.String(64), nullable=False),
        sa.Column("source_type", sa.String(32), nullable=False),
        sa.Column("source_name", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "trading_calendar_versions",
        sa.Column("trading_calendar_version_id", sa.String(36), primary_key=True),
        sa.Column(
            "calendar_id",
            sa.String(36),
            sa.ForeignKey("trading_calendars.calendar_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("source_sha256", sa.String(64), nullable=False),
        sa.Column("schema_version", sa.String(64), nullable=False),
        sa.Column("session_count", sa.Integer(), nullable=False),
        sa.Column("first_session_date", sa.Date()),
        sa.Column("last_session_date", sa.Date()),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint(
            "calendar_id", "version", name="uq_trading_calendar_versions_calendar_version"
        ),
        sa.UniqueConstraint("fingerprint", name="uq_trading_calendar_versions_fingerprint"),
    )
    op.create_table(
        "trading_calendar_sessions",
        sa.Column("trading_calendar_session_id", sa.String(36), primary_key=True),
        sa.Column(
            "calendar_version_id",
            sa.String(36),
            sa.ForeignKey(
                "trading_calendar_versions.trading_calendar_version_id", ondelete="RESTRICT"
            ),
            nullable=False,
        ),
        sa.Column("session_date", sa.Date(), nullable=False),
        sa.Column("is_open", sa.Boolean(), nullable=False),
        sa.Column("open_time", sa.Time()),
        sa.Column("close_time", sa.Time()),
        sa.Column("timezone", sa.String(64), nullable=False),
        sa.Column("session_type", sa.String(32), nullable=False),
        sa.UniqueConstraint(
            "calendar_version_id", "session_date", name="uq_trading_calendar_sessions_version_date"
        ),
    )
    op.execute("""
        CREATE TRIGGER trg_trading_calendar_versions_published_no_update
        BEFORE UPDATE ON trading_calendar_versions
        WHEN OLD.status = 'PUBLISHED'
        BEGIN SELECT RAISE(ABORT, 'PUBLISHED trading calendar version is immutable'); END;
    """)
    op.execute("""
        CREATE TRIGGER trg_trading_calendar_versions_published_no_delete
        BEFORE DELETE ON trading_calendar_versions
        WHEN OLD.status = 'PUBLISHED'
        BEGIN SELECT RAISE(ABORT, 'PUBLISHED trading calendar version is immutable'); END;
    """)
    op.execute("""
        CREATE TRIGGER trg_trading_calendar_sessions_published_no_insert
        BEFORE INSERT ON trading_calendar_sessions
        WHEN (SELECT status FROM trading_calendar_versions
              WHERE trading_calendar_version_id = NEW.calendar_version_id) = 'PUBLISHED'
        BEGIN SELECT RAISE(ABORT, 'PUBLISHED trading calendar sessions are immutable'); END;
    """)
    op.execute("""
        CREATE TRIGGER trg_trading_calendar_sessions_published_no_update
        BEFORE UPDATE ON trading_calendar_sessions
        WHEN (SELECT status FROM trading_calendar_versions
              WHERE trading_calendar_version_id = OLD.calendar_version_id) = 'PUBLISHED'
        BEGIN SELECT RAISE(ABORT, 'PUBLISHED trading calendar sessions are immutable'); END;
    """)
    op.execute("""
        CREATE TRIGGER trg_trading_calendar_sessions_published_no_delete
        BEFORE DELETE ON trading_calendar_sessions
        WHEN (SELECT status FROM trading_calendar_versions
              WHERE trading_calendar_version_id = OLD.calendar_version_id) = 'PUBLISHED'
        BEGIN SELECT RAISE(ABORT, 'PUBLISHED trading calendar sessions are immutable'); END;
    """)


def downgrade() -> None:
    for name in (
        "trg_trading_calendar_sessions_published_no_insert",
        "trg_trading_calendar_sessions_published_no_delete",
        "trg_trading_calendar_sessions_published_no_update",
        "trg_trading_calendar_versions_published_no_delete",
        "trg_trading_calendar_versions_published_no_update",
    ):
        op.execute(f"DROP TRIGGER IF EXISTS {name}")
    op.drop_table("trading_calendar_sessions")
    op.drop_table("trading_calendar_versions")
    op.drop_table("trading_calendars")
