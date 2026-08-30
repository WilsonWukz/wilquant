from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from quant_lab.ai.contracts import (
    AcceptedAssertion,
    AnalysisRequirements,
    CanonicalEvidenceItem,
    ClaimPredicate,
    ClaimType,
    EvidenceClassification,
    EvidenceContext,
    EvidencePack,
    EvidenceSourceType,
    TemporalContext,
    ValidationDisposition,
)
from quant_lab.ai.validation import ValidationService


def _item(
    ref: str,
    value: Decimal,
    *,
    classification: EvidenceClassification = EvidenceClassification.FACT,
) -> CanonicalEvidenceItem:
    return CanonicalEvidenceItem(
        ref=ref,
        source_type=EvidenceSourceType.BACKTEST_RUN,
        source_entity_id="run-1",
        source_version_id="v1",
        field=ref,
        value=value,
        value_type="DECIMAL",
        unit="RATIO",
        classification=classification,
        subject="SSE:600000",
        effective_at=datetime(2024, 1, 31, tzinfo=UTC),
        known_at=datetime(2024, 2, 1, tzinfo=UTC),
        market="CN_A_SHARE",
        asset_type="EQUITY",
        instrument_id="SSE:600000",
        currency="CNY",
        content_fingerprint=(ref[0] if ref[0] in "abcdef" else "a") * 64,
    )


def _pack(*items: CanonicalEvidenceItem) -> EvidencePack:
    return EvidencePack(
        id="pack-1",
        case_id="case-1",
        temporal_context=TemporalContext(
            market_data_cutoff="2024-01-31T23:59:59Z",
            knowledge_cutoff="2024-02-01T23:59:59Z",
            market="CN_A_SHARE",
            timezone="Asia/Shanghai",
            asset_type="EQUITY",
            analysis_mode="HISTORICAL_REPLAY",
        ),
        evidence_context=EvidenceContext(
            market="CN_A_SHARE",
            instrument_id="SSE:600000",
            currency="CNY",
            asset_type="EQUITY",
            timezone="Asia/Shanghai",
        ),
        requirements=AnalysisRequirements(),
        items=items,
        policy_version="ai-evidence-v1",
        fingerprint="f" * 64,
        created_at=datetime(2026, 8, 30, tzinfo=UTC),
    )


def _candidate(claim: dict, *, action_type: str = "RESEARCH_ANALYSIS") -> dict:
    return {
        "schema_version": "ai-structured-output-v1",
        "action_type": action_type,
        "claims": [claim],
    }


def _fact(**updates) -> dict:
    claim = {
        "claim_id": "claim-1",
        "claim_type": "FACT",
        "subject": "SSE:600000",
        "predicate": "EQUALS",
        "value": "1.20",
        "unit": "RATIO",
        "evidence_refs": ["a-new"],
        "operand_refs": [],
    }
    claim.update(updates)
    return claim


def test_valid_grounded_fact_is_accepted() -> None:
    result = ValidationService().validate(
        _candidate(_fact()),
        _pack(_item("a-new", Decimal("1.20"))),
        origin_attempt_id="attempt-1",
    )

    assert result.disposition is ValidationDisposition.ACCEPTED
    assert result.error_codes == ()
    assert result.accepted_assertions[0].value == Decimal("1.20")


def test_fabricated_ref_and_user_note_fact_are_rejected() -> None:
    validator = ValidationService()
    pack = _pack(
        _item("a-new", Decimal("1.20"), classification=EvidenceClassification.USER_NOTE)
    )

    fabricated = validator.validate(
        _candidate(_fact(evidence_refs=["missing"])),
        pack,
        origin_attempt_id="attempt-1",
    )
    user_note = validator.validate(
        _candidate(_fact()), pack, origin_attempt_id="attempt-1"
    )

    assert "FABRICATED_EVIDENCE_REF" in fabricated.error_codes
    assert "USER_NOTE_CANNOT_SUPPORT_FACT" in user_note.error_codes


def test_delta_and_percent_change_are_recomputed_from_ordered_operands() -> None:
    pack = _pack(_item("a-new", Decimal("120")), _item("b-old", Decimal("100")))
    validator = ValidationService()
    delta = _fact(
        predicate="DELTA",
        value="20",
        operand_refs=["a-new", "b-old"],
        evidence_refs=[],
    )
    percent = _fact(
        predicate="PERCENT_CHANGE",
        value="0.20",
        operand_refs=["a-new", "b-old"],
        evidence_refs=[],
    )

    delta_result = validator.validate(
        _candidate(delta), pack, origin_attempt_id="attempt-1"
    )
    percent_result = validator.validate(
        _candidate(percent), pack, origin_attempt_id="attempt-1"
    )

    assert delta_result.accepted_assertions[0].value == Decimal("20")
    assert percent_result.accepted_assertions[0].value == Decimal("0.2")


def test_grounding_contradiction_is_not_accepted() -> None:
    result = ValidationService().validate(
        _candidate(_fact(value="99")),
        _pack(_item("a-new", Decimal("1.20"))),
        origin_attempt_id="attempt-1",
    )

    assert "GROUNDING_CONTRADICTION" in result.error_codes
    assert result.accepted_assertions == ()


def test_prior_assertion_helper_has_stable_shape() -> None:
    assertion = AcceptedAssertion(
        assertion_identity="a" * 64,
        claim_id="old-id",
        claim_type=ClaimType.FACT,
        subject="SSE:600000",
        predicate=ClaimPredicate.EQUALS,
        value=Decimal("1.20"),
        unit="RATIO",
        evidence_refs=("a-new",),
        operand_refs=(),
    )
    assert assertion.claim_id == "old-id"
