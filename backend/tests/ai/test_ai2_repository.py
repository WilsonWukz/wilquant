from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

from quant_lab.ai.persistence import (
    AIEvidencePackModel,
    AIResearchCaseDocumentModel,
    AIResearchCaseModel,
)
from quant_lab.ai.repository import AIRepository
from quant_lab.db.sqlite import Base


@pytest.fixture
def repository() -> AIRepository:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE VIRTUAL TABLE ai_research_case_fts USING fts5("
                "document_id UNINDEXED, case_id UNINDEXED, title, summary, diagnosis, "
                "factors, labels_tags)"
            )
        )
    return AIRepository(engine)


def _case() -> AIResearchCaseModel:
    return AIResearchCaseModel(
        id="case-1",
        purpose="TEST",
        market="CN_A_SHARE",
        exchange="SSE",
        symbol="600000",
        instrument_id="SSE:600000",
        asset_type="EQUITY",
        currency="CNY",
        timeframe="1D",
        as_of_utc=datetime(2024, 1, 31, tzinfo=UTC),
        market_local_trade_date=date(2024, 1, 31),
        bindings_json="{}",
        previous_case_id=None,
        previous_analysis_run_id=None,
        thesis_revision_id=None,
        fingerprint="1" * 64,
        created_by="USER",
        created_at=datetime(2024, 2, 1, tzinfo=UTC),
    )


def _document() -> AIResearchCaseDocumentModel:
    return AIResearchCaseDocumentModel(
        id="doc-1",
        case_id="case-1",
        title="Mean reversion",
        summary="Stable result",
        diagnosis="Low turnover",
        success_factors_json='["stable"]',
        failure_factors_json='["trend"]',
        regime_labels_json='["sideways"]',
        safe_tags_json='["daily"]',
        universe_json='["SSE:600000"]',
        strategy_family="mean_reversion",
        market_rules_version=None,
        document_fingerprint="3" * 64,
        created_at=datetime(2024, 2, 1, tzinfo=UTC),
    )


def test_add_and_get_evidence_pack(repository: AIRepository) -> None:
    repository.add_research_case(_case())
    model = AIEvidencePackModel(
        id="pack-1",
        case_id="case-1",
        temporal_context_json="{}",
        evidence_context_json="{}",
        requirements_json="{}",
        items_json="[]",
        policy_version="v1",
        fingerprint="2" * 64,
        created_at=datetime(2024, 2, 1, tzinfo=UTC),
    )

    repository.add_evidence_pack(model)

    restored = repository.get_evidence_pack("pack-1")
    assert restored is not None
    assert restored.fingerprint == "2" * 64


def test_document_and_fts_are_inserted_atomically(repository: AIRepository) -> None:
    repository.add_research_case(_case())
    repository.add_research_case_document(_document())

    with repository.engine.connect() as connection:
        row = connection.execute(
            text(
                "SELECT document_id, title FROM ai_research_case_fts "
                "WHERE ai_research_case_fts MATCH 'reversion'"
            )
        ).one()
    assert row == ("doc-1", "Mean reversion")

    conflicting = _document()
    conflicting.id = "doc-2"
    conflicting.document_fingerprint = "4" * 64
    with pytest.raises(IntegrityError):
        repository.add_research_case_document(conflicting)
    with repository.engine.connect() as connection:
        assert connection.scalar(text("SELECT COUNT(*) FROM ai_research_case_fts")) == 1


def test_fts_rebuild_uses_only_canonical_documents(repository: AIRepository) -> None:
    repository.add_research_case(_case())
    repository.add_research_case_document(_document())
    with repository.engine.begin() as connection:
        connection.execute(text("DELETE FROM ai_research_case_fts"))
        connection.execute(
            text(
                "INSERT INTO ai_research_case_fts "
                "(document_id,case_id,title,summary,diagnosis,factors,labels_tags) "
                "VALUES ('fake','fake','Injected','Injected','Injected','','')"
            )
        )

    assert repository.rebuild_research_case_fts() == 1

    with repository.engine.connect() as connection:
        rows = connection.execute(
            text("SELECT document_id,case_id FROM ai_research_case_fts")
        ).all()
    assert rows == [("doc-1", "case-1")]
