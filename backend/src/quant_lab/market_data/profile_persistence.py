from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, String, Text, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Mapped, Session, mapped_column

from quant_lab.datasets.errors import DatasetError
from quant_lab.db.sqlite import Base


class MarketDataProfileModel(Base):
    __tablename__ = "market_data_profiles"
    profile_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    market: Mapped[str] = mapped_column(String(32), nullable=False)
    bar_frequency: Mapped[str] = mapped_column(String(32), nullable=False)
    bars_dataset_id: Mapped[str] = mapped_column(
        ForeignKey("datasets.dataset_id", ondelete="RESTRICT"), nullable=False
    )
    bars_dataset_version_id: Mapped[str] = mapped_column(
        ForeignKey("dataset_versions.dataset_version_id", ondelete="RESTRICT"), nullable=False
    )
    calendar_id: Mapped[str] = mapped_column(
        ForeignKey("trading_calendars.calendar_id", ondelete="RESTRICT"), nullable=False
    )
    calendar_version_id: Mapped[str] = mapped_column(
        ForeignKey("trading_calendar_versions.trading_calendar_version_id", ondelete="RESTRICT"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MarketDataProfileAuditModel(Base):
    __tablename__ = "market_data_profile_audits"
    audit_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    profile_id: Mapped[str] = mapped_column(
        ForeignKey("market_data_profiles.profile_id", ondelete="RESTRICT"), nullable=False
    )
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    before_json: Mapped[str | None] = mapped_column(Text)
    after_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MarketDataProfileRepository:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def create(self, **values: object) -> MarketDataProfileModel:
        now = datetime.now(UTC)
        with Session(self.engine) as session:
            model = MarketDataProfileModel(
                profile_id=str(uuid4()), status="ACTIVE", created_at=now, updated_at=now, **values
            )
            session.add(model)
            session.add(
                MarketDataProfileAuditModel(
                    audit_id=str(uuid4()),
                    profile_id=model.profile_id,
                    action="CREATE",
                    before_json=None,
                    after_json=str(values),
                    created_at=now,
                )
            )
            session.commit()
            session.refresh(model)
            session.expunge(model)
            return model

    def list(self) -> tuple[MarketDataProfileModel, ...]:
        with Session(self.engine) as session:
            values = tuple(
                session.scalars(
                    select(MarketDataProfileModel).order_by(MarketDataProfileModel.name)
                )
            )
            for value in values:
                session.expunge(value)
            return values

    def get(self, profile_id: str) -> MarketDataProfileModel:
        with Session(self.engine) as session:
            value = session.get(MarketDataProfileModel, profile_id)
            if value is None:
                raise DatasetError("PROFILE_NOT_FOUND", "市场数据配置不存在")
            session.expunge(value)
            return value

    def update_bindings(self, profile_id: str, values: dict[str, object]) -> MarketDataProfileModel:
        now = datetime.now(UTC)
        with Session(self.engine) as session:
            model = session.get(MarketDataProfileModel, profile_id)
            if model is None:
                raise DatasetError("PROFILE_NOT_FOUND", "市场数据配置不存在")
            before = {key: getattr(model, key) for key in values}
            for key, value in values.items():
                setattr(model, key, value)
            model.updated_at = now
            session.add(
                MarketDataProfileAuditModel(
                    audit_id=str(uuid4()),
                    profile_id=profile_id,
                    action="UPDATE_BINDING",
                    before_json=str(before),
                    after_json=str(values),
                    created_at=now,
                )
            )
            session.commit()
            session.refresh(model)
            session.expunge(model)
            return model
