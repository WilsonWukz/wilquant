from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from quant_lab.ai.persistence import (
    AIAnalysisAttemptModel,
    AIAnalysisRunModel,
    AIAnalysisTraceEventModel,
    AIEvidenceRefModel,
    AIModelConfigVersionModel,
    AIPromptTemplateVersionModel,
    AIResearchCaseModel,
    AIUsageLedgerModel,
)


class AIRepository:
    """SQLite persistence boundary for AI provenance records."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def find_prompt_template_by_fingerprint(
        self, fingerprint: str
    ) -> AIPromptTemplateVersionModel | None:
        with Session(self.engine) as session:
            model = session.scalar(
                select(AIPromptTemplateVersionModel).where(
                    AIPromptTemplateVersionModel.fingerprint == fingerprint
                )
            )
            if model is not None:
                session.expunge(model)
            return model

    def add_prompt_template(
        self, model: AIPromptTemplateVersionModel
    ) -> AIPromptTemplateVersionModel:
        with Session(self.engine) as session:
            session.add(model)
            session.commit()
            session.refresh(model)
            session.expunge(model)
            return model

    def get_prompt_template(self, model_id: str) -> AIPromptTemplateVersionModel | None:
        with Session(self.engine) as session:
            model = session.get(AIPromptTemplateVersionModel, model_id)
            if model is not None:
                session.expunge(model)
            return model

    def find_model_config_by_fingerprint(
        self, fingerprint: str
    ) -> AIModelConfigVersionModel | None:
        with Session(self.engine) as session:
            model = session.scalar(
                select(AIModelConfigVersionModel).where(
                    AIModelConfigVersionModel.fingerprint == fingerprint
                )
            )
            if model is not None:
                session.expunge(model)
            return model

    def add_model_config(self, model: AIModelConfigVersionModel) -> AIModelConfigVersionModel:
        with Session(self.engine) as session:
            session.add(model)
            session.commit()
            session.refresh(model)
            session.expunge(model)
            return model

    def get_model_config(self, model_id: str) -> AIModelConfigVersionModel | None:
        with Session(self.engine) as session:
            model = session.get(AIModelConfigVersionModel, model_id)
            if model is not None:
                session.expunge(model)
            return model

    def find_research_case_by_fingerprint(
        self, fingerprint: str
    ) -> AIResearchCaseModel | None:
        with Session(self.engine) as session:
            model = session.scalar(
                select(AIResearchCaseModel).where(AIResearchCaseModel.fingerprint == fingerprint)
            )
            if model is not None:
                session.expunge(model)
            return model

    def add_research_case(self, model: AIResearchCaseModel) -> AIResearchCaseModel:
        with Session(self.engine) as session:
            session.add(model)
            session.commit()
            session.refresh(model)
            session.expunge(model)
            return model

    def get_research_case(self, model_id: str) -> AIResearchCaseModel | None:
        with Session(self.engine) as session:
            model = session.get(AIResearchCaseModel, model_id)
            if model is not None:
                session.expunge(model)
            return model

    def find_evidence_ref_by_fingerprint(self, fingerprint: str) -> AIEvidenceRefModel | None:
        with Session(self.engine) as session:
            model = session.scalar(
                select(AIEvidenceRefModel).where(AIEvidenceRefModel.fingerprint == fingerprint)
            )
            if model is not None:
                session.expunge(model)
            return model

    def add_evidence_ref(self, model: AIEvidenceRefModel) -> AIEvidenceRefModel:
        with Session(self.engine) as session:
            session.add(model)
            session.commit()
            session.refresh(model)
            session.expunge(model)
            return model

    def add_run(self, model: AIAnalysisRunModel) -> AIAnalysisRunModel:
        with Session(self.engine) as session:
            session.add(model)
            session.commit()
            session.refresh(model)
            session.expunge(model)
            return model

    def get_run(self, model_id: str) -> AIAnalysisRunModel | None:
        with Session(self.engine) as session:
            model = session.get(AIAnalysisRunModel, model_id)
            if model is not None:
                session.expunge(model)
            return model

    def update_run(self, model_id: str, values: dict[str, object]) -> AIAnalysisRunModel | None:
        with Session(self.engine) as session:
            model = session.get(AIAnalysisRunModel, model_id)
            if model is None:
                return None
            for key, value in values.items():
                setattr(model, key, value)
            session.commit()
            session.refresh(model)
            session.expunge(model)
            return model

    def list_incomplete_runs(self) -> tuple[AIAnalysisRunModel, ...]:
        with Session(self.engine) as session:
            models = tuple(
                session.scalars(
                    select(AIAnalysisRunModel)
                    .where(AIAnalysisRunModel.status.in_(("RUNNING", "VALIDATING")))
                    .order_by(AIAnalysisRunModel.created_at, AIAnalysisRunModel.id)
                )
            )
            for model in models:
                session.expunge(model)
            return models

    def next_attempt_number(self, run_id: str) -> int:
        with Session(self.engine) as session:
            maximum = session.scalar(
                select(func.max(AIAnalysisAttemptModel.attempt_number)).where(
                    AIAnalysisAttemptModel.run_id == run_id
                )
            )
            return int(maximum or 0) + 1

    def add_attempt(self, model: AIAnalysisAttemptModel) -> AIAnalysisAttemptModel:
        with Session(self.engine) as session:
            session.add(model)
            session.commit()
            session.refresh(model)
            session.expunge(model)
            return model

    def get_attempt(self, model_id: str) -> AIAnalysisAttemptModel | None:
        with Session(self.engine) as session:
            model = session.get(AIAnalysisAttemptModel, model_id)
            if model is not None:
                session.expunge(model)
            return model

    def update_attempt(
        self, model_id: str, values: dict[str, object]
    ) -> AIAnalysisAttemptModel | None:
        with Session(self.engine) as session:
            model = session.get(AIAnalysisAttemptModel, model_id)
            if model is None:
                return None
            for key, value in values.items():
                setattr(model, key, value)
            session.commit()
            session.refresh(model)
            session.expunge(model)
            return model

    def list_started_attempts(self, run_id: str) -> tuple[AIAnalysisAttemptModel, ...]:
        with Session(self.engine) as session:
            models = tuple(
                session.scalars(
                    select(AIAnalysisAttemptModel)
                    .where(
                        AIAnalysisAttemptModel.run_id == run_id,
                        AIAnalysisAttemptModel.status == "STARTED",
                    )
                    .order_by(AIAnalysisAttemptModel.attempt_number)
                )
            )
            for model in models:
                session.expunge(model)
            return models

    def next_trace_sequence(self, run_id: str) -> int:
        with Session(self.engine) as session:
            maximum = session.scalar(
                select(func.max(AIAnalysisTraceEventModel.sequence)).where(
                    AIAnalysisTraceEventModel.run_id == run_id
                )
            )
            return int(maximum or 0) + 1

    def add_trace(self, model: AIAnalysisTraceEventModel) -> AIAnalysisTraceEventModel:
        with Session(self.engine) as session:
            session.add(model)
            session.commit()
            session.refresh(model)
            session.expunge(model)
            return model

    def list_trace(self, run_id: str) -> tuple[AIAnalysisTraceEventModel, ...]:
        with Session(self.engine) as session:
            models = tuple(
                session.scalars(
                    select(AIAnalysisTraceEventModel)
                    .where(AIAnalysisTraceEventModel.run_id == run_id)
                    .order_by(AIAnalysisTraceEventModel.sequence)
                )
            )
            for model in models:
                session.expunge(model)
            return models

    def add_usage(self, model: AIUsageLedgerModel) -> AIUsageLedgerModel:
        with Session(self.engine) as session:
            session.add(model)
            session.commit()
            session.refresh(model)
            session.expunge(model)
            return model

    def list_usage(self, run_id: str) -> tuple[AIUsageLedgerModel, ...]:
        with Session(self.engine) as session:
            models = tuple(
                session.scalars(
                    select(AIUsageLedgerModel)
                    .where(AIUsageLedgerModel.run_id == run_id)
                    .order_by(AIUsageLedgerModel.occurred_at, AIUsageLedgerModel.id)
                )
            )
            for model in models:
                session.expunge(model)
            return models
