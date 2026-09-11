from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from quant_lab.ai.analysis_contracts import (
    STAGE1_CONTRACT_VERSION,
    AnalysisType,
    ResearchAnalysisRequest,
    ResearchDiagnosis,
)
from quant_lab.ai.validation import ValidationService

from .test_ai2_validation import _fact, _item, _pack


def diagnosis(**updates):
    result = dict(
        schema_version=STAGE1_CONTRACT_VERSION,
        analysis_type="MARKET_DIAGNOSIS",
        claims=[_fact()],
        observations=[],
        risks=[],
        uncertainties=[],
        abstention=None,
        analysis_specific=None,
    )
    result.update(updates)
    return result


@pytest.mark.parametrize("analysis_type", list(AnalysisType))
def test_common_envelope_supports_all_analysis_types(analysis_type):
    assert (
        ResearchDiagnosis.model_validate(diagnosis(analysis_type=analysis_type)).analysis_type
        == analysis_type
    )


def test_envelope_schema_errors_are_not_hidden_by_claim_projection():
    result = ValidationService().validate(
        diagnosis(unexpected="secret"),
        _pack(_item("a-new", Decimal("1.20"))),
        origin_attempt_id="attempt",
        stage_contract=STAGE1_CONTRACT_VERSION,
    )
    assert result.disposition == "REJECTED"
    assert not result.accepted_assertions
    assert result.observations and not result.observations[0].trusted


def test_schema_invalid_authority_is_non_retryable():
    result = ValidationService().validate(
        diagnosis(action_type="EXECUTE_LIVE_ORDER"),
        _pack(),
        origin_attempt_id="attempt",
        stage_contract=STAGE1_CONTRACT_VERSION,
    )
    assert any(f.code == "FORBIDDEN_AI_AUTHORITY" and not f.retryable for f in result.findings)


def test_schema_invalid_nested_execution_token_is_non_retryable():
    result = ValidationService().validate(
        diagnosis(payload={"operation": "EXECUTE_LIVE_ORDER"}),
        _pack(),
        origin_attempt_id="attempt",
        stage_contract=STAGE1_CONTRACT_VERSION,
    )
    assert any(f.code == "FORBIDDEN_AI_AUTHORITY" and not f.retryable for f in result.findings)


def test_unknown_stage_contract_cannot_silently_use_stage_two():
    with pytest.raises(ValueError, match="unsupported stage contract"):
        ValidationService().validate({}, _pack(), origin_attempt_id="a", stage_contract="UNKNOWN")


def test_diagnosis_is_bounded_and_forbids_extra_fields():
    with pytest.raises(ValidationError):
        ResearchDiagnosis.model_validate(diagnosis(risks=["x"] * 65))
    with pytest.raises(ValidationError):
        ResearchDiagnosis.model_validate(diagnosis(trade="BUY"))


def test_expected_analysis_type_is_checked_inside_validation():
    result = ValidationService().validate(
        diagnosis(claims=[]),
        _pack(),
        origin_attempt_id="attempt",
        stage_contract=STAGE1_CONTRACT_VERSION,
        expected_analysis_type=AnalysisType.PAPER_REVIEW,
    )
    assert any(f.code == "ANALYSIS_TYPE_MISMATCH" for f in result.findings)


def test_recommendation_references_are_grounded():
    from quant_lab.ai.analysis_contracts import STAGE2_CONTRACT_VERSION

    candidate = dict(
        schema_version=STAGE2_CONTRACT_VERSION,
        analysis_type="MARKET_DIAGNOSIS",
        summary="等待",
        claims=[],
        hypotheses=[],
        uncertainties=[],
        invalidation_conditions=[],
        suggested_next_actions=["WAIT_FOR_MORE_DATA"],
        evidence_refs=["missing"],
        diagnosis_ref="wrong",
    )
    result = ValidationService().validate(
        candidate,
        _pack(),
        origin_attempt_id="attempt",
        stage_contract=STAGE2_CONTRACT_VERSION,
        expected_diagnosis_ref="expected",
    )
    assert {f.code for f in result.findings} >= {"DIAGNOSIS_REF_MISMATCH", "EVIDENCE_REF_NOT_FOUND"}


def test_request_uses_closed_market_and_fixed_paper_ids():
    payload = dict(
        analysis_type="PAPER_REVIEW",
        market="CN_A_SHARE",
        asset_type="EQUITY",
        market_data_cutoff="2024-01-01T00:00:00Z",
        knowledge_cutoff="2024-01-01T00:00:00Z",
        freshness_requirement="HISTORICAL_OK",
        analysis_mode="HISTORICAL_REPLAY",
        research_question="review",
        model_config_version_id="m",
        stage1_prompt_template_version_id="s1",
        stage2_prompt_template_version_id="s2",
        paper_account_snapshot_ids=["p"],
        risk_decision_ids=["r"],
    )
    assert ResearchAnalysisRequest.model_validate(payload).paper_account_snapshot_ids == ("p",)
    with pytest.raises(ValidationError):
        ResearchAnalysisRequest.model_validate(dict(payload, market="INVALID"))


@pytest.mark.parametrize("schema_break", ["missing", "extra"])
@pytest.mark.parametrize("violation", ["fabricated", "future", "contradiction", "drift"])
def test_schema_invalid_envelope_retains_nonretryable_claim_safety(schema_break, violation):
    service = ValidationService()
    item = _item("a-new", Decimal("1.20"))
    pack = _pack(item)
    prior = service.validate(
        diagnosis(), pack, origin_attempt_id="first", stage_contract=STAGE1_CONTRACT_VERSION
    )
    claim = _fact()
    code = {
        "fabricated": "EVIDENCE_REF_NOT_FOUND",
        "future": "TEMPORAL_LEAK",
        "contradiction": "EVIDENCE_VALUE_MISMATCH",
        "drift": "IMMUTABLE_FACT_DRIFT",
    }[violation]
    if violation == "fabricated":
        claim["evidence_refs"] = ["invented"]
    elif violation == "future":
        pack = _pack(item.model_copy(update={"known_at": datetime(2099, 1, 1, tzinfo=UTC)}))
    else:
        claim["value"] = "9.99"
    candidate = diagnosis(claims=[claim])
    if schema_break == "missing":
        del candidate["risks"]
    else:
        candidate["unknown"] = "invalid"
    result = service.validate(
        candidate,
        pack,
        origin_attempt_id="retry",
        stage_contract=STAGE1_CONTRACT_VERSION,
        prior_assertions=prior.accepted_assertions if violation == "drift" else (),
    )
    assert result.disposition == "REJECTED" and not result.accepted_assertions
    assert result.observations and all(not item.trusted for item in result.observations)
    assert any(f.layer == "SCHEMA" for f in result.findings)
    assert any(f.code == code and not f.retryable for f in result.findings)


@pytest.mark.parametrize("schema_break", ["missing", "extra"])
@pytest.mark.parametrize("future", [False, True])
def test_schema_invalid_stage_two_checks_top_level_bindings(schema_break, future):
    from quant_lab.ai.analysis_contracts import STAGE2_CONTRACT_VERSION

    candidate = dict(
        schema_version=STAGE2_CONTRACT_VERSION,
        analysis_type="MARKET_DIAGNOSIS",
        summary="等待",
        claims=[],
        hypotheses=[],
        uncertainties=[],
        invalidation_conditions=[],
        suggested_next_actions=["WAIT_FOR_MORE_DATA"],
        evidence_refs=["a-new" if future else "invented"],
        diagnosis_ref="wrong",
    )
    if schema_break == "missing":
        del candidate["summary"]
    else:
        candidate["extra"] = True
    item = _item("a-new", Decimal("1.20")).model_copy(
        update={"known_at": datetime(2099, 1, 1, tzinfo=UTC)}
    )
    result = ValidationService().validate(
        candidate,
        _pack(item),
        origin_attempt_id="a",
        stage_contract=STAGE2_CONTRACT_VERSION,
        expected_diagnosis_ref="expected",
    )
    codes = {f.code for f in result.findings if not f.retryable}
    assert codes >= {
        "DIAGNOSIS_REF_MISMATCH",
        "TEMPORAL_LEAK" if future else "EVIDENCE_REF_NOT_FOUND",
    }
    assert any(f.layer == "SCHEMA" for f in result.findings)
    assert not result.accepted_assertions


@pytest.mark.parametrize("missing_field", ["claim_id", "text"])
@pytest.mark.parametrize("violation", ["fabricated", "future", "contradiction", "drift"])
def test_missing_claim_display_fields_do_not_hide_safety(missing_field, violation):
    service = ValidationService()
    item = _item("a-new", Decimal("1.20"))
    pack = _pack(item)
    prior = service.validate(
        diagnosis(), pack, origin_attempt_id="first", stage_contract=STAGE1_CONTRACT_VERSION
    )
    claim = _fact()
    del claim[missing_field]
    code = {
        "fabricated": "EVIDENCE_REF_NOT_FOUND",
        "future": "TEMPORAL_LEAK",
        "contradiction": "EVIDENCE_VALUE_MISMATCH",
        "drift": "IMMUTABLE_FACT_DRIFT",
    }[violation]
    if violation == "fabricated":
        claim["evidence_refs"] = ["invented"]
    elif violation == "future":
        pack = _pack(item.model_copy(update={"known_at": datetime(2099, 1, 1, tzinfo=UTC)}))
    else:
        claim["value"] = "9.99"
    result = service.validate(
        diagnosis(claims=[claim]),
        pack,
        origin_attempt_id="retry",
        stage_contract=STAGE1_CONTRACT_VERSION,
        prior_assertions=prior.accepted_assertions if violation == "drift" else (),
    )
    assert any(f.code == code and not f.retryable for f in result.findings)
    assert result.observations and not result.accepted_assertions


@pytest.mark.parametrize("future", [False, True])
def test_unparseable_claim_still_checks_safe_reference_strings(future):
    item = _item("a-new", Decimal("1.20")).model_copy(
        update={"known_at": datetime(2099, 1, 1, tzinfo=UTC)}
    )
    claim = {"evidence_refs": [None, {"unsafe": "object"}, "a-new" if future else "invented"]}
    result = ValidationService().validate(
        diagnosis(claims=[claim]),
        _pack(item),
        origin_attempt_id="retry",
        stage_contract=STAGE1_CONTRACT_VERSION,
    )
    assert any(
        f.code == ("TEMPORAL_LEAK" if future else "EVIDENCE_REF_NOT_FOUND") and not f.retryable
        for f in result.findings
    )
    assert not result.accepted_assertions


@pytest.mark.parametrize("future", [False, True])
@pytest.mark.parametrize("derived", [False, True])
def test_valid_schema_semantic_failure_cannot_hide_operand_reference_safety(future, derived):
    item = _item("a-new", Decimal("1.20")).model_copy(
        update={"known_at": datetime(2099, 1, 1, tzinfo=UTC)}
    )
    claim = _fact(
        evidence_refs=[],
        operand_refs=["a-new" if future else "invented"],
        predicate="DELTA" if derived else "EQ",
    )
    result = ValidationService().validate(
        diagnosis(claims=[claim]),
        _pack(item),
        origin_attempt_id="a",
        stage_contract=STAGE1_CONTRACT_VERSION,
    )
    assert any(
        f.code == ("TEMPORAL_LEAK" if future else "EVIDENCE_REF_NOT_FOUND") and not f.retryable
        for f in result.findings
    )


@pytest.mark.parametrize("field", ["text", "claim_id"])
@pytest.mark.parametrize("bad", [None, "", 123, "x" * 2001])
def test_invalid_claim_display_fields_preserve_contradiction_and_drift(field, bad):
    service = ValidationService()
    pack = _pack(_item("a-new", Decimal("1.20")))
    prior = service.validate(
        diagnosis(), pack, origin_attempt_id="first", stage_contract=STAGE1_CONTRACT_VERSION
    )
    claim = _fact(value="9.99")
    claim[field] = bad
    result = service.validate(
        diagnosis(claims=[claim]),
        pack,
        origin_attempt_id="retry",
        stage_contract=STAGE1_CONTRACT_VERSION,
        prior_assertions=prior.accepted_assertions,
    )
    assert {f.code for f in result.findings if not f.retryable} >= {
        "EVIDENCE_VALUE_MISMATCH",
        "IMMUTABLE_FACT_DRIFT",
    }
    assert any(f.layer == "SCHEMA" for f in result.findings)
    assert result.observations and not result.accepted_assertions
    assert all(not o.trusted for o in result.observations)
