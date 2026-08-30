from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from quant_lab.ai.contracts import (
    AnalysisRequirements,
    CanonicalEvidenceItem,
    EvidenceClassification,
    EvidenceContext,
    EvidenceSourceType,
    TemporalContext,
)
from quant_lab.ai.packs import EvidencePackError, EvidencePackService


class _PackRepository:
    def __init__(self) -> None:
        self.models = {}

    def find_evidence_pack_by_fingerprint(self, fingerprint):
        return next(
            (model for model in self.models.values() if model.fingerprint == fingerprint), None
        )

    def add_evidence_pack(self, model):
        self.models[model.id] = model
        return model


def _contexts():
    return (
        TemporalContext(
            market_data_cutoff="2024-01-31T23:59:59Z",
            knowledge_cutoff="2024-02-01T23:59:59Z",
            market="CN_A_SHARE",
            timezone="Asia/Shanghai",
            asset_type="EQUITY",
            analysis_mode="HISTORICAL_REPLAY",
        ),
        EvidenceContext(
            market="CN_A_SHARE",
            exchange="SSE",
            instrument_id="SSE:600000",
            currency="CNY",
            asset_type="EQUITY",
            timezone="Asia/Shanghai",
        ),
    )


def _item(**updates) -> CanonicalEvidenceItem:
    values = {
        "ref": "DATASET_VERSION:d:v1:close",
        "source_type": EvidenceSourceType.DATASET_VERSION,
        "source_entity_id": "d",
        "source_version_id": "v1",
        "field": "close",
        "value": Decimal("12.30"),
        "value_type": "DECIMAL",
        "unit": "CNY",
        "classification": EvidenceClassification.FACT,
        "subject": "SSE:600000",
        "effective_at": datetime(2024, 1, 31, tzinfo=UTC),
        "known_at": datetime(2024, 2, 1, tzinfo=UTC),
        "market": "CN_A_SHARE",
        "asset_type": "EQUITY",
        "instrument_id": "SSE:600000",
        "currency": "CNY",
        "content_fingerprint": "a" * 64,
    }
    values.update(updates)
    return CanonicalEvidenceItem(**values)


def test_pack_fingerprint_excludes_server_created_at_and_item_order() -> None:
    temporal, evidence = _contexts()
    first_repository = _PackRepository()
    second_repository = _PackRepository()
    second_item = _item(ref="DATASET_VERSION:d:v1:volume", field="volume", value=100)
    first = EvidencePackService(
        first_repository, clock=lambda: datetime(2026, 8, 30, 0, tzinfo=UTC)
    ).freeze(
        case_id="case-1",
        temporal_context=temporal,
        evidence_context=evidence,
        requirements=AnalysisRequirements(),
        items=(_item(), second_item),
    )
    second = EvidencePackService(
        second_repository, clock=lambda: datetime(2026, 8, 30, 1, tzinfo=UTC)
    ).freeze(
        case_id="case-1",
        temporal_context=temporal,
        evidence_context=evidence,
        requirements=AnalysisRequirements(),
        items=(second_item, _item()),
    )

    assert first.fingerprint == second.fingerprint
    assert first.created_at != second.created_at


@pytest.mark.parametrize(
    ("updates", "code"),
    (
        ({"known_at": datetime(2024, 2, 2, tzinfo=UTC)}, "FUTURE_KNOWLEDGE"),
        ({"effective_at": datetime(2024, 2, 1, tzinfo=UTC)}, "FUTURE_MARKET_DATA"),
        ({"market": "US_EQUITY"}, "MARKET_MISMATCH"),
        ({"asset_type": "ETF"}, "ASSET_TYPE_MISMATCH"),
        ({"instrument_id": "SSE:600001"}, "INSTRUMENT_MISMATCH"),
        ({"integrity_status": "INVALID"}, "INVALID_EVIDENCE"),
    ),
)
def test_pack_rejects_temporal_identity_or_integrity_violation(updates, code) -> None:
    repository = _PackRepository()
    temporal, evidence = _contexts()

    with pytest.raises(EvidencePackError) as raised:
        EvidencePackService(repository).freeze(
            case_id="case-1",
            temporal_context=temporal,
            evidence_context=evidence,
            requirements=AnalysisRequirements(),
            items=(_item(**updates),),
        )

    assert raised.value.code == code
    assert repository.models == {}


def test_pack_rejects_secret_shaped_field_before_persistence() -> None:
    repository = _PackRepository()
    temporal, evidence = _contexts()

    with pytest.raises(EvidencePackError) as raised:
        EvidencePackService(repository).freeze(
            case_id="case-1",
            temporal_context=temporal,
            evidence_context=evidence,
            requirements=AnalysisRequirements(),
            items=(_item(field="api_key"),),
        )

    assert raised.value.code == "SECRET_MATERIAL_FORBIDDEN"
    assert repository.models == {}
