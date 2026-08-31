from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from sqlalchemy import create_engine, text

from quant_lab.ai.contracts import RetrievalQuery
from quant_lab.ai.persistence import AIResearchCaseModel
from quant_lab.ai.repository import AIRepository
from quant_lab.ai.retrieval import (
    ResearchCaseDocumentError,
    ResearchCaseDocumentService,
    ResearchCaseRetrievalService,
)
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


def _case(
    case_id: str,
    *,
    market: str = "CN_A_SHARE",
    asset_type: str = "EQUITY",
    as_of: datetime = datetime(2023, 12, 29, tzinfo=UTC),
    known_at: datetime = datetime(2024, 1, 2, tzinfo=UTC),
) -> AIResearchCaseModel:
    us = market == "US_EQUITY"
    return AIResearchCaseModel(
        id=case_id,
        purpose="RESEARCH",
        market=market,
        exchange="NASDAQ" if us else "SSE",
        symbol="AAPL" if us else "600000",
        instrument_id="NASDAQ:AAPL" if us else "SSE:600000",
        asset_type=asset_type,
        currency="USD" if us else "CNY",
        timeframe="1D",
        as_of_utc=as_of,
        market_local_trade_date=date(2023, 12, 29),
        bindings_json="{}",
        previous_case_id=None,
        previous_analysis_run_id=None,
        thesis_revision_id=None,
        fingerprint=("a" if case_id == "case-a" else "b" if case_id == "case-b" else "c")
        * 64,
        created_by="USER",
        created_at=known_at,
    )


def _add_document(
    repository: AIRepository,
    case_id: str,
    *,
    title: str,
    strategy_family: str,
    market_rules_version: str | None = None,
    regime_labels: tuple[str, ...] = ("sideways",),
) -> None:
    ResearchCaseDocumentService(repository).create(
        case_id=case_id,
        title=title,
        summary=f"{title} produced stable alpha",
        diagnosis="Low turnover and controlled drawdown",
        success_factors=("mean reversion",),
        failure_factors=("strong trend",),
        regime_labels=regime_labels,
        safe_tags=("daily",),
        universe=("SSE:600000",),
        strategy_family=strategy_family,
        market_rules_version=market_rules_version,
    )


def _query(**updates) -> RetrievalQuery:
    values = {
        "market": "CN_A_SHARE",
        "asset_type": "EQUITY",
        "market_data_cutoff": "2024-12-31T23:59:59Z",
        "knowledge_cutoff": "2024-12-31T23:59:59Z",
        "query_text": "mean reversion",
        "universe": ("SSE:600000",),
        "strategy_family": "mean_reversion",
        "regime_labels": ("sideways",),
        "safe_tags": ("daily",),
    }
    values.update(updates)
    return RetrievalQuery(**values)


def test_case_describing_2023_but_created_2026_is_excluded_from_2024_knowledge(
    repository: AIRepository,
) -> None:
    repository.add_research_case(
        _case("case-a", known_at=datetime(2026, 8, 30, tzinfo=UTC))
    )
    _add_document(
        repository, case_id="case-a", title="Late imported case", strategy_family="mean_reversion"
    )

    snapshot = ResearchCaseRetrievalService(repository).retrieve(_query())

    assert snapshot.candidates == ()
    assert snapshot.exclusions == ({"case_id": "case-a", "reason": "KNOWLEDGE_CUTOFF"},)


def test_cn_and_us_are_strictly_isolated(repository: AIRepository) -> None:
    repository.add_research_case(_case("case-a"))
    repository.add_research_case(_case("case-b", market="US_EQUITY"))
    _add_document(
        repository, case_id="case-a", title="CN mean reversion", strategy_family="mean_reversion"
    )
    _add_document(
        repository, case_id="case-b", title="US mean reversion", strategy_family="mean_reversion"
    )

    snapshot = ResearchCaseRetrievalService(repository).retrieve(_query())

    assert [item.case_id for item in snapshot.candidates] == ["case-a"]
    assert {item["reason"] for item in snapshot.exclusions} == {"MARKET_MISMATCH"}


def test_strategy_family_is_high_weight_score_not_hard_filter(
    repository: AIRepository,
) -> None:
    repository.add_research_case(_case("case-a"))
    repository.add_research_case(_case("case-b"))
    _add_document(
        repository, case_id="case-a", title="Matching family", strategy_family="mean_reversion"
    )
    _add_document(
        repository, case_id="case-b", title="Other family", strategy_family="momentum"
    )

    snapshot = ResearchCaseRetrievalService(repository).retrieve(_query())

    assert [item.case_id for item in snapshot.candidates] == ["case-a", "case-b"]
    assert snapshot.candidates[0].structured_score > snapshot.candidates[1].structured_score


def test_market_rules_filter_is_conditional(repository: AIRepository) -> None:
    repository.add_research_case(_case("case-a"))
    _add_document(
        repository,
        case_id="case-a",
        title="No rules case",
        strategy_family="mean_reversion",
        market_rules_version=None,
    )
    service = ResearchCaseRetrievalService(repository)

    independent = service.retrieve(_query())
    dependent = service.retrieve(
        _query(requires_market_rules=True, market_rules_version="cn-a-v1")
    )

    assert [item.case_id for item in independent.candidates] == ["case-a"]
    assert dependent.candidates == ()
    assert dependent.exclusions == (
        {"case_id": "case-a", "reason": "MARKET_RULES_MISMATCH"},
    )


def test_fts_query_syntax_is_sanitized(repository: AIRepository) -> None:
    repository.add_research_case(_case("case-a"))
    _add_document(
        repository, case_id="case-a", title="Mean reversion", strategy_family="mean_reversion"
    )

    snapshot = ResearchCaseRetrievalService(repository).retrieve(
        _query(query_text='mean OR "reversion" NOT secret*')
    )

    assert [item.case_id for item in snapshot.candidates] == ["case-a"]
    assert snapshot.candidates[0].lexical_score >= 1


def test_case_document_rejects_obvious_secret_text(repository: AIRepository) -> None:
    repository.add_research_case(_case("case-a"))

    with pytest.raises(ResearchCaseDocumentError) as raised:
        ResearchCaseDocumentService(repository).create(
            case_id="case-a",
            title="Unsafe",
            summary="Authorization: Bearer abcdefghijklmnopqrstuvwxyz",
            diagnosis="None",
            success_factors=(),
            failure_factors=(),
            regime_labels=(),
            safe_tags=(),
            universe=("SSE:600000",),
            strategy_family=None,
            market_rules_version=None,
        )

    assert raised.value.code == "SECRET_MATERIAL_FORBIDDEN"
