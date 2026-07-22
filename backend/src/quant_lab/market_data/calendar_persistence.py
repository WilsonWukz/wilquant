from __future__ import annotations

from datetime import UTC, date, datetime, time
from typing import cast
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Time,
    UniqueConstraint,
    func,
    select,
)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Mapped, Session, mapped_column

from quant_lab.datasets.errors import DatasetError
from quant_lab.db.sqlite import Base


class TradingCalendarModel(Base):
    __tablename__ = "trading_calendars"
    calendar_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    market: Mapped[str] = mapped_column(String(32), nullable=False)
    exchange: Mapped[str] = mapped_column(String(32), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class TradingCalendarVersionModel(Base):
    __tablename__ = "trading_calendar_versions"
    __table_args__ = (UniqueConstraint("calendar_id", "version"), UniqueConstraint("fingerprint"))
    trading_calendar_version_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    calendar_id: Mapped[str] = mapped_column(
        ForeignKey("trading_calendars.calendar_id", ondelete="RESTRICT"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    session_count: Mapped[int] = mapped_column(Integer, nullable=False)
    first_session_date: Mapped[date | None] = mapped_column(Date)
    last_session_date: Mapped[date | None] = mapped_column(Date)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TradingCalendarSessionModel(Base):
    __tablename__ = "trading_calendar_sessions"
    __table_args__ = (UniqueConstraint("calendar_version_id", "session_date"),)
    trading_calendar_session_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    calendar_version_id: Mapped[str] = mapped_column(
        ForeignKey("trading_calendar_versions.trading_calendar_version_id", ondelete="RESTRICT"),
        nullable=False,
    )
    session_date: Mapped[date] = mapped_column(Date, nullable=False)
    is_open: Mapped[bool] = mapped_column(Boolean, nullable=False)
    open_time: Mapped[time | None] = mapped_column(Time)
    close_time: Mapped[time | None] = mapped_column(Time)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    session_type: Mapped[str] = mapped_column(String(32), nullable=False)


class TradingCalendarRepository:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def create_calendar(
        self,
        *,
        name: str,
        market: str,
        exchange: str,
        timezone: str,
        source_type: str,
        source_name: str,
    ) -> TradingCalendarModel:
        with Session(self.engine) as session:
            model = TradingCalendarModel(
                calendar_id=str(uuid4()),
                name=name,
                market=market,
                exchange=exchange,
                timezone=timezone,
                source_type=source_type,
                source_name=source_name,
                created_at=datetime.now(UTC),
            )
            session.add(model)
            session.commit()
            session.refresh(model)
            session.expunge(model)
            return model

    def get_calendar(self, calendar_id: str) -> TradingCalendarModel:
        with Session(self.engine) as session:
            model = session.get(TradingCalendarModel, calendar_id)
            if model is None:
                raise DatasetError("CALENDAR_NOT_FOUND", "交易日日历不存在")
            session.expunge(model)
            return model

    def list_calendars(self) -> tuple[TradingCalendarModel, ...]:
        with Session(self.engine) as session:
            values = tuple(
                session.scalars(select(TradingCalendarModel).order_by(TradingCalendarModel.name))
            )
            for value in values:
                session.expunge(value)
            return values

    def create_version(
        self,
        *,
        calendar_id: str,
        source_sha256: str,
        schema_version: str,
        fingerprint: str,
        sessions: list[dict[str, object]],
    ) -> TradingCalendarVersionModel:
        now = datetime.now(UTC)
        dates = [cast(date, item["session_date"]) for item in sessions]
        with Session(self.engine) as session:
            calendar = session.get(TradingCalendarModel, calendar_id)
            if calendar is None:
                raise DatasetError("CALENDAR_NOT_FOUND", "交易日日历不存在")
            existing = session.scalar(
                select(TradingCalendarVersionModel).where(
                    TradingCalendarVersionModel.calendar_id == calendar_id,
                    TradingCalendarVersionModel.fingerprint == fingerprint,
                )
            )
            if existing is not None:
                session.expunge(existing)
                return existing
            version = (
                session.scalar(
                    select(func.max(TradingCalendarVersionModel.version)).where(
                        TradingCalendarVersionModel.calendar_id == calendar_id
                    )
                )
                or 0
            ) + 1
            model = TradingCalendarVersionModel(
                trading_calendar_version_id=str(uuid4()),
                calendar_id=calendar_id,
                version=version,
                status="VALIDATING",
                source_sha256=source_sha256,
                schema_version=schema_version,
                session_count=len(sessions),
                first_session_date=min(dates) if dates else None,
                last_session_date=max(dates) if dates else None,
                fingerprint=fingerprint,
                created_at=now,
                published_at=now,
            )
            session.add(model)
            session.flush()
            session.add_all(
                TradingCalendarSessionModel(
                    trading_calendar_session_id=str(uuid4()),
                    calendar_version_id=model.trading_calendar_version_id,
                    **item,
                )
                for item in sessions
            )
            model.status = "PUBLISHED"
            session.commit()
            session.refresh(model)
            session.expunge(model)
            return model

    def list_versions(self, calendar_id: str) -> tuple[TradingCalendarVersionModel, ...]:
        with Session(self.engine) as session:
            values = tuple(
                session.scalars(
                    select(TradingCalendarVersionModel)
                    .where(TradingCalendarVersionModel.calendar_id == calendar_id)
                    .order_by(TradingCalendarVersionModel.version)
                )
            )
            for value in values:
                session.expunge(value)
            return values

    def get_version(self, calendar_id: str, version_id: str) -> TradingCalendarVersionModel:
        with Session(self.engine) as session:
            value = session.scalar(
                select(TradingCalendarVersionModel).where(
                    TradingCalendarVersionModel.calendar_id == calendar_id,
                    TradingCalendarVersionModel.trading_calendar_version_id == version_id,
                )
            )
            if value is None:
                raise DatasetError("CALENDAR_VERSION_NOT_FOUND", "交易日日历版本不存在")
            session.expunge(value)
            return value

    def list_sessions(
        self,
        version_id: str,
        *,
        open_only: bool = False,
        start: date | None = None,
        end: date | None = None,
        limit: int = 1000,
        offset: int = 0,
    ) -> tuple[TradingCalendarSessionModel, ...]:
        if limit < 1 or limit > 5000 or offset < 0:
            raise DatasetError("INVALID_QUERY_LIMIT", "查询范围无效")
        statement = select(TradingCalendarSessionModel).where(
            TradingCalendarSessionModel.calendar_version_id == version_id
        )
        if open_only:
            statement = statement.where(TradingCalendarSessionModel.is_open.is_(True))
        if start is not None:
            statement = statement.where(TradingCalendarSessionModel.session_date >= start)
        if end is not None:
            statement = statement.where(TradingCalendarSessionModel.session_date <= end)
        statement = (
            statement.order_by(TradingCalendarSessionModel.session_date).limit(limit).offset(offset)
        )
        with Session(self.engine) as session:
            values = tuple(session.scalars(statement))
            for value in values:
                session.expunge(value)
            return values
