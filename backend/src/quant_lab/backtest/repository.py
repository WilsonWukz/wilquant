from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from quant_lab.backtest.domain import BacktestRunStatus
from quant_lab.backtest.persistence import BacktestArtifactModel, BacktestRunModel
from quant_lab.datasets.errors import DatasetError


class BacktestRepository:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def claim(
        self,
        *,
        name: str,
        market_data_profile_id: str,
        market_data_snapshot_json: str,
        market_data_snapshot_fingerprint: str,
        strategy_type: str,
        strategy_spec_json: str,
        strategy_fingerprint: str,
        engine_version: str,
        config_json: str,
        config_fingerprint: str,
        run_input_fingerprint: str,
        initial_cash: Decimal,
        start_date: date,
        end_date: date,
    ) -> BacktestRunModel:
        now = datetime.now(UTC)
        with Session(self.engine) as session:
            existing = session.scalar(
                select(BacktestRunModel).where(
                    BacktestRunModel.run_input_fingerprint == run_input_fingerprint
                )
            )
            if existing is not None:
                session.expunge(existing)
                return existing
            model = BacktestRunModel(
                backtest_run_id=str(uuid4()),
                name=name,
                status=BacktestRunStatus.PENDING.value,
                market_data_profile_id=market_data_profile_id,
                market_data_snapshot_json=market_data_snapshot_json,
                market_data_snapshot_fingerprint=market_data_snapshot_fingerprint,
                strategy_type=strategy_type,
                strategy_spec_json=strategy_spec_json,
                strategy_fingerprint=strategy_fingerprint,
                engine_version=engine_version,
                config_json=config_json,
                config_fingerprint=config_fingerprint,
                run_input_fingerprint=run_input_fingerprint,
                initial_cash=initial_cash,
                start_date=start_date,
                end_date=end_date,
                created_at=now,
            )
            session.add(model)
            session.commit()
            session.refresh(model)
            session.expunge(model)
            return model

    def get(self, run_id: str) -> BacktestRunModel:
        with Session(self.engine) as session:
            model = session.get(BacktestRunModel, run_id)
            if model is None:
                raise DatasetError("BACKTEST_NOT_FOUND", "回测不存在")
            session.expunge(model)
            return model

    def list(self) -> tuple[BacktestRunModel, ...]:
        with Session(self.engine) as session:
            values = tuple(
                session.scalars(
                    select(BacktestRunModel).order_by(BacktestRunModel.created_at.desc())
                )
            )
            for value in values:
                session.expunge(value)
            return values

    def mark_running(self, run_id: str) -> BacktestRunModel:
        return self._transition(
            run_id, BacktestRunStatus.RUNNING.value, started_at=datetime.now(UTC)
        )

    def mark_succeeded(self, run_id: str, manifest_path: str) -> BacktestRunModel:
        return self._transition(
            run_id,
            BacktestRunStatus.SUCCEEDED.value,
            completed_at=datetime.now(UTC),
            artifact_manifest_path=manifest_path,
        )

    def mark_failed(self, run_id: str, code: str, message: str) -> BacktestRunModel:
        return self._transition(
            run_id,
            BacktestRunStatus.FAILED.value,
            completed_at=datetime.now(UTC),
            failure_code=code,
            failure_message=message,
        )

    def _transition(self, run_id: str, status: str, **values: object) -> BacktestRunModel:
        with Session(self.engine) as session:
            model = session.get(BacktestRunModel, run_id)
            if model is None:
                raise DatasetError("BACKTEST_NOT_FOUND", "回测不存在")
            if model.status == BacktestRunStatus.SUCCEEDED.value:
                session.expunge(model)
                return model
            model.status = status
            for key, value in values.items():
                setattr(model, key, value)
            session.commit()
            session.refresh(model)
            session.expunge(model)
            return model

    def add_artifacts(self, run_id: str, artifacts: list[dict[str, object]]) -> None:
        now = datetime.now(UTC)
        with Session(self.engine) as session:
            model = session.get(BacktestRunModel, run_id)
            if model is None:
                raise DatasetError("BACKTEST_NOT_FOUND", "回测不存在")
            session.add_all(
                BacktestArtifactModel(
                    backtest_artifact_id=str(uuid4()),
                    backtest_run_id=run_id,
                    created_at=now,
                    **artifact,
                )
                for artifact in artifacts
            )
            session.commit()

    def artifacts(self, run_id: str) -> tuple[BacktestArtifactModel, ...]:
        with Session(self.engine) as session:
            values = tuple(
                session.scalars(
                    select(BacktestArtifactModel)
                    .where(BacktestArtifactModel.backtest_run_id == run_id)
                    .order_by(BacktestArtifactModel.artifact_type)
                )
            )
            for value in values:
                session.expunge(value)
            return values
