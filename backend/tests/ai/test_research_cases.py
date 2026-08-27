from __future__ import annotations

from datetime import UTC, date, datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine

from quant_lab.ai import persistence  # noqa: F401
from quant_lab.ai.cases import ResearchCaseInput, ResearchCaseService
from quant_lab.ai.configuration import AIProvenanceError
from quant_lab.ai.repository import AIRepository
from quant_lab.db.sqlite import Base


@pytest.fixture
def service() -> ResearchCaseService:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return ResearchCaseService(AIRepository(engine))


def _case_input(**changes) -> ResearchCaseInput:
    values = {
        "purpose": "BACKTEST_REVIEW",
        "market": "CN_A_SHARE",
        "exchange": "SSE",
        "symbol": "600000",
        "instrument_id": "600000.XSHG",
        "asset_type": "EQUITY",
        "currency": "CNY",
        "timeframe": "1D",
        "as_of_utc": datetime(2026, 8, 27, 8, tzinfo=UTC),
        "market_local_trade_date": date(2026, 8, 27),
        "bindings": {
            "market_data_fingerprint": "a" * 64,
            "calendar_fingerprint": "b" * 64,
            "market_rules_fingerprint": "c" * 64,
        },
    }
    values.update(changes)
    return ResearchCaseInput(**values)


def test_case_identity_is_idempotent_and_includes_market_fields(service) -> None:
    first = service.freeze(_case_input(), actor="USER")
    same = service.freeze(_case_input(), actor="USER")
    us = service.freeze(
        _case_input(
            market="US",
            exchange="NASDAQ",
            symbol="AAPL",
            instrument_id="US:NASDAQ:AAPL:USD:EQUITY",
            currency="USD",
        ),
        actor="USER",
    )

    assert same.id == first.id
    assert us.id != first.id
    assert us.fingerprint != first.fingerprint


def test_case_cutoff_is_utc_and_changes_identity(service) -> None:
    local = datetime(2026, 8, 27, 16, tzinfo=timezone(timedelta(hours=8)))
    first = service.freeze(_case_input(as_of_utc=local), actor="USER")
    same_utc = service.freeze(
        _case_input(as_of_utc=datetime(2026, 8, 27, 8, tzinfo=UTC)), actor="USER"
    )
    later = service.freeze(
        _case_input(as_of_utc=datetime(2026, 8, 27, 8, 1, tzinfo=UTC)), actor="USER"
    )

    assert same_utc.id == first.id
    assert later.id != first.id


def test_case_rejects_naive_cutoff_and_missing_bindings(service) -> None:
    with pytest.raises(AIProvenanceError, match="AI_CASE_TIMEZONE_REQUIRED"):
        service.freeze(_case_input(as_of_utc=datetime(2026, 8, 27, 8)), actor="USER")
    with pytest.raises(AIProvenanceError, match="AI_CASE_BINDINGS_INCOMPLETE"):
        service.freeze(_case_input(bindings={"market_data_fingerprint": "a" * 64}), actor="USER")


def test_case_lineage_requires_existing_parent(service) -> None:
    with pytest.raises(AIProvenanceError, match="AI_CASE_PARENT_NOT_FOUND"):
        service.freeze(_case_input(previous_case_id="missing"), actor="USER")
