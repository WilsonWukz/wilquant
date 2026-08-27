from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine

from quant_lab.ai import persistence  # noqa: F401
from quant_lab.ai.cases import ResearchCaseInput, ResearchCaseService
from quant_lab.ai.configuration import AIProvenanceError
from quant_lab.ai.evidence import EvidenceRefInput, EvidenceRefService
from quant_lab.ai.repository import AIRepository
from quant_lab.db.sqlite import Base


@pytest.fixture
def context():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    repository = AIRepository(engine)
    case = ResearchCaseService(repository).freeze(
        ResearchCaseInput(
            purpose="BACKTEST_REVIEW",
            market="CN_A_SHARE",
            exchange="SSE",
            symbol="600000",
            instrument_id="600000.XSHG",
            asset_type="EQUITY",
            currency="CNY",
            timeframe="1D",
            as_of_utc=datetime(2026, 8, 27, 8, tzinfo=UTC),
            market_local_trade_date=date(2026, 8, 27),
            bindings={
                "market_data_fingerprint": "a" * 64,
                "calendar_fingerprint": "b" * 64,
                "market_rules_fingerprint": "c" * 64,
            },
        ),
        actor="USER",
    )
    return EvidenceRefService(repository), case


def _evidence() -> EvidenceRefInput:
    return EvidenceRefInput(
        evidence_type="BACKTEST_METRIC",
        source_entity_type="BACKTEST_RUN",
        source_entity_id="run-1",
        source_version_id="backtest-engine@1",
        content_sha256="d" * 64,
        locator={"metric": "total_return"},
        effective_at=datetime(2026, 8, 26, 8, tzinfo=UTC),
        known_at=datetime(2026, 8, 27, 7, tzinfo=UTC),
        captured_at=datetime(2026, 8, 27, 7, 1, tzinfo=UTC),
        market="CN_A_SHARE",
        instrument_id="600000.XSHG",
        currency="CNY",
        temporal_status="ELIGIBLE",
        integrity_status="VERIFIED",
    )


def test_evidence_ref_is_idempotent_and_locator_affects_fingerprint(context) -> None:
    service, case = context
    first = service.register(case.id, _evidence())
    same = service.register(case.id, _evidence())
    changed = service.register(
        case.id, replace(_evidence(), locator={"metric": "max_drawdown"})
    )

    assert same.id == first.id
    assert changed.id != first.id
    assert changed.fingerprint != first.fingerprint


def test_evidence_ref_rejects_future_known_at(context) -> None:
    service, case = context
    with pytest.raises(AIProvenanceError, match="AI_EVIDENCE_FUTURE_KNOWLEDGE"):
        service.register(
            case.id,
            replace(_evidence(), known_at=datetime(2026, 8, 27, 8, 1, tzinfo=UTC)),
        )


def test_evidence_ref_normalizes_aware_times_and_rejects_naive(context) -> None:
    service, case = context
    equivalent = replace(
        _evidence(),
        known_at=datetime(2026, 8, 27, 15, tzinfo=timezone(timedelta(hours=8))),
    )
    assert service.register(case.id, equivalent).id == service.register(case.id, _evidence()).id

    with pytest.raises(AIProvenanceError, match="AI_EVIDENCE_TIMEZONE_REQUIRED"):
        service.register(case.id, replace(_evidence(), known_at=datetime(2026, 8, 27, 7)))


def test_evidence_ref_must_match_case_identity(context) -> None:
    service, case = context
    with pytest.raises(AIProvenanceError, match="AI_EVIDENCE_CASE_IDENTITY_MISMATCH"):
        service.register(case.id, replace(_evidence(), currency="USD"))


def test_evidence_ref_requires_existing_case(context) -> None:
    service, _ = context
    with pytest.raises(AIProvenanceError, match="AI_CASE_NOT_FOUND"):
        service.register("missing", _evidence())
