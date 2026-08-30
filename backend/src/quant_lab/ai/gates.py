from __future__ import annotations

from collections.abc import Sequence

from quant_lab.ai.contracts import (
    AnalysisRequirements,
    EvidenceContext,
    FindingSeverity,
    GateDecision,
    GateResult,
    ValidationFinding,
)

REASON_ORDER = (
    "FORBIDDEN_AI_AUTHORITY",
    "IMMUTABLE_FACT_DRIFT",
    "FABRICATED_EVIDENCE_REF",
    "GROUNDING_CONTRADICTION",
    "TEMPORAL_LEAK",
    "FUTURE_KNOWLEDGE",
    "FUTURE_MARKET_DATA",
    "INVALID_EVIDENCE",
    "MARKET_MISMATCH",
    "ASSET_TYPE_MISMATCH",
    "INSTRUMENT_MISMATCH",
    "CURRENCY_MISMATCH",
    "MARKET_RULES_MISMATCH",
    "MISSING_MARKET_RULES",
    "INSUFFICIENT_EVIDENCE",
    "STALE_MARKET_DATA",
    "NOT_COMPARABLE",
    "FUNDAMENTALLY_UNANSWERABLE",
    "PROCEED",
)

DETERMINISTIC_VIOLATIONS = frozenset(REASON_ORDER[:13])
MISSING_OR_STALE = frozenset(
    {"MISSING_MARKET_RULES", "INSUFFICIENT_EVIDENCE", "STALE_MARKET_DATA"}
)
UNANSWERABLE = frozenset({"NOT_COMPARABLE", "FUNDAMENTALLY_UNANSWERABLE"})


def _ordered(codes: set[str]) -> tuple[str, ...]:
    known = [code for code in REASON_ORDER if code in codes]
    unknown = sorted(codes - set(REASON_ORDER))
    return tuple([*known, *unknown])


class ResearchGate:
    def decide(
        self,
        *,
        findings: Sequence[ValidationFinding],
        evidence_context: EvidenceContext,
        requirements: AnalysisRequirements,
    ) -> GateResult:
        codes = {
            finding.code
            for finding in findings
            if finding.severity is FindingSeverity.ERROR
        }
        if requirements.market_rules_required and evidence_context.market_rules_version is None:
            codes.add("MISSING_MARKET_RULES")
        if codes & DETERMINISTIC_VIOLATIONS:
            return GateResult(decision=GateDecision.REJECT, reason_codes=_ordered(codes))
        if codes & MISSING_OR_STALE:
            return GateResult(
                decision=GateDecision.WAIT_FOR_EVIDENCE, reason_codes=_ordered(codes)
            )
        if codes & UNANSWERABLE:
            return GateResult(decision=GateDecision.ABSTAIN, reason_codes=_ordered(codes))
        if codes:
            return GateResult(decision=GateDecision.REJECT, reason_codes=_ordered(codes))
        return GateResult(decision=GateDecision.PROCEED, reason_codes=("PROCEED",))
