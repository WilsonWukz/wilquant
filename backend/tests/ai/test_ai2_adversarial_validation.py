from __future__ import annotations

from decimal import Decimal

from quant_lab.ai.validation import ValidationService, assertion_identity

from .test_ai2_validation import _candidate, _fact, _item, _pack


def test_claim_id_subject_alias_unit_spelling_and_ref_order_cannot_bypass_drift() -> None:
    pack = _pack(_item("a-new", Decimal("1.20")), _item("b-old", Decimal("1.20")))
    validator = ValidationService(subject_aliases={"600000": "SSE:600000"})
    original_claim = _fact(evidence_refs=["a-new", "b-old"])
    first = validator.validate(
        _candidate(original_claim), pack, origin_attempt_id="attempt-1"
    )
    prior = first.accepted_assertions[0]

    mutated = _fact(
        claim_id="different-id",
        subject="600000",
        unit="ratio",
        evidence_refs=["b-old", "a-new"],
        value="9.99",
    )
    retry = validator.validate(
        _candidate(mutated),
        pack,
        origin_attempt_id="attempt-2",
        prior_assertions=(prior,),
    )

    assert "IMMUTABLE_FACT_DRIFT" in retry.error_codes
    assert prior.assertion_identity == assertion_identity(
        retry_candidate := validator.parse_claim(mutated), pack, validator.subject_aliases
    )
    assert retry_candidate.claim_id == "different-id"


def test_operand_swap_is_detected_as_drift_not_a_new_fact() -> None:
    pack = _pack(_item("a-new", Decimal("120")), _item("b-old", Decimal("100")))
    validator = ValidationService()
    first = validator.validate(
        _candidate(
            _fact(
                predicate="DELTA",
                value="20",
                evidence_refs=[],
                operand_refs=["a-new", "b-old"],
            )
        ),
        pack,
        origin_attempt_id="attempt-1",
    )

    swapped = validator.validate(
        _candidate(
            _fact(
                claim_id="new-id",
                predicate="DELTA",
                value="-20",
                evidence_refs=[],
                operand_refs=["b-old", "a-new"],
            )
        ),
        pack,
        origin_attempt_id="attempt-2",
        prior_assertions=first.accepted_assertions,
    )

    assert "IMMUTABLE_FACT_DRIFT" in swapped.error_codes


def test_schema_invalid_assertion_is_untrusted_observation_only() -> None:
    invalid = {
        "schema_version": "ai-structured-output-v1",
        "action_type": "RESEARCH_ANALYSIS",
        "claims": [
            {
                "claim_id": "claim-1",
                "claim_type": "FACT",
                "subject": "SSE:600000",
                "predicate": "EQUALS",
                "value": "1.20",
                "unit": "RATIO",
                "evidence_refs": ["a-new"],
                "unexpected": "schema failure",
            }
        ],
    }

    result = ValidationService().validate(
        invalid,
        _pack(_item("a-new", Decimal("1.20"))),
        origin_attempt_id="attempt-schema-invalid",
    )

    assert "SCHEMA_INVALID" in result.error_codes
    assert not result.accepted
    assert result.accepted_assertions == ()
    assert len(result.observations) == 1
    assert result.observations[0].origin_attempt_id == "attempt-schema-invalid"
    assert result.observations[0].trusted is False


def test_forbidden_authority_is_rejected_even_with_grounded_fact() -> None:
    result = ValidationService().validate(
        _candidate(_fact(), action_type="EXECUTE_LIVE_ORDER"),
        _pack(_item("a-new", Decimal("1.20"))),
        origin_attempt_id="attempt-1",
    )

    assert "FORBIDDEN_AI_AUTHORITY" in result.error_codes
    assert not result.accepted


def test_zero_denominator_is_stable_validation_error() -> None:
    pack = _pack(_item("a-new", Decimal("120")), _item("b-old", Decimal("0")))
    result = ValidationService().validate(
        _candidate(
            _fact(
                predicate="PERCENT_CHANGE",
                value="0",
                evidence_refs=[],
                operand_refs=["a-new", "b-old"],
            )
        ),
        pack,
        origin_attempt_id="attempt-1",
    )

    assert "DERIVED_ZERO_DENOMINATOR" in result.error_codes
    assert not result.accepted
