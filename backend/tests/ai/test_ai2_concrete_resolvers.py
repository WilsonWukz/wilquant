from __future__ import annotations

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from quant_lab.ai.contracts import (
    EvidenceClassification,
    EvidenceSemanticType,
    EvidenceSourceType,
)
from quant_lab.ai.resolvers import (
    DisallowedEvidenceField,
    EvidenceRequest,
    EvidenceSourceNotFound,
)
from quant_lab.ai.source_resolvers import build_domain_resolver_registry
from quant_lab.backtest.persistence import BacktestArtifactModel, BacktestRunModel
from quant_lab.backtest.strategy_library import StrategyDefinitionModel, StrategyVersionModel
from quant_lab.datasets.persistence import DatasetModel, DatasetVersionModel
from quant_lab.db.sqlite import Base
from quant_lab.paper.models import (
    PaperAccountModel,
    PaperAccountSnapshotModel,
    PaperOrderIntentModel,
    PaperRiskDecisionModel,
    PaperRiskPolicyModel,
    PaperRiskPolicyVersionModel,
    PaperSessionModel,
)
from quant_lab.research.persistence import ExperimentRunLinkModel, ResearchExperimentModel

KNOWN = datetime(2024, 2, 1, 8, tzinfo=UTC)
EFFECTIVE = datetime(2024, 1, 31, 8, tzinfo=UTC)


@pytest.fixture
def domain_registry(tmp_path: Path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'domain.db'}")
    Base.metadata.create_all(engine)
    runtime = tmp_path / "runtime"
    metrics_path = runtime / "artifacts" / "metrics.json"
    metrics_path.parent.mkdir(parents=True)
    metrics_path.write_text(
        json.dumps({"sharpe_ratio": "1.25", "max_drawdown": "0.08"}),
        encoding="utf-8",
    )
    snapshot = {
        "profile_id": "profile-1",
        "bars_dataset_version_id": "dv1",
        "bars_dataset_fingerprint": "1" * 64,
        "calendar_version_id": "calendar-v1",
        "calendar_fingerprint": "2" * 64,
        "snapshot_fingerprint": "3" * 64,
    }
    with Session(engine) as session:
        session.add_all(
            [
                DatasetModel(
                    dataset_id="d1",
                    dataset_key="bars-cn",
                    logical_key="CN:DAILY:BARS",
                    name="CN bars",
                    description=None,
                    dataset_type="BAR",
                    market="CN_A_SHARE",
                    frequency="1d",
                    adjustment_type="NONE",
                    schema_version="bars@1",
                    created_at=KNOWN,
                    updated_at=KNOWN,
                    is_active=True,
                ),
                DatasetVersionModel(
                    dataset_version_id="dv1",
                    dataset_id="d1",
                    version=1,
                    status="PUBLISHED",
                    source_batch_id="batch-1",
                    source_preview_fingerprint="0" * 64,
                    publication_fingerprint="1" * 64,
                    schema_version="bars@1",
                    normalization_version="normalization@1",
                    quality_rules_version="quality@1",
                    publication_format_version="publication@1",
                    partition_strategy_version="partition@1",
                    row_count=20,
                    instrument_count=1,
                    min_timestamp=datetime(2024, 1, 1, tzinfo=UTC),
                    max_timestamp=EFFECTIVE,
                    partition_count=1,
                    file_count=1,
                    total_size_bytes=100,
                    quality_issue_count=0,
                    warning_count=0,
                    blocking_issue_count=0,
                    quality_summary_json="{}",
                    relative_version_root="datasets/d1/v1",
                    manifest_path="manifest.json",
                    manifest_sha256="4" * 64,
                    publication_claimed_at=KNOWN,
                    published_at=KNOWN,
                    created_at=KNOWN,
                ),
                StrategyDefinitionModel(
                    id="sd1",
                    name="Buy and hold",
                    description="deterministic",
                    strategy_type="BUY_AND_HOLD",
                    status="ACTIVE",
                    created_at=KNOWN,
                    updated_at=KNOWN,
                ),
                StrategyVersionModel(
                    id="sv1",
                    strategy_definition_id="sd1",
                    version=1,
                    strategy_spec_json='{"weight":"0.5"}',
                    strategy_fingerprint="5" * 64,
                    change_note="initial",
                    created_at=KNOWN,
                ),
                BacktestRunModel(
                    backtest_run_id="run1",
                    name="run one",
                    status="SUCCEEDED",
                    market_data_profile_id="profile-1",
                    market_data_snapshot_json=json.dumps(snapshot),
                    market_data_snapshot_fingerprint="3" * 64,
                    strategy_type="BUY_AND_HOLD",
                    strategy_version_id="sv1",
                    strategy_spec_json="{}",
                    strategy_fingerprint="5" * 64,
                    engine_version="backtest@1",
                    config_json="{}",
                    config_fingerprint="6" * 64,
                    run_input_fingerprint="7" * 64,
                    initial_cash=Decimal("100000"),
                    start_date=date(2024, 1, 1),
                    end_date=date(2024, 1, 31),
                    started_at=KNOWN,
                    completed_at=KNOWN,
                    artifact_manifest_path="artifacts/manifest.json",
                    created_at=KNOWN,
                ),
                BacktestArtifactModel(
                    backtest_artifact_id="artifact-metrics",
                    backtest_run_id="run1",
                    artifact_type="METRICS",
                    relative_path="artifacts/metrics.json",
                    size_bytes=metrics_path.stat().st_size,
                    sha256="8" * 64,
                    row_count=1,
                    created_at=KNOWN,
                ),
                ResearchExperimentModel(
                    id="exp1",
                    name="experiment one",
                    hypothesis="momentum may persist",
                    market_data_profile_id="profile-1",
                    status="ACTIVE",
                    tags_json='["momentum"]',
                    created_at=KNOWN,
                    updated_at=KNOWN,
                ),
                ExperimentRunLinkModel(
                    id="link1",
                    experiment_id="exp1",
                    backtest_run_id="run1",
                    role="BASELINE",
                    label="baseline",
                    created_at=KNOWN,
                ),
                PaperAccountModel(
                    id="pa1",
                    name="paper account",
                    status="ACTIVE",
                    base_currency="CNY",
                    initial_cash=Decimal("100000"),
                    cash=Decimal("90000"),
                    market_value=Decimal("10000"),
                    account_equity=Decimal("100000"),
                    created_at=KNOWN,
                    updated_at=KNOWN,
                ),
                PaperSessionModel(
                    id="ps1",
                    name="paper session",
                    paper_account_id="pa1",
                    market_data_profile_id="profile-1",
                    market_data_snapshot_json=json.dumps(snapshot),
                    market_data_snapshot_fingerprint="3" * 64,
                    strategy_version_id="sv1",
                    status="PAUSED",
                    current_session_date=date(2024, 1, 31),
                    replay_start_date=date(2024, 1, 1),
                    replay_end_date=date(2024, 1, 31),
                    execution_config_json='{"mode":"CLOSE"}',
                    execution_config_fingerprint="9" * 64,
                    version=2,
                    created_at=KNOWN,
                    updated_at=KNOWN,
                ),
                PaperAccountSnapshotModel(
                    id="pas1",
                    paper_account_id="pa1",
                    paper_session_id="ps1",
                    session_date=date(2024, 1, 31),
                    cash=Decimal("90000"),
                    market_value=Decimal("10000"),
                    equity=Decimal("100000"),
                    gross_exposure=Decimal("10000"),
                    daily_pnl=Decimal("100"),
                    cumulative_pnl=Decimal("500"),
                    drawdown=Decimal("0.02"),
                    created_at=KNOWN,
                ),
                PaperRiskPolicyModel(
                    id="rp1",
                    paper_account_id="pa1",
                    name="default",
                    status="ACTIVE",
                    created_at=KNOWN,
                ),
                PaperRiskPolicyVersionModel(
                    id="rpv1",
                    risk_policy_id="rp1",
                    version=1,
                    max_single_order_notional=Decimal("10000"),
                    max_single_position_weight=Decimal("0.2"),
                    max_total_exposure=Decimal("0.8"),
                    cash_buffer_ratio=Decimal("0.1"),
                    max_daily_loss=Decimal("0.05"),
                    max_drawdown=Decimal("0.2"),
                    max_open_orders=10,
                    allowed_security_types_json='["EQUITY"]',
                    policy_fingerprint="a" * 64,
                    created_at=KNOWN,
                ),
                PaperOrderIntentModel(
                    id="intent1",
                    paper_session_id="ps1",
                    source_type="MANUAL",
                    source_id=None,
                    instrument_id="SSE:600000",
                    side="BUY",
                    quantity=100,
                    order_type="MARKET",
                    limit_price=None,
                    signal_session_date=date(2024, 1, 31),
                    intended_execution_session=date(2024, 1, 31),
                    strategy_version_id="sv1",
                    reason="TEST",
                    metadata_json="{}",
                    idempotency_key="intent-key",
                    created_at=KNOWN,
                ),
                PaperRiskDecisionModel(
                    id="rd1",
                    order_intent_id="intent1",
                    decision="APPROVED",
                    reason_codes_json='["WITHIN_LIMITS"]',
                    risk_policy_id="rp1",
                    risk_policy_version_id="rpv1",
                    risk_policy_version=1,
                    account_snapshot_json='{"cash":"90000","gross_exposure":"10000"}',
                    position_snapshot_json="null",
                    market_context_json='{"estimated_notional":"1000"}',
                    evaluated_at=KNOWN,
                ),
            ]
        )
        session.commit()

    registry = build_domain_resolver_registry(engine=engine, artifact_root=runtime)
    try:
        yield registry
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    ("source_type", "source_id", "field", "semantic_type", "classification"),
    (
        (
            EvidenceSourceType.DATASET_VERSION,
            "dv1",
            "row_count",
            EvidenceSemanticType.COUNT,
            EvidenceClassification.FACT,
        ),
        (
            EvidenceSourceType.MARKET_DATA_SNAPSHOT,
            "run1",
            "snapshot_fingerprint",
            EvidenceSemanticType.IDENTIFIER,
            EvidenceClassification.FACT,
        ),
        (
            EvidenceSourceType.STRATEGY_VERSION,
            "sv1",
            "strategy_fingerprint",
            EvidenceSemanticType.IDENTIFIER,
            EvidenceClassification.FACT,
        ),
        (
            EvidenceSourceType.BACKTEST_RUN,
            "run1",
            "metrics.sharpe",
            EvidenceSemanticType.RATIO,
            EvidenceClassification.DERIVED_METRIC,
        ),
        (
            EvidenceSourceType.RESEARCH_EXPERIMENT,
            "exp1",
            "hypothesis",
            EvidenceSemanticType.TEXT,
            EvidenceClassification.USER_NOTE,
        ),
        (
            EvidenceSourceType.RESEARCH_COMPARISON,
            "exp1",
            "ranking_allowed",
            EvidenceSemanticType.BOOLEAN,
            EvidenceClassification.DERIVED_METRIC,
        ),
        (
            EvidenceSourceType.RESEARCH_DIAGNOSTIC,
            "run1",
            "counts",
            EvidenceSemanticType.JSON,
            EvidenceClassification.DERIVED_METRIC,
        ),
        (
            EvidenceSourceType.RESEARCH_REPORT,
            "run1",
            "report_fingerprint",
            EvidenceSemanticType.IDENTIFIER,
            EvidenceClassification.FACT,
        ),
        (
            EvidenceSourceType.PAPER_SESSION,
            "ps1",
            "version",
            EvidenceSemanticType.COUNT,
            EvidenceClassification.SYSTEM_STATE,
        ),
        (
            EvidenceSourceType.PAPER_ACCOUNT_SNAPSHOT,
            "pas1",
            "cash",
            EvidenceSemanticType.MONEY,
            EvidenceClassification.FACT,
        ),
        (
            EvidenceSourceType.RISK_DECISION,
            "rd1",
            "decision",
            EvidenceSemanticType.ENUM,
            EvidenceClassification.SYSTEM_STATE,
        ),
    ),
)
def test_each_supported_source_resolves_from_real_domain_records(
    domain_registry, source_type, source_id, field, semantic_type, classification
) -> None:
    request = EvidenceRequest(source_type=source_type, source_id=source_id, fields=(field,))

    first = domain_registry.resolve(request)[0]
    second = domain_registry.resolve(request)[0]

    assert first.semantic_type is semantic_type
    assert first.classification is classification
    assert first.source_fingerprint == second.source_fingerprint
    assert first.value_fingerprint == second.value_fingerprint
    assert first.ref_id == second.ref_id
    assert first.resolver_policy_version == "1"
    assert first.known_at.tzinfo is not None
    assert first.effective_at.tzinfo is not None


def test_concrete_resolver_missing_and_forbidden_fields_fail_closed(domain_registry) -> None:
    with pytest.raises(EvidenceSourceNotFound):
        domain_registry.resolve(
            EvidenceRequest(
                source_type=EvidenceSourceType.DATASET_VERSION,
                source_id="missing",
                fields=("row_count",),
            )
        )


def test_concrete_resolvers_are_read_only(domain_registry) -> None:
    engine = domain_registry.get(EvidenceSourceType.PAPER_SESSION)._loader.__self__.engine
    with Session(engine) as session:
        before_session = session.get(PaperSessionModel, "ps1")
        before_account = session.get(PaperAccountModel, "pa1")
        before = (
            before_session.status,
            before_session.version,
            before_account.status,
            before_account.cash,
        )

    domain_registry.resolve(
        EvidenceRequest(
            source_type=EvidenceSourceType.PAPER_SESSION,
            source_id="ps1",
            fields=("status",),
        )
    )
    domain_registry.resolve(
        EvidenceRequest(
            source_type=EvidenceSourceType.RISK_DECISION,
            source_id="rd1",
            fields=("decision",),
        )
    )

    with Session(engine) as session:
        after_session = session.get(PaperSessionModel, "ps1")
        after_account = session.get(PaperAccountModel, "pa1")
        after = (
            after_session.status,
            after_session.version,
            after_account.status,
            after_account.cash,
        )
    assert after == before
    with pytest.raises(DisallowedEvidenceField):
        domain_registry.resolve(
            EvidenceRequest(
                source_type=EvidenceSourceType.DATASET_VERSION,
                source_id="dv1",
                fields=("apiKey",),
            )
        )
