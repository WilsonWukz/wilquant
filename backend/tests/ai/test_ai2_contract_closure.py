from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from quant_lab.ai.configuration import contains_forbidden_secret_material
from quant_lab.ai.contracts import (
    AnalysisRequirements,
    CanonicalEvidenceItem,
    ClaimPredicate,
    EvidenceClassification,
    EvidenceContext,
    EvidencePack,
    EvidenceSemanticType,
    EvidenceSourceType,
    FreshnessClass,
    FreshnessRequirement,
    GateDecision,
    StructuredCandidate,
    TemporalContext,
    Uncertainty,
)
from quant_lab.ai.gates import ResearchGate
from quant_lab.ai.policies import AI2Policy
from quant_lab.ai.resolvers import EvidenceRequest, ExplicitSnapshotResolver, SourceSnapshot
from quant_lab.ai.validation import ValidationService

NOW = datetime(2024, 2, 1, 12, tzinfo=UTC)


def _snapshot(source_id: str, *, value: object = Decimal("12.30")) -> SourceSnapshot:
    return SourceSnapshot(
        source_entity_id=source_id,
        source_version_id="v1",
        source_fingerprint="a" * 64,
        subject="SSE:600000",
        effective_at=datetime(2024, 1, 31, tzinfo=UTC),
        known_at=datetime(2024, 2, 1, tzinfo=UTC),
        observed_at=datetime(2024, 2, 1, 11, 59, 50, tzinfo=UTC),
        market_timestamp=datetime(2024, 2, 1, 11, 59, 45, tzinfo=UTC),
        freshness_class=FreshnessClass.REALTIME,
        known_delay_seconds=5,
        market="CN_A_SHARE",
        asset_type="EQUITY",
        instrument_id="SSE:600000",
        currency="CNY",
        context={"market": "CN_A_SHARE", "exchange": "SSE"},
        values={"cash": value},
    )


def _resolved_item(*, value: object = Decimal("12.30"), unit: str = "CNY"):
    resolver = ExplicitSnapshotResolver(
        source_type=EvidenceSourceType.PAPER_ACCOUNT_SNAPSHOT,
        field_classifications={"cash": EvidenceClassification.FACT},
        field_semantic_types={"cash": EvidenceSemanticType.MONEY},
        field_units={"cash": unit},
        resolver_policy_version="1",
        loader=lambda source_id: _snapshot(source_id, value=value),
    )
    return resolver.resolve(
        EvidenceRequest(
            source_type=EvidenceSourceType.PAPER_ACCOUNT_SNAPSHOT,
            source_id="snapshot-1",
            fields=("cash",),
        )
    )[0]


def _pack(*items: CanonicalEvidenceItem) -> EvidencePack:
    return EvidencePack(
        id="pack-1",
        case_id="case-1",
        temporal_context=TemporalContext(
            market_data_cutoff=datetime(2024, 2, 1, 23, 59, tzinfo=UTC),
            knowledge_cutoff=datetime(2024, 2, 1, 23, 59, tzinfo=UTC),
            market="CN_A_SHARE",
            timezone="Asia/Shanghai",
            asset_type="EQUITY",
            analysis_mode="CURRENT_RESEARCH",
        ),
        evidence_context=EvidenceContext(
            market="CN_A_SHARE",
            exchange="SSE",
            instrument_id="SSE:600000",
            currency="CNY",
            asset_type="EQUITY",
            timezone="Asia/Shanghai",
        ),
        requirements=AnalysisRequirements(),
        items=items,
        policy_version="ai-evidence-v2",
        fingerprint="f" * 64,
        created_at=NOW,
    )


def _candidate(claims: list[dict[str, object]]) -> dict[str, object]:
    return {
        "schema_version": "ai-structured-output-v1",
        "action_type": "RESEARCH_RECOMMENDATION",
        "recommendation": "REVIEW_STRATEGY",
        "claims": claims,
    }


def _claim(**updates: object) -> dict[str, object]:
    value: dict[str, object] = {
        "claim_id": "c1",
        "claim_type": "FACT",
        "text": "账户现金为 12.30 元",
        "subject": "SSE:600000",
        "predicate": "EQ",
        "value": "12.30",
        "unit": "CNY",
        "evidence_refs": [_resolved_item().ref_id],
        "operand_refs": [],
        "uncertainty": "LOW",
        "recommendation": None,
    }
    value.update(updates)
    return value


def test_canonical_evidence_item_contains_full_typed_contract() -> None:
    item = _resolved_item()

    assert item.ref_id.startswith("ev-")
    assert item.source_id == "snapshot-1"
    assert item.field_path == "cash"
    assert item.semantic_type is EvidenceSemanticType.MONEY
    assert item.classification is EvidenceClassification.FACT
    assert item.value == Decimal("12.30")
    assert item.unit == "CNY"
    assert item.source_fingerprint == "a" * 64
    assert len(item.value_fingerprint) == 64
    assert item.effective_at.tzinfo is UTC
    assert item.known_at.tzinfo is UTC
    assert item.observed_at == datetime(2024, 2, 1, 11, 59, 50, tzinfo=UTC)
    assert item.market_timestamp == datetime(2024, 2, 1, 11, 59, 45, tzinfo=UTC)
    assert item.freshness_class is FreshnessClass.REALTIME
    assert item.known_delay_seconds == 5
    assert item.context == {"exchange": "SSE", "market": "CN_A_SHARE"}
    assert item.resolver_policy_version == "1"
    assert "value_type" not in item.model_dump(mode="json")
    assert "content_fingerprint" not in item.model_dump(mode="json")


def test_value_fingerprint_depends_only_on_value_semantics_and_unit() -> None:
    first = _resolved_item(value=Decimal("12.30"), unit="CNY")
    same = _resolved_item(value=Decimal("12.300"), unit="cny")
    changed_value = _resolved_item(value=Decimal("12.31"), unit="CNY")
    changed_unit = _resolved_item(value=Decimal("12.30"), unit="USD")

    assert first.value_fingerprint == same.value_fingerprint
    assert first.value_fingerprint != changed_value.value_fingerprint
    assert first.value_fingerprint != changed_unit.value_fingerprint


def test_core_derived_ref_changes_with_policy_or_temporal_identity() -> None:
    first = _resolved_item()
    resolver = ExplicitSnapshotResolver(
        source_type=EvidenceSourceType.PAPER_ACCOUNT_SNAPSHOT,
        field_classifications={"cash": EvidenceClassification.FACT},
        field_semantic_types={"cash": EvidenceSemanticType.MONEY},
        field_units={"cash": "CNY"},
        resolver_policy_version="2",
        loader=_snapshot,
    )
    changed_policy = resolver.resolve(
        EvidenceRequest(
            source_type=EvidenceSourceType.PAPER_ACCOUNT_SNAPSHOT,
            source_id="snapshot-1",
            fields=("cash",),
        )
    )[0]

    assert first.ref_id != changed_policy.ref_id


def test_core_derived_ref_binds_freshness_metadata() -> None:
    first = _resolved_item()
    changed_snapshot = _snapshot("snapshot-1").model_copy(
        update={
            "freshness_class": FreshnessClass.DELAYED,
            "known_delay_seconds": 900,
        }
    )
    resolver = ExplicitSnapshotResolver(
        source_type=EvidenceSourceType.PAPER_ACCOUNT_SNAPSHOT,
        field_classifications={"cash": EvidenceClassification.FACT},
        field_semantic_types={"cash": EvidenceSemanticType.MONEY},
        field_units={"cash": "CNY"},
        resolver_policy_version="1",
        loader=lambda _: changed_snapshot,
    )
    changed = resolver.resolve(
        EvidenceRequest(
            source_type=EvidenceSourceType.PAPER_ACCOUNT_SNAPSHOT,
            source_id="snapshot-1",
            fields=("cash",),
        )
    )[0]

    assert first.value_fingerprint == changed.value_fingerprint
    assert first.ref_id != changed.ref_id


@pytest.mark.parametrize(
    "bad_context",
    (
        {"apiKey": "secret-value"},
        {"analysis_scope": {"nested": {"too": {"deep": True}}}},
        {"arbitrary_user_payload": "not-allowlisted"},
    ),
)
def test_evidence_context_is_bounded_allowlisted_and_secret_scanned(bad_context) -> None:
    snapshot = _snapshot("snapshot-1").model_copy(update={"context": bad_context})
    resolver = ExplicitSnapshotResolver(
        source_type=EvidenceSourceType.PAPER_ACCOUNT_SNAPSHOT,
        field_classifications={"cash": EvidenceClassification.FACT},
        field_semantic_types={"cash": EvidenceSemanticType.MONEY},
        field_units={"cash": "CNY"},
        resolver_policy_version="1",
        loader=lambda _: snapshot,
    )

    with pytest.raises(ValueError):
        resolver.resolve(
            EvidenceRequest(
                source_type=EvidenceSourceType.PAPER_ACCOUNT_SNAPSHOT,
                source_id="snapshot-1",
                fields=("cash",),
            )
        )


def test_formal_claim_contract_and_predicates_are_canonical() -> None:
    candidate = StructuredCandidate.model_validate(_candidate([_claim()]))

    claim = candidate.claims[0]
    assert claim.text == "账户现金为 12.30 元"
    assert claim.predicate is ClaimPredicate.EQ
    assert claim.uncertainty is Uncertainty.LOW
    assert candidate.recommendation == "REVIEW_STRATEGY"
    assert {value.value for value in ClaimPredicate} == {
        "EQ",
        "NE",
        "GT",
        "GTE",
        "LT",
        "LTE",
        "DELTA",
        "PERCENT_CHANGE",
    }


def test_policy_exposes_versioned_freshness_contract() -> None:
    policy = AI2Policy()

    assert policy.realtime_max_age_seconds == 30
    assert policy.research_gate_policy_version
    assert {value.value for value in FreshnessRequirement} == {
        "HISTORICAL_OK",
        "EOD_REQUIRED",
        "DELAYED_OK",
        "REALTIME_REQUIRED",
    }


@pytest.mark.parametrize(
    ("freshness_class", "requirement", "age_seconds", "accepted", "code"),
    (
        (
            FreshnessClass.IMMUTABLE_HISTORICAL,
            FreshnessRequirement.HISTORICAL_OK,
            999999,
            True,
            None,
        ),
        (FreshnessClass.EOD, FreshnessRequirement.EOD_REQUIRED, 86400, True, None),
        (FreshnessClass.EOD, FreshnessRequirement.REALTIME_REQUIRED, 1, False, "STALE_MARKET_DATA"),
        (FreshnessClass.DELAYED, FreshnessRequirement.DELAYED_OK, 1, True, None),
        (FreshnessClass.REALTIME, FreshnessRequirement.REALTIME_REQUIRED, 30, True, None),
        (
            FreshnessClass.REALTIME,
            FreshnessRequirement.REALTIME_REQUIRED,
            31,
            False,
            "STALE_MARKET_DATA",
        ),
    ),
)
def test_freshness_requirement_matrix_is_deterministic(
    freshness_class, requirement, age_seconds, accepted, code
) -> None:
    item = _resolved_item().model_copy(update={"freshness_class": freshness_class})
    result = ValidationService().validate(
        _candidate([_claim(evidence_refs=[item.ref_id])]),
        _pack(item),
        origin_attempt_id="attempt-freshness",
        freshness_requirement=requirement,
        reference_now=(item.observed_at or NOW) + timedelta(seconds=age_seconds),
    )

    assert result.accepted is accepted
    if code is not None:
        assert code in result.error_codes


def test_realtime_without_observed_at_waits_for_temporal_metadata() -> None:
    item = _resolved_item().model_copy(update={"observed_at": None})
    result = ValidationService().validate(
        _candidate([_claim(evidence_refs=[item.ref_id])]),
        _pack(item),
        origin_attempt_id="attempt-missing-time",
        freshness_requirement=FreshnessRequirement.REALTIME_REQUIRED,
        reference_now=NOW,
    )

    assert "TEMPORAL_METADATA_UNAVAILABLE" in result.error_codes
    gate = ResearchGate().decide(
        findings=result.findings,
        evidence_context=_pack(item).evidence_context,
        requirements=AnalysisRequirements(),
    )
    assert gate.decision is GateDecision.WAIT_FOR_EVIDENCE


@pytest.mark.parametrize(
    "payload",
    (
        {"items": [{"api_key": "x"}]},
        {"items": [{"apiKey": "x"}]},
        {"items": [{"client_secret": "x"}]},
        {"items": [{"clientSecret": "x"}]},
        {"items": [{"access_token": "x"}]},
        {"items": [{"accessToken": "x"}]},
        {"items": [{"Authorization": "x"}]},
        {"items": [{"BeArEr": "x"}]},
        {"items": [{"password": "x"}]},
        {"items": [{"gateway_secret": "x"}]},
        {"items": [{"broker_credential": "x"}]},
    ),
)
def test_nested_mixed_case_credentials_are_rejected(payload) -> None:
    assert contains_forbidden_secret_material(payload)


def test_stale_realtime_is_wait_not_reject_with_deterministic_reference_now() -> None:
    item = _resolved_item()
    result = ValidationService().validate(
        _candidate([_claim()]),
        _pack(item),
        origin_attempt_id="attempt-1",
        freshness_requirement=FreshnessRequirement.REALTIME_REQUIRED,
        reference_now=item.observed_at + timedelta(seconds=31),
    )

    assert "STALE_MARKET_DATA" in result.error_codes
    gate = ResearchGate().decide(
        findings=result.findings,
        evidence_context=_pack(item).evidence_context,
        requirements=AnalysisRequirements(),
    )
    assert gate.decision is GateDecision.WAIT_FOR_EVIDENCE


def test_naive_freshness_timestamp_is_rejected() -> None:
    payload = _snapshot("snapshot-1").model_dump()
    payload["observed_at"] = datetime(2024, 2, 1, 12)
    with pytest.raises(ValidationError, match="timezone-aware"):
        SourceSnapshot.model_validate(payload)


@pytest.mark.parametrize(
    ("predicate", "evidence", "claimed", "accepted"),
    (
        ("EQ", "12.30", "12.304", True),
        ("EQ", "12.30", "12.311", False),
        ("NE", "12.30", "12.304", False),
        ("NE", "12.30", "12.311", True),
        ("GT", "12.30", "12.29", True),
        ("GTE", "12.30", "12.30", True),
        ("LT", "12.30", "12.31", True),
        ("LTE", "12.30", "12.30", True),
    ),
)
def test_all_direct_predicates_use_semantic_type_tolerance(
    predicate: str, evidence: str, claimed: str, accepted: bool
) -> None:
    item = _resolved_item(value=Decimal(evidence))
    claim = _claim(
        predicate=predicate,
        value=claimed,
        evidence_refs=[item.ref_id],
    )

    result = ValidationService().validate(
        _candidate([claim]), _pack(item), origin_attempt_id="attempt-1"
    )

    assert result.accepted is accepted
    assert ("EVIDENCE_VALUE_MISMATCH" in result.error_codes) is (not accepted)


def test_ordering_predicate_rejects_text_semantic_type() -> None:
    resolver = ExplicitSnapshotResolver(
        source_type=EvidenceSourceType.RESEARCH_EXPERIMENT,
        field_classifications={"hypothesis": EvidenceClassification.FACT},
        field_semantic_types={"hypothesis": EvidenceSemanticType.TEXT},
        field_units={"hypothesis": None},
        resolver_policy_version="1",
        loader=lambda source_id: _snapshot(source_id).model_copy(
            update={"values": {"hypothesis": "alpha"}}
        ),
    )
    item = resolver.resolve(
        EvidenceRequest(
            source_type=EvidenceSourceType.RESEARCH_EXPERIMENT,
            source_id="experiment-1",
            fields=("hypothesis",),
        )
    )[0]
    claim = _claim(
        claim_type="FACT",
        predicate="GT",
        value="aardvark",
        unit=None,
        evidence_refs=[item.ref_id],
    )

    result = ValidationService().validate(
        _candidate([claim]), _pack(item), origin_attempt_id="attempt-1"
    )

    assert "SEMANTIC_PREDICATE_NOT_SUPPORTED" in result.error_codes


def test_delta_and_percent_change_use_formal_ordered_operand_formulas() -> None:
    old = _resolved_item(value=Decimal("100"))
    new_snapshot = _snapshot("snapshot-2", value=Decimal("120"))
    resolver = ExplicitSnapshotResolver(
        source_type=EvidenceSourceType.PAPER_ACCOUNT_SNAPSHOT,
        field_classifications={"cash": EvidenceClassification.FACT},
        field_semantic_types={"cash": EvidenceSemanticType.MONEY},
        field_units={"cash": "CNY"},
        resolver_policy_version="1",
        loader=lambda _: new_snapshot,
    )
    new = resolver.resolve(
        EvidenceRequest(
            source_type=EvidenceSourceType.PAPER_ACCOUNT_SNAPSHOT,
            source_id="snapshot-2",
            fields=("cash",),
        )
    )[0]
    pack = _pack(old, new)

    delta = ValidationService().validate(
        _candidate(
            [
                _claim(
                    predicate="DELTA",
                    value="20",
                    evidence_refs=[],
                    operand_refs=[new.ref_id, old.ref_id],
                )
            ]
        ),
        pack,
        origin_attempt_id="attempt-1",
    )
    percent = ValidationService().validate(
        _candidate(
            [
                _claim(
                    predicate="PERCENT_CHANGE",
                    value="0.2",
                    unit="RATIO",
                    evidence_refs=[],
                    operand_refs=[old.ref_id, new.ref_id],
                )
            ]
        ),
        pack,
        origin_attempt_id="attempt-1",
    )

    assert delta.accepted_assertions[0].value == Decimal("20")
    assert percent.accepted_assertions[0].value == Decimal("0.2")


def test_percent_change_zero_old_operand_has_stable_code() -> None:
    zero = _resolved_item(value=Decimal("0"))
    one_snapshot = _snapshot("snapshot-2", value=Decimal("1"))
    resolver = ExplicitSnapshotResolver(
        source_type=EvidenceSourceType.PAPER_ACCOUNT_SNAPSHOT,
        field_classifications={"cash": EvidenceClassification.FACT},
        field_semantic_types={"cash": EvidenceSemanticType.MONEY},
        field_units={"cash": "CNY"},
        resolver_policy_version="1",
        loader=lambda _: one_snapshot,
    )
    one = resolver.resolve(
        EvidenceRequest(
            source_type=EvidenceSourceType.PAPER_ACCOUNT_SNAPSHOT,
            source_id="snapshot-2",
            fields=("cash",),
        )
    )[0]

    result = ValidationService().validate(
        _candidate(
            [
                _claim(
                    predicate="PERCENT_CHANGE",
                    value="1",
                    unit="RATIO",
                    evidence_refs=[],
                    operand_refs=[zero.ref_id, one.ref_id],
                )
            ]
        ),
        _pack(zero, one),
        origin_attempt_id="attempt-1",
    )

    assert "DERIVED_DIVISION_BY_ZERO" in result.error_codes


def test_duplicate_claim_id_is_rejected_without_overwrite() -> None:
    item = _resolved_item()
    result = ValidationService().validate(
        _candidate([_claim(), _claim(value="99")]),
        _pack(item),
        origin_attempt_id="attempt-1",
    )

    assert "DUPLICATE_CLAIM_ID" in result.error_codes
    assert result.accepted_assertions == ()


@pytest.mark.parametrize(
    ("candidate", "code", "path"),
    (
        (
            {"schema_version": "ai-structured-output-v1", "action_type": "EXPERIMENT_DRAFT"},
            "SCHEMA_MISSING_FIELD",
            "claims",
        ),
        (
            {
                "schema_version": "ai-structured-output-v1",
                "action_type": "EXPERIMENT_DRAFT",
                "claims": "not-a-list",
            },
            "SCHEMA_INVALID_TYPE",
            "claims",
        ),
        (
            {
                "schema_version": "ai-structured-output-v1",
                "action_type": "EXPERIMENT_DRAFT",
                "claims": [
                    _claim(claim_id="c0"),
                    _claim(claim_id="c1"),
                    _claim(claim_id="c2", predicate="BETTER_THAN"),
                ],
            },
            "SCHEMA_INVALID_ENUM",
            "claims[2].predicate",
        ),
    ),
)
def test_pydantic_errors_map_to_stable_schema_findings(candidate, code, path) -> None:
    result = ValidationService().validate(
        candidate, _pack(_resolved_item()), origin_attempt_id="attempt-1"
    )

    matching = [finding for finding in result.findings if finding.code == code]
    assert matching
    assert matching[0].field_path == path


@pytest.mark.parametrize(
    "forbidden",
    (
        "EXECUTE_LIVE_ORDER",
        "CREATE_ORDER_INTENT",
        "APPROVE_EXECUTION",
        "INCREASE_CAPITAL",
        "UNFREEZE_ACCOUNT",
        "ACTIVATE_LIVE",
        "MODIFY_RISK_POLICY",
    ),
)
def test_recommendation_authority_escalation_is_rejected(forbidden: str) -> None:
    item = _resolved_item()
    candidate = _candidate([_claim()])
    candidate["recommendation"] = forbidden

    result = ValidationService().validate(candidate, _pack(item), origin_attempt_id="attempt-1")

    assert "FORBIDDEN_AI_AUTHORITY" in result.error_codes
