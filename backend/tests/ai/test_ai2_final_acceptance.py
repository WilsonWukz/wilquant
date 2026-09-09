from __future__ import annotations

from datetime import timedelta

import pytest
from pydantic import ValidationError
from sqlalchemy.orm import Session

from quant_lab.ai.contracts import (
    AnalysisRequirements,
    CanonicalEvidenceItem,
    EvidenceSourceType,
    FindingSeverity,
    FreshnessRequirement,
    GateDecision,
    ValidationFinding,
    ValidationLayer,
)
from quant_lab.ai.gates import ResearchGate
from quant_lab.ai.packs import EvidencePackError, EvidencePackService
from quant_lab.ai.resolvers import DisallowedEvidenceField, EvidenceRequest
from quant_lab.ai.validation import ValidationService
from quant_lab.paper.models import PaperRiskDecisionModel

from .test_ai2_concrete_resolvers import KNOWN
from .test_ai2_concrete_resolvers import domain_registry as domain_registry
from .test_ai2_contract_closure import _candidate, _claim, _pack, _resolved_item


@pytest.mark.parametrize("unit", ["USD", "SHARES", None])
def test_fact_rejects_equal_value_in_different_unit(unit) -> None:
    item = _resolved_item()
    result = ValidationService().validate(
        _candidate([_claim(unit=unit)]), _pack(item), origin_attempt_id="unit"
    )
    assert not result.accepted
    assert "EVIDENCE_UNIT_MISMATCH" in result.error_codes


def test_unit_alias_remains_valid() -> None:
    item = _resolved_item()
    result = ValidationService().validate(
        _candidate([_claim(unit=" rmb ")]), _pack(item), origin_attempt_id="alias"
    )
    assert result.accepted


def test_stale_evidence_does_not_hide_future_knowledge_violation() -> None:
    item = _resolved_item().model_copy(update={"known_at": KNOWN + timedelta(days=100)})
    result = ValidationService().validate(
        _candidate([_claim()]),
        _pack(item),
        origin_attempt_id="future-and-stale",
        freshness_requirement=FreshnessRequirement.REALTIME_REQUIRED,
        reference_now=item.observed_at + timedelta(seconds=31),
    )
    assert "TEMPORAL_LEAK" in result.error_codes
    assert (
        ResearchGate()
        .decide(
            findings=result.findings,
            evidence_context=_pack().evidence_context,
            requirements=AnalysisRequirements(),
        )
        .decision
        is GateDecision.REJECT
    )


@pytest.mark.parametrize("predicate", ["DELTA", "PERCENT_CHANGE"])
def test_derived_operands_cannot_mix_currencies(predicate) -> None:
    first = _resolved_item()
    second = _resolved_item(unit="USD")
    result = ValidationService().validate(
        _candidate(
            [
                _claim(
                    predicate=predicate,
                    value="0",
                    unit="RATIO" if predicate == "PERCENT_CHANGE" else "CNY",
                    evidence_refs=[],
                    operand_refs=[first.ref_id, second.ref_id],
                )
            ]
        ),
        _pack(first, second),
        origin_attempt_id="derived-unit",
    )
    assert not result.accepted
    assert "EVIDENCE_UNIT_MISMATCH" in result.error_codes


@pytest.mark.parametrize(
    "claim_type,accepted", [("FACT", False), ("INFERENCE", False), ("HYPOTHESIS", True)]
)
def test_claim_type_evidence_requirements_are_explicit(claim_type, accepted) -> None:
    result = ValidationService().validate(
        _candidate([_claim(claim_type=claim_type, evidence_refs=[], value=None)]),
        _pack(),
        origin_attempt_id="claim-type",
    )
    assert result.accepted is accepted


@pytest.mark.parametrize(
    "code",
    [
        "SCHEMA_MISSING_FIELD",
        "SCHEMA_INVALID_TYPE",
        "SCHEMA_INVALID_ENUM",
        "USER_NOTE_CANNOT_SUPPORT_FACT",
    ],
)
def test_deterministic_errors_precede_missing_rules(code) -> None:
    result = ResearchGate().decide(
        findings=(
            ValidationFinding(
                layer=ValidationLayer.SCHEMA,
                code=code,
                severity=FindingSeverity.ERROR,
                message_safe=code,
                retryable=True,
            ),
        ),
        evidence_context=_pack().evidence_context,
        requirements=AnalysisRequirements(required_rule_topics=("LOT_SIZE",)),
    )
    assert result.decision is GateDecision.REJECT


def test_secret_text_in_allowlisted_context_is_rejected() -> None:
    payload = _resolved_item().model_dump(mode="python")
    payload["context"] = {"analysis_scope": "api_key=" + "x" * 24}
    with pytest.raises(ValidationError):
        CanonicalEvidenceItem.model_validate(payload)


def test_pack_rechecks_mutated_context_before_freezing() -> None:
    item = _resolved_item()
    item.context["analysis_scope"] = "api_key=" + "x" * 24
    pack = _pack(item)
    with pytest.raises(EvidencePackError, match="secret"):
        EvidencePackService._validate_item(item, pack.temporal_context, pack.evidence_context)


def test_risk_evaluated_metrics_are_the_persisted_domain_result(domain_registry) -> None:
    engine = domain_registry.get(EvidenceSourceType.RISK_DECISION)._loader.__self__.engine
    with Session(engine) as session:
        decision = session.get(PaperRiskDecisionModel, "rd1")
        decision.market_context_json = '{"evaluated_metrics":{"projected_exposure_ratio":"0.2"}}'
        session.commit()
    item = domain_registry.resolve(
        EvidenceRequest(
            source_type=EvidenceSourceType.RISK_DECISION,
            source_id="rd1",
            fields=("evaluated_metrics",),
        )
    )[0]
    assert item.value == {"projected_exposure_ratio": "0.2"}


@pytest.mark.parametrize("source_type", list(EvidenceSourceType))
def test_every_concrete_resolver_checks_field_allowlist_before_loading(
    domain_registry, source_type
) -> None:
    with pytest.raises(DisallowedEvidenceField):
        domain_registry.resolve(
            EvidenceRequest(source_type=source_type, source_id="missing", fields=("apiKey",))
        )


@pytest.mark.parametrize("reason", ["DAILY_LOSS_LIMIT", "DRAWDOWN_LIMIT"])
def test_risk_freeze_projection_uses_formal_reason_codes(domain_registry, reason) -> None:
    engine = domain_registry.get(EvidenceSourceType.RISK_DECISION)._loader.__self__.engine
    with Session(engine) as session:
        decision = session.get(PaperRiskDecisionModel, "rd1")
        decision.reason_codes_json = f'["{reason}"]'
        session.commit()
    item = domain_registry.resolve(
        EvidenceRequest(
            source_type=EvidenceSourceType.RISK_DECISION,
            source_id="rd1",
            fields=("freeze_required",),
        )
    )[0]
    assert item.value is True


def test_money_resolver_uses_actual_account_currency(domain_registry) -> None:
    item = domain_registry.resolve(
        EvidenceRequest(
            source_type=EvidenceSourceType.PAPER_ACCOUNT_SNAPSHOT,
            source_id="pas1",
            fields=("cash",),
        )
    )[0]
    assert item.unit == "CNY"


@pytest.mark.parametrize(
    "source_type", [EvidenceSourceType.RESEARCH_EXPERIMENT, EvidenceSourceType.RESEARCH_COMPARISON]
)
def test_mutable_research_projection_uses_system_observation_time(
    domain_registry, source_type
) -> None:
    loader = domain_registry.get(source_type)._loader.__self__
    observed = KNOWN + timedelta(days=100)
    loader.clock = lambda: observed
    item = domain_registry.resolve(EvidenceRequest(source_type=source_type, source_id="exp1"))[0]
    assert item.known_at == observed
    assert item.observed_at == observed


def test_report_evidence_fingerprint_excludes_deferred_journal(domain_registry) -> None:
    resolver = domain_registry.get(EvidenceSourceType.RESEARCH_REPORT)
    request = EvidenceRequest(source_type=EvidenceSourceType.RESEARCH_REPORT, source_id="run1")
    before = resolver.resolve(request)
    resolver._loader.__self__.research.create_journal_entry(
        title="Later note",
        entry_type="OBSERVATION",
        content="Unverified prose",
        tags=[],
        experiment_id=None,
        backtest_run_id="run1",
        strategy_version_id=None,
    )
    after = resolver.resolve(request)
    assert [item.ref_id for item in after] == [item.ref_id for item in before]
    assert [item.source_fingerprint for item in after] == [
        item.source_fingerprint for item in before
    ]
