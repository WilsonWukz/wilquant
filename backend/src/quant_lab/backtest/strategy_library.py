from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import ClassVar
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from quant_lab.datasets.errors import DatasetError
from quant_lab.datasets.fingerprints import canonical_json, sha256_text
from quant_lab.db.sqlite import Base


class StrategyDefinitionModel(Base):
    __tablename__ = "strategy_definitions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    strategy_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class StrategyVersionModel(Base):
    __tablename__ = "strategy_versions"
    __table_args__ = (UniqueConstraint("strategy_definition_id", "version"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    strategy_definition_id: Mapped[str] = mapped_column(
        ForeignKey("strategy_definitions.id", ondelete="RESTRICT"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    strategy_spec_json: Mapped[str] = mapped_column(Text, nullable=False)
    strategy_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    change_note: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class StrategyLibrary:
    allowed_types: ClassVar[frozenset[str]] = frozenset(
        {"BUY_AND_HOLD", "TOP_N_MOMENTUM_ROTATION"}
    )

    def __init__(self, engine) -> None:
        self.engine = engine

    def _validate(self, strategy_type: str, spec: dict[str, object]) -> None:
        if strategy_type not in self.allowed_types:
            raise DatasetError("STRATEGY_UNSUPPORTED", "策略类型不受支持")
        if any(key.lower() in {"python", "code", "expression", "sql", "script"} for key in spec):
            raise DatasetError("STRATEGY_SPEC_INVALID", "策略配置不允许执行代码")
        if len(json.dumps(spec, ensure_ascii=False, default=str)) > 10000:
            raise DatasetError("STRATEGY_SPEC_INVALID", "策略配置过大")

    def create_definition(self, name: str, description: str, strategy_type: str):
        self._validate(strategy_type, {})
        now = datetime.now(UTC)
        model = StrategyDefinitionModel(
            id=str(uuid4()),
            name=name,
            description=description,
            strategy_type=strategy_type,
            status="ACTIVE",
            created_at=now,
            updated_at=now,
        )
        with Session(self.engine) as session:
            session.add(model)
            session.commit()
            session.refresh(model)
            session.expunge(model)
        return model

    def get(self, definition_id: str):
        with Session(self.engine) as session:
            model = session.get(StrategyDefinitionModel, definition_id)
            if model is None:
                raise DatasetError("STRATEGY_NOT_FOUND", "策略不存在")
            session.expunge(model)
            return model

    def list(self):
        with Session(self.engine) as session:
            values = tuple(
                session.scalars(
                    select(StrategyDefinitionModel).order_by(StrategyDefinitionModel.created_at)
                )
            )
            for value in values:
                session.expunge(value)
            return values

    def create_version(self, definition_id: str, spec: dict[str, object], change_note: str):
        definition = self.get(definition_id)
        if definition.status != "ACTIVE":
            raise DatasetError("STRATEGY_ARCHIVED", "归档策略不能创建新版本")
        self._validate(definition.strategy_type, spec)
        payload = canonical_json(spec)
        now = datetime.now(UTC)
        with Session(self.engine) as session:
            session.connection().exec_driver_sql("BEGIN IMMEDIATE")
            version = (
                session.scalar(
                    select(func.max(StrategyVersionModel.version)).where(
                        StrategyVersionModel.strategy_definition_id == definition_id
                    )
                )
                or 0
            )
            model = StrategyVersionModel(
                id=str(uuid4()),
                strategy_definition_id=definition_id,
                version=int(version) + 1,
                strategy_spec_json=payload,
                strategy_fingerprint=sha256_text(definition.strategy_type + ":" + payload),
                change_note=change_note,
                created_at=now,
            )
            session.add(model)
            session.commit()
            session.expunge(model)
            return model

    def versions(self, definition_id: str):
        self.get(definition_id)
        with Session(self.engine) as session:
            values = tuple(
                session.scalars(
                    select(StrategyVersionModel)
                    .where(StrategyVersionModel.strategy_definition_id == definition_id)
                    .order_by(StrategyVersionModel.version)
                )
            )
            for value in values:
                session.expunge(value)
            return values

    def archive(self, definition_id: str):
        with Session(self.engine) as session:
            model = session.get(StrategyDefinitionModel, definition_id)
            if model is None:
                raise DatasetError("STRATEGY_NOT_FOUND", "策略不存在")
            model.status = "ARCHIVED"
            model.updated_at = datetime.now(UTC)
            session.commit()
            session.expunge(model)
            return model
