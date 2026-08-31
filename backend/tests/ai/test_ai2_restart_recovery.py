from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import text

from alembic import command
from quant_lab.ai.cases import ResearchCaseInput, ResearchCaseService
from quant_lab.ai.repository import AIRepository
from quant_lab.ai.retrieval import ResearchCaseDocumentService
from quant_lab.core.config import Settings
from quant_lab.db.sqlite import create_sqlite_engine
from quant_lab.main import create_app


@pytest.mark.anyio
async def test_restart_rebuilds_fts_from_canonical_documents_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = Settings(project_root=tmp_path, runtime_root=tmp_path / "runtime")
    monkeypatch.setenv("QUANT_LAB_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("QUANT_LAB_RUNTIME_ROOT", str(settings.runtime_root))
    command.upgrade(Config("backend/alembic.ini"), "head")
    engine = create_sqlite_engine(settings)
    repository = AIRepository(engine)
    case = ResearchCaseService(repository).freeze(
        ResearchCaseInput(
            purpose="TEST",
            market="CN_A_SHARE",
            exchange="SSE",
            symbol="600000",
            instrument_id="SSE:600000",
            asset_type="EQUITY",
            currency="CNY",
            timeframe="1D",
            as_of_utc=datetime(2026, 8, 30, tzinfo=UTC),
            market_local_trade_date=date(2026, 8, 30),
            bindings={
                "market_data_fingerprint": "a" * 64,
                "calendar_fingerprint": "b" * 64,
                "market_rules_fingerprint": "c" * 64,
            },
        ),
        actor="USER",
    )
    document = ResearchCaseDocumentService(repository).create(
        case_id=case.id,
        title="Canonical",
        summary="Stable result",
        diagnosis="None",
        success_factors=(),
        failure_factors=(),
        regime_labels=(),
        safe_tags=(),
        universe=("SSE:600000",),
        strategy_family=None,
        market_rules_version=None,
    )
    with engine.begin() as connection:
        connection.execute(text("DELETE FROM ai_research_case_fts"))
        connection.execute(
            text(
                "INSERT INTO ai_research_case_fts "
                "(document_id,case_id,title,summary,diagnosis,factors,labels_tags) "
                "VALUES ('fake','fake','Injected','','','','')"
            )
        )
    engine.dispose()

    app = create_app(settings)
    async with app.router.lifespan_context(app):
        with app.state.ai_repository.engine.connect() as connection:
            ids = connection.execute(
                text("SELECT document_id FROM ai_research_case_fts")
            ).scalars().all()
        assert ids == [document.id]
        assert app.state.ai_fts_document_count == 1
