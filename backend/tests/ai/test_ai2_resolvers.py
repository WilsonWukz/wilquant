from __future__ import annotations

from datetime import UTC, datetime

import pytest

from quant_lab.ai.contracts import EvidenceClassification, EvidenceSourceType
from quant_lab.ai.resolvers import (
    DisallowedEvidenceField,
    EvidenceRequest,
    EvidenceResolverRegistry,
    SourceSnapshot,
    UnsupportedEvidenceSource,
)
from quant_lab.ai.source_resolvers import build_supported_resolver_registry


def _snapshot(source_id: str) -> SourceSnapshot:
    return SourceSnapshot(
        source_entity_id=source_id,
        source_version_id="v1",
        source_fingerprint="a" * 64,
        subject="SSE:600000",
        effective_at=datetime(2024, 1, 31, tzinfo=UTC),
        known_at=datetime(2024, 2, 1, tzinfo=UTC),
        market="CN_A_SHARE",
        asset_type="EQUITY",
        instrument_id="SSE:600000",
        currency="CNY",
        values={
            "row_count": 100,
            "max_timestamp": "2024-01-31T07:00:00Z",
            "status": "PUBLISHED",
        },
    )


def test_registry_rejects_unregistered_source() -> None:
    registry = EvidenceResolverRegistry()

    with pytest.raises(UnsupportedEvidenceSource, match="RESEARCH_JOURNAL"):
        registry.resolve_source("RESEARCH_JOURNAL", "journal-1")


def test_dataset_resolver_rejects_field_outside_allowlist() -> None:
    registry = build_supported_resolver_registry(
        {EvidenceSourceType.DATASET_VERSION: _snapshot}
    )

    with pytest.raises(DisallowedEvidenceField, match="database_url"):
        registry.resolve(
            EvidenceRequest(
                source_type=EvidenceSourceType.DATASET_VERSION,
                source_id="dataset-1",
                fields=("database_url",),
            )
        )


def test_dataset_resolver_builds_canonical_items_only_for_requested_fields() -> None:
    registry = build_supported_resolver_registry(
        {EvidenceSourceType.DATASET_VERSION: _snapshot}
    )

    items = registry.resolve(
        EvidenceRequest(
            source_type=EvidenceSourceType.DATASET_VERSION,
            source_id="dataset-1",
            fields=("row_count", "status"),
        )
    )

    assert [item.field for item in items] == ["row_count", "status"]
    assert items[0].classification is EvidenceClassification.FACT
    assert items[1].classification is EvidenceClassification.SYSTEM_STATE
    assert all(item.content_fingerprint == "a" * 64 for item in items)


def test_registry_rejects_duplicate_resolver_registration() -> None:
    registry = build_supported_resolver_registry(
        {EvidenceSourceType.DATASET_VERSION: _snapshot}
    )
    resolver = registry.get(EvidenceSourceType.DATASET_VERSION)

    with pytest.raises(ValueError, match="already registered"):
        registry.register(resolver)
