from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from quant_lab.datasets.errors import DatasetError
from quant_lab.research.domain import (
    ResearchExperimentStatus,
    RunRole,
)
from quant_lab.research.persistence import (
    ExperimentRunLinkModel,
    ResearchExperimentModel,
    ResearchJournalEntryModel,
)


class ResearchRepository:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    # --- experiments ---
    def create_experiment(
        self,
        *,
        name: str,
        hypothesis: str,
        tags: list[str],
        market_data_profile_id: str | None,
    ) -> ResearchExperimentModel:
        now = datetime.now(UTC)
        with Session(self.engine) as session:
            model = ResearchExperimentModel(
                id=str(uuid4()),
                name=name,
                hypothesis=hypothesis,
                market_data_profile_id=market_data_profile_id,
                status=ResearchExperimentStatus.DRAFT.value,
                tags_json=json.dumps(tags, ensure_ascii=False, sort_keys=True),
                created_at=now,
                updated_at=now,
            )
            session.add(model)
            session.commit()
            session.refresh(model)
            session.expunge(model)
            return model

    def get_experiment(self, experiment_id: str) -> ResearchExperimentModel:
        with Session(self.engine) as session:
            model = session.get(ResearchExperimentModel, experiment_id)
            if model is None:
                raise DatasetError("EXPERIMENT_NOT_FOUND", "研究实验不存在")
            session.expunge(model)
            return model

    def list_experiments(self, status: str | None = None) -> tuple[ResearchExperimentModel, ...]:
        with Session(self.engine) as session:
            statement = select(ResearchExperimentModel).order_by(
                ResearchExperimentModel.created_at.desc()
            )
            if status is not None:
                statement = statement.where(ResearchExperimentModel.status == status)
            values = tuple(session.scalars(statement))
            for value in values:
                session.expunge(value)
            return values

    def update_experiment(
        self, experiment_id: str, values: dict[str, object]
    ) -> ResearchExperimentModel:
        now = datetime.now(UTC)
        with Session(self.engine) as session:
            model = session.get(ResearchExperimentModel, experiment_id)
            if model is None:
                raise DatasetError("EXPERIMENT_NOT_FOUND", "研究实验不存在")
            for key, value in values.items():
                setattr(model, key, value)
            model.updated_at = now
            session.commit()
            session.refresh(model)
            session.expunge(model)
            return model

    # --- run links ---
    def add_run(
        self, experiment_id: str, backtest_run_id: str, role: str, label: str | None
    ) -> ExperimentRunLinkModel:
        now = datetime.now(UTC)
        with Session(self.engine) as session:
            existing = session.scalar(
                select(ExperimentRunLinkModel).where(
                    ExperimentRunLinkModel.experiment_id == experiment_id,
                    ExperimentRunLinkModel.backtest_run_id == backtest_run_id,
                )
            )
            if existing is not None:
                raise DatasetError("EXPERIMENT_RUN_DUPLICATE", "该回测已加入实验")
            if role == RunRole.BASELINE.value:
                baseline = session.scalar(
                    select(ExperimentRunLinkModel).where(
                        ExperimentRunLinkModel.experiment_id == experiment_id,
                        ExperimentRunLinkModel.role == RunRole.BASELINE.value,
                    )
                )
                if baseline is not None:
                    baseline.role = RunRole.CANDIDATE.value
                    session.flush()
            model = ExperimentRunLinkModel(
                id=str(uuid4()),
                experiment_id=experiment_id,
                backtest_run_id=backtest_run_id,
                role=role,
                label=label,
                created_at=now,
            )
            session.add(model)
            session.commit()
            session.refresh(model)
            session.expunge(model)
            return model

    def update_run_link(
        self, experiment_id: str, backtest_run_id: str, role: str | None, label: str | None
    ) -> ExperimentRunLinkModel:
        with Session(self.engine) as session:
            model = session.scalar(
                select(ExperimentRunLinkModel).where(
                    ExperimentRunLinkModel.experiment_id == experiment_id,
                    ExperimentRunLinkModel.backtest_run_id == backtest_run_id,
                )
            )
            if model is None:
                raise DatasetError("EXPERIMENT_RUN_NOT_FOUND", "实验未关联该回测")
            if role is not None:
                if role == RunRole.BASELINE.value and model.role != RunRole.BASELINE.value:
                    baseline = session.scalar(
                        select(ExperimentRunLinkModel).where(
                            ExperimentRunLinkModel.experiment_id == experiment_id,
                            ExperimentRunLinkModel.role == RunRole.BASELINE.value,
                        )
                    )
                    if baseline is not None:
                        baseline.role = RunRole.CANDIDATE.value
                        session.flush()
                model.role = role
            if label is not None:
                model.label = label
            session.commit()
            session.refresh(model)
            session.expunge(model)
            return model

    def remove_run_link(self, experiment_id: str, backtest_run_id: str) -> None:
        with Session(self.engine) as session:
            model = session.scalar(
                select(ExperimentRunLinkModel).where(
                    ExperimentRunLinkModel.experiment_id == experiment_id,
                    ExperimentRunLinkModel.backtest_run_id == backtest_run_id,
                )
            )
            if model is None:
                raise DatasetError("EXPERIMENT_RUN_NOT_FOUND", "实验未关联该回测")
            session.delete(model)
            session.commit()

    def list_run_links(self, experiment_id: str) -> tuple[ExperimentRunLinkModel, ...]:
        with Session(self.engine) as session:
            values = tuple(
                session.scalars(
                    select(ExperimentRunLinkModel)
                    .where(ExperimentRunLinkModel.experiment_id == experiment_id)
                    .order_by(ExperimentRunLinkModel.created_at)
                )
            )
            for value in values:
                session.expunge(value)
            return values

    # --- journal ---
    def create_journal_entry(
        self,
        *,
        title: str,
        entry_type: str,
        content: str,
        tags: list[str],
        experiment_id: str | None,
        backtest_run_id: str | None,
        strategy_version_id: str | None,
    ) -> ResearchJournalEntryModel:
        now = datetime.now(UTC)
        with Session(self.engine) as session:
            model = ResearchJournalEntryModel(
                id=str(uuid4()),
                title=title,
                entry_type=entry_type,
                content=content,
                experiment_id=experiment_id,
                backtest_run_id=backtest_run_id,
                strategy_version_id=strategy_version_id,
                tags_json=json.dumps(tags, ensure_ascii=False, sort_keys=True),
                created_at=now,
                updated_at=now,
            )
            session.add(model)
            session.commit()
            session.refresh(model)
            session.expunge(model)
            return model

    def get_journal_entry(self, entry_id: str) -> ResearchJournalEntryModel:
        with Session(self.engine) as session:
            model = session.get(ResearchJournalEntryModel, entry_id)
            if model is None:
                raise DatasetError("JOURNAL_ENTRY_NOT_FOUND", "研究记录不存在")
            session.expunge(model)
            return model

    def list_journal_entries(
        self,
        *,
        entry_type: str | None = None,
        experiment_id: str | None = None,
        backtest_run_id: str | None = None,
        strategy_version_id: str | None = None,
        tag: str | None = None,
    ) -> tuple[ResearchJournalEntryModel, ...]:
        with Session(self.engine) as session:
            statement = select(ResearchJournalEntryModel).order_by(
                ResearchJournalEntryModel.created_at.desc()
            )
            if entry_type is not None:
                statement = statement.where(ResearchJournalEntryModel.entry_type == entry_type)
            if experiment_id is not None:
                statement = statement.where(
                    ResearchJournalEntryModel.experiment_id == experiment_id
                )
            if backtest_run_id is not None:
                statement = statement.where(
                    ResearchJournalEntryModel.backtest_run_id == backtest_run_id
                )
            if strategy_version_id is not None:
                statement = statement.where(
                    ResearchJournalEntryModel.strategy_version_id == strategy_version_id
                )
            if tag is not None:
                statement = statement.where(ResearchJournalEntryModel.tags_json.like(f'%"{tag}"%'))
            values = tuple(session.scalars(statement))
            for value in values:
                session.expunge(value)
            return values

    def update_journal_entry(
        self,
        entry_id: str,
        *,
        title: str | None,
        entry_type: str | None,
        content: str | None,
        tags: list[str] | None,
    ) -> ResearchJournalEntryModel:
        now = datetime.now(UTC)
        with Session(self.engine) as session:
            model = session.get(ResearchJournalEntryModel, entry_id)
            if model is None:
                raise DatasetError("JOURNAL_ENTRY_NOT_FOUND", "研究记录不存在")
            if title is not None:
                model.title = title
            if entry_type is not None:
                model.entry_type = entry_type
            if content is not None:
                model.content = content
            if tags is not None:
                model.tags_json = json.dumps(tags, ensure_ascii=False, sort_keys=True)
            model.updated_at = now
            session.commit()
            session.refresh(model)
            session.expunge(model)
            return model

    def delete_journal_entry(self, entry_id: str) -> None:
        with Session(self.engine) as session:
            model = session.get(ResearchJournalEntryModel, entry_id)
            if model is None:
                raise DatasetError("JOURNAL_ENTRY_NOT_FOUND", "研究记录不存在")
            session.delete(model)
            session.commit()
