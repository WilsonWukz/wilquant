from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from quant_lab.ai.contracts import (
    AnalysisRequirements,
    CanonicalEvidenceItem,
    EvidenceClassification,
    EvidenceContext,
    EvidenceSourceType,
    TemporalContext,
)
from quant_lab.ai.policies import AI2Policy


def _aware(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(UTC)


def test_temporal_context_normalizes_aware_datetimes_to_utc() -> None:
    context = TemporalContext(
        market_data_cutoff="2024-01-01T08:00:00+08:00",
        knowledge_cutoff="2024-01-02T08:00:00+08:00",
        market="CN_A_SHARE",
        timezone="Asia/Shanghai",
        asset_type="EQUITY",
        analysis_mode="HISTORICAL_REPLAY",
    )

    assert context.market_data_cutoff == _aware("2024-01-01T00:00:00+00:00")
    assert context.knowledge_cutoff == _aware("2024-01-02T00:00:00+00:00")


def test_temporal_context_rejects_naive_datetime() -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        TemporalContext(
            market_data_cutoff=datetime(2024, 1, 1),
            knowledge_cutoff=_aware("2024-01-02T00:00:00+00:00"),
            market="CN_A_SHARE",
            timezone="Asia/Shanghai",
            asset_type="EQUITY",
            analysis_mode="HISTORICAL_REPLAY",
        )


def test_market_rules_version_is_nullable_for_rule_independent_analysis() -> None:
    context = EvidenceContext(
        market="CN_A_SHARE",
        exchange="SSE",
        instrument_id="SSE:600000",
        currency="CNY",
        asset_type="EQUITY",
        timezone="Asia/Shanghai",
        market_rules_version=None,
    )
    requirements = AnalysisRequirements()

    assert context.market_rules_version is None
    assert not requirements.requires_market_rules


def test_analysis_requirements_reject_unrecognized_rule_topic() -> None:
    with pytest.raises(ValidationError):
        AnalysisRequirements(required_rule_topics=("invented_rule",))


def test_evidence_item_is_frozen_and_decimal_safe() -> None:
    item = CanonicalEvidenceItem(
        ref="dataset:version:v1:max_close",
        source_type=EvidenceSourceType.DATASET_VERSION,
        source_entity_id="dataset-version-v1",
        source_version_id="v1",
        field="max_close",
        value=Decimal("12.30"),
        value_type="DECIMAL",
        unit="CNY",
        classification=EvidenceClassification.FACT,
        subject="SSE:600000",
        effective_at=_aware("2024-01-01T00:00:00+00:00"),
        known_at=_aware("2024-01-02T00:00:00+00:00"),
        market="CN_A_SHARE",
        asset_type="EQUITY",
        instrument_id="SSE:600000",
        currency="CNY",
        content_fingerprint="a" * 64,
    )

    assert item.value == Decimal("12.30")
    with pytest.raises(ValidationError):
        item.value = Decimal("99")


def test_policy_is_fixed_and_bounded() -> None:
    policy = AI2Policy()

    assert policy.evidence_policy_version == "ai-evidence-v2"
    assert policy.validation_policy_version == "ai-validation-v2"
    assert policy.retrieval_policy_version == "ai-retrieval-v1"
    assert policy.max_evidence_items == 128
    assert policy.max_evidence_bytes == 262_144
    assert policy.max_retrieval_cases == 20
    assert policy.strategy_family_weight > policy.safe_tag_weight

    with pytest.raises(ValidationError):
        policy.strategy_family_weight = 1
