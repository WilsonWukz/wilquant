from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text

from quant_lab.ai.repository import AIRepository
from quant_lab.ai.retrieval import ResearchCaseRetrievalService
from quant_lab.db.sqlite import Base

from .test_ai2_retrieval import _add_document, _case, _query


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


def test_fts_rebuild_preserves_business_ranking_and_old_snapshot(repository) -> None:
    repository.add_research_case(_case("case-a"))
    repository.add_research_case(_case("case-b"))
    _add_document(
        repository, case_id="case-a", title="Mean reversion alpha", strategy_family="mean_reversion"
    )
    _add_document(
        repository, case_id="case-b", title="Mean alpha", strategy_family="momentum"
    )
    service = ResearchCaseRetrievalService(repository)

    before = service.retrieve(_query())
    frozen = repository.get_retrieval_snapshot(before.id)
    with repository.engine.begin() as connection:
        connection.execute(text("DELETE FROM ai_research_case_fts"))
    repository.rebuild_research_case_fts()
    after = service.retrieve(_query())

    before_rows = [
        (row.case_id, row.document_fingerprint, row.final_score, row.rank)
        for row in before.candidates
    ]
    after_rows = [
        (row.case_id, row.document_fingerprint, row.final_score, row.rank)
        for row in after.candidates
    ]
    assert before_rows == after_rows
    assert before.fingerprint == after.fingerprint
    restored = repository.get_retrieval_snapshot(before.id)
    assert restored is not None and frozen is not None
    assert restored.fingerprint == frozen.fingerprint


def test_rebuild_removes_noncanonical_fts_rows(repository) -> None:
    repository.add_research_case(_case("case-a"))
    _add_document(
        repository, case_id="case-a", title="Canonical", strategy_family="mean_reversion"
    )
    canonical = repository.get_research_case_document_by_case_id("case-a")
    assert canonical is not None
    with repository.engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO ai_research_case_fts "
                "(document_id,case_id,title,summary,diagnosis,factors,labels_tags) "
                "VALUES ('fake','fake','Injected','','','','')"
            )
        )

    assert repository.rebuild_research_case_fts() == 1
    with repository.engine.connect() as connection:
        ids = (
            connection.execute(text("SELECT document_id FROM ai_research_case_fts"))
            .scalars()
            .all()
        )
    assert ids == [canonical.id]
