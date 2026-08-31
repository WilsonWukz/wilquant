from __future__ import annotations

from datetime import UTC, datetime

import pytest

from quant_lab.ai.contracts import EvidenceClassification, EvidenceSourceType
from quant_lab.ai.resolvers import EvidenceRequest, SourceSnapshot, UnsupportedEvidenceSource
from quant_lab.ai.source_resolvers import (
    SUPPORTED_SOURCE_POLICIES,
    build_supported_resolver_registry,
)


def _loader(source_id: str) -> SourceSnapshot:
    return SourceSnapshot(
        source_entity_id=source_id,
        source_version_id="v1",
        source_fingerprint="b" * 64,
        subject="SSE:600000",
        effective_at=datetime(2024, 1, 31, tzinfo=UTC),
        known_at=datetime(2024, 2, 1, tzinfo=UTC),
        market="CN_A_SHARE",
        asset_type="EQUITY",
        instrument_id="SSE:600000",
        currency="CNY",
        values={
            field: "hypothesis" if field == "hypothesis" else "value"
            for field in SUPPORTED_SOURCE_POLICIES[
                EvidenceSourceType.RESEARCH_EXPERIMENT
            ].fields
        },
    )


def test_all_and_only_approved_sources_have_explicit_field_policies() -> None:
    assert set(SUPPORTED_SOURCE_POLICIES) == set(EvidenceSourceType)
    assert all(policy.fields for policy in SUPPORTED_SOURCE_POLICIES.values())
    assert all("database_url" not in policy.fields for policy in SUPPORTED_SOURCE_POLICIES.values())


def test_every_supported_source_can_resolve_through_its_explicit_adapter() -> None:
    def loader_for(source_type: EvidenceSourceType):
        def load(source_id: str) -> SourceSnapshot:
            policy = SUPPORTED_SOURCE_POLICIES[source_type]
            return SourceSnapshot(
                source_entity_id=source_id,
                source_version_id="v1",
                source_fingerprint="c" * 64,
                subject="SSE:600000",
                effective_at=datetime(2024, 1, 31, tzinfo=UTC),
                known_at=datetime(2024, 2, 1, tzinfo=UTC),
                market="CN_A_SHARE",
                asset_type="EQUITY",
                instrument_id="SSE:600000",
                currency="CNY",
                values={field: "value" for field in policy.fields},
            )

        return load

    registry = build_supported_resolver_registry(
        {source_type: loader_for(source_type) for source_type in EvidenceSourceType}
    )

    for source_type, policy in SUPPORTED_SOURCE_POLICIES.items():
        field = min(policy.fields)
        (item,) = registry.resolve(
            EvidenceRequest(
                source_type=source_type,
                source_id=f"{source_type.value.lower()}-1",
                fields=(field,),
            )
        )
        assert item.source_type is source_type
        assert item.field == field


def test_experiment_hypothesis_is_always_user_note() -> None:
    registry = build_supported_resolver_registry(
        {EvidenceSourceType.RESEARCH_EXPERIMENT: _loader}
    )

    (item,) = registry.resolve(
        EvidenceRequest(
            source_type=EvidenceSourceType.RESEARCH_EXPERIMENT,
            source_id="experiment-1",
            fields=("hypothesis",),
        )
    )

    assert item.classification is EvidenceClassification.USER_NOTE


@pytest.mark.parametrize(
    "deferred",
    (
        "MARKET_DATA_PROFILE",
        "RESEARCH_JOURNAL",
        "MARKET_RULES_VERSION",
        "US_REALTIME_QUOTE",
    ),
)
def test_deferred_sources_fail_closed(deferred: str) -> None:
    registry = build_supported_resolver_registry({})

    with pytest.raises(UnsupportedEvidenceSource):
        registry.resolve_source(deferred, "source-1")
