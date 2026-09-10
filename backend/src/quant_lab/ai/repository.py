from __future__ import annotations

import json
from datetime import datetime
from uuid import uuid4

from sqlalchemy import func, select, text, true
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from quant_lab.ai.persistence import (
    AIAnalysisAttemptModel,
    AIAnalysisRunModel,
    AIAnalysisTraceEventModel,
    AIEvidencePackModel,
    AIEvidenceRefModel,
    AIModelConfigVersionModel,
    AIPromptTemplateVersionModel,
    AIProviderCallBindingModel,
    AIResearchCaseDocumentModel,
    AIResearchCaseModel,
    AIRetrievalSnapshotModel,
    AIUsageLedgerModel,
    AIValidationResultModel,
)


class AIRepository:
    """SQLite persistence boundary for AI provenance records."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def abandon_provider_attempt(self, attempt_id: str, now_utc: datetime) -> None:
        """Atomically retain unknown usage on restart; never release the binding reservation."""
        with Session(self.engine) as session:
            session.execute(text("BEGIN IMMEDIATE"))
            attempt = session.get(AIAnalysisAttemptModel, attempt_id)
            if attempt is None or attempt.status != "STARTED":
                return
            binding = session.get(AIProviderCallBindingModel, attempt_id)
            if (
                binding is not None
                and session.scalar(
                    select(AIUsageLedgerModel).where(AIUsageLedgerModel.attempt_id == attempt_id)
                )
                is None
            ):
                session.add(
                    AIUsageLedgerModel(
                        id=str(uuid4()),
                        run_id=attempt.run_id,
                        attempt_id=attempt_id,
                        prompt_tokens=None,
                        cached_prompt_tokens=None,
                        completion_tokens=None,
                        total_tokens=None,
                        reported_cost=None,
                        estimated_cost=None,
                        currency=binding.currency,
                        is_estimate=True,
                        occurred_at=now_utc,
                    )
                )
            attempt.status = "ABANDONED"
            attempt.failure_code = "PROVIDER_RESULT_UNKNOWN"
            attempt.completed_at = now_utc
            session.commit()

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

    def find_research_case_by_fingerprint(self, fingerprint: str) -> AIResearchCaseModel | None:
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

    def list_started_attempts(
        self, run_id: str | None = None
    ) -> tuple[AIAnalysisAttemptModel, ...]:
        with Session(self.engine) as session:
            models = tuple(
                session.scalars(
                    select(AIAnalysisAttemptModel)
                    .where(
                        (AIAnalysisAttemptModel.run_id == run_id) if run_id is not None else true(),
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

    def find_evidence_pack_by_fingerprint(self, fingerprint: str) -> AIEvidencePackModel | None:
        with Session(self.engine) as session:
            model = session.scalar(
                select(AIEvidencePackModel).where(AIEvidencePackModel.fingerprint == fingerprint)
            )
            if model is not None:
                session.expunge(model)
            return model

    def add_evidence_pack(self, model: AIEvidencePackModel) -> AIEvidencePackModel:
        with Session(self.engine) as session:
            session.add(model)
            session.commit()
            session.refresh(model)
            session.expunge(model)
            return model

    def get_evidence_pack(self, model_id: str) -> AIEvidencePackModel | None:
        with Session(self.engine) as session:
            model = session.get(AIEvidencePackModel, model_id)
            if model is not None:
                session.expunge(model)
            return model

    def add_validation_result(self, model: AIValidationResultModel) -> AIValidationResultModel:
        with Session(self.engine) as session:
            session.add(model)
            session.commit()
            session.refresh(model)
            session.expunge(model)
            return model

    def find_validation_result_by_fingerprint(
        self, fingerprint: str
    ) -> AIValidationResultModel | None:
        with Session(self.engine) as session:
            model = session.scalar(
                select(AIValidationResultModel).where(
                    AIValidationResultModel.fingerprint == fingerprint
                )
            )
            if model is not None:
                session.expunge(model)
            return model

    def get_validation_result(self, model_id: str) -> AIValidationResultModel | None:
        with Session(self.engine) as session:
            model = session.get(AIValidationResultModel, model_id)
            if model is not None:
                session.expunge(model)
            return model

    def list_validation_results(self, run_id: str) -> tuple[AIValidationResultModel, ...]:
        with Session(self.engine) as session:
            models = tuple(
                session.scalars(
                    select(AIValidationResultModel)
                    .where(AIValidationResultModel.run_id == run_id)
                    .order_by(AIValidationResultModel.created_at, AIValidationResultModel.id)
                )
            )
            for model in models:
                session.expunge(model)
            return models

    @staticmethod
    def _fts_values(model: AIResearchCaseDocumentModel) -> dict[str, str]:
        success = json.loads(model.success_factors_json)
        failure = json.loads(model.failure_factors_json)
        regimes = json.loads(model.regime_labels_json)
        tags = json.loads(model.safe_tags_json)
        return {
            "document_id": model.id,
            "case_id": model.case_id,
            "title": model.title,
            "summary": model.summary,
            "diagnosis": model.diagnosis,
            "factors": " ".join(str(value) for value in [*success, *failure]),
            "labels_tags": " ".join(str(value) for value in [*regimes, *tags]),
        }

    def add_research_case_document(
        self, model: AIResearchCaseDocumentModel
    ) -> AIResearchCaseDocumentModel:
        with Session(self.engine) as session:
            session.add(model)
            session.flush()
            session.execute(
                text(
                    "INSERT INTO ai_research_case_fts "
                    "(document_id,case_id,title,summary,diagnosis,factors,labels_tags) "
                    "VALUES (:document_id,:case_id,:title,:summary,:diagnosis,"
                    ":factors,:labels_tags)"
                ),
                self._fts_values(model),
            )
            session.commit()
            session.refresh(model)
            session.expunge(model)
            return model

    def get_research_case_document(self, model_id: str) -> AIResearchCaseDocumentModel | None:
        with Session(self.engine) as session:
            model = session.get(AIResearchCaseDocumentModel, model_id)
            if model is not None:
                session.expunge(model)
            return model

    def get_research_case_document_by_case_id(
        self, case_id: str
    ) -> AIResearchCaseDocumentModel | None:
        with Session(self.engine) as session:
            model = session.scalar(
                select(AIResearchCaseDocumentModel).where(
                    AIResearchCaseDocumentModel.case_id == case_id
                )
            )
            if model is not None:
                session.expunge(model)
            return model

    def list_research_case_documents(self) -> tuple[AIResearchCaseDocumentModel, ...]:
        with Session(self.engine) as session:
            models = tuple(
                session.scalars(
                    select(AIResearchCaseDocumentModel).order_by(
                        AIResearchCaseDocumentModel.created_at,
                        AIResearchCaseDocumentModel.id,
                    )
                )
            )
            for model in models:
                session.expunge(model)
            return models

    def list_research_case_documents_with_cases(
        self,
    ) -> tuple[tuple[AIResearchCaseDocumentModel, AIResearchCaseModel], ...]:
        with Session(self.engine) as session:
            rows = tuple(
                session.execute(
                    select(AIResearchCaseDocumentModel, AIResearchCaseModel)
                    .join(
                        AIResearchCaseModel,
                        AIResearchCaseModel.id == AIResearchCaseDocumentModel.case_id,
                    )
                    .order_by(AIResearchCaseDocumentModel.id)
                ).all()
            )
            for document, case in rows:
                session.expunge(document)
                session.expunge(case)
            return tuple((row[0], row[1]) for row in rows)

    def search_research_case_fts(self, match_query: str) -> tuple[str, ...]:
        with self.engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT document_id FROM ai_research_case_fts "
                    "WHERE ai_research_case_fts MATCH :query"
                ),
                {"query": match_query},
            )
            return tuple(str(row[0]) for row in rows)

    def rebuild_research_case_fts(self) -> int:
        documents = self.list_research_case_documents()
        with self.engine.begin() as connection:
            connection.execute(text("DELETE FROM ai_research_case_fts"))
            for model in documents:
                connection.execute(
                    text(
                        "INSERT INTO ai_research_case_fts "
                        "(document_id,case_id,title,summary,diagnosis,factors,labels_tags) "
                        "VALUES (:document_id,:case_id,:title,:summary,:diagnosis,"
                        ":factors,:labels_tags)"
                    ),
                    self._fts_values(model),
                )
        return len(documents)

    def find_retrieval_snapshot_by_fingerprint(
        self, fingerprint: str
    ) -> AIRetrievalSnapshotModel | None:
        with Session(self.engine) as session:
            model = session.scalar(
                select(AIRetrievalSnapshotModel).where(
                    AIRetrievalSnapshotModel.fingerprint == fingerprint
                )
            )
            if model is not None:
                session.expunge(model)
            return model

    def add_retrieval_snapshot(self, model: AIRetrievalSnapshotModel) -> AIRetrievalSnapshotModel:
        with Session(self.engine) as session:
            session.add(model)
            session.commit()
            session.refresh(model)
            session.expunge(model)
            return model

    def get_retrieval_snapshot(self, model_id: str) -> AIRetrievalSnapshotModel | None:
        with Session(self.engine) as session:
            model = session.get(AIRetrievalSnapshotModel, model_id)
            if model is not None:
                session.expunge(model)
            return model
