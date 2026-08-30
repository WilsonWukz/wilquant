from __future__ import annotations

from quant_lab.ai.contracts import (
    AnalysisRequirements,
    EvidenceContext,
    FindingSeverity,
    GateDecision,
    ValidationFinding,
    ValidationLayer,
)
from quant_lab.ai.gates import ResearchGate


def _finding(code: str) -> ValidationFinding:
    return ValidationFinding(
        layer=ValidationLayer.TEMPORAL,
        code=code,
        severity=FindingSeverity.ERROR,
        message_safe=code,
        retryable=False,
    )


def _context(rules: str | None = None) -> EvidenceContext:
    return EvidenceContext(
        market="CN_A_SHARE",
        instrument_id="SSE:600000",
        asset_type="EQUITY",
        timezone="Asia/Shanghai",
        market_rules_version=rules,
    )


def test_gate_uses_fixed_precedence_independent_of_finding_order() -> None:
    findings = (
        _finding("NOT_COMPARABLE"),
        _finding("INSUFFICIENT_EVIDENCE"),
        _finding("IMMUTABLE_FACT_DRIFT"),
    )

    result = ResearchGate().decide(
        findings=tuple(reversed(findings)),
        evidence_context=_context(),
        requirements=AnalysisRequirements(),
    )

    assert result.decision is GateDecision.REJECT
    assert result.reason_codes[0] == "IMMUTABLE_FACT_DRIFT"


def test_gate_maps_missing_or_stale_to_wait_and_unanswerable_to_abstain() -> None:
    gate = ResearchGate()

    wait = gate.decide(
        findings=(_finding("STALE_MARKET_DATA"),),
        evidence_context=_context(),
        requirements=AnalysisRequirements(),
    )
    abstain = gate.decide(
        findings=(_finding("NOT_COMPARABLE"),),
        evidence_context=_context(),
        requirements=AnalysisRequirements(),
    )

    assert wait.decision is GateDecision.WAIT_FOR_EVIDENCE
    assert abstain.decision is GateDecision.ABSTAIN


def test_missing_market_rules_only_blocks_rule_dependent_analysis() -> None:
    gate = ResearchGate()

    independent = gate.decide(
        findings=(),
        evidence_context=_context(),
        requirements=AnalysisRequirements(),
    )
    dependent = gate.decide(
        findings=(),
        evidence_context=_context(),
        requirements=AnalysisRequirements(required_rule_topics=("LOT_SIZE",)),
    )

    assert independent.decision is GateDecision.PROCEED
    assert dependent.decision is GateDecision.WAIT_FOR_EVIDENCE
    assert dependent.reason_codes == ("MISSING_MARKET_RULES",)


def test_rules_dependent_analysis_proceeds_with_compatible_rules() -> None:
    result = ResearchGate().decide(
        findings=(),
        evidence_context=_context("cn-a-v1"),
        requirements=AnalysisRequirements(required_rule_topics=("SELLABILITY",)),
    )

    assert result.decision is GateDecision.PROCEED
    assert result.reason_codes == ("PROCEED",)
