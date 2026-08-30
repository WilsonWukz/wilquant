from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation

from pydantic import ValidationError

from quant_lab.ai.contracts import (
    AcceptedAssertion,
    AssertionObservation,
    CanonicalEvidenceItem,
    ClaimPredicate,
    ClaimType,
    EvidenceClassification,
    EvidencePack,
    EvidenceScalar,
    FindingSeverity,
    StructuredCandidate,
    StructuredClaim,
    ValidationDisposition,
    ValidationFinding,
    ValidationLayer,
    ValidationResult,
)
from quant_lab.ai.fingerprints import fingerprint_payload
from quant_lab.ai.policies import AI2_POLICY, AI2Policy

ALLOWED_ACTION_TYPES = frozenset({"RESEARCH_ANALYSIS", "RESEARCH_DIAGNOSIS"})
_CLAIM_KEYS = frozenset(
    {
        "claim_id",
        "claim_type",
        "subject",
        "predicate",
        "value",
        "unit",
        "evidence_refs",
        "operand_refs",
    }
)


def _canonical_unit(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = "".join(
        character
        for character in value.upper()
        if character.isalnum() or character == "%"
    )
    aliases = {
        "%": "PERCENT",
        "PERCENT": "PERCENT",
        "PERCENTAGE": "PERCENT",
        "RATIO": "RATIO",
        "CNY": "CNY",
        "RMB": "CNY",
        "USD": "USD",
        "SHARE": "SHARES",
        "SHARES": "SHARES",
        "COUNT": "COUNT",
    }
    return aliases.get(normalized, normalized)


def _item_map(pack: EvidencePack) -> dict[str, CanonicalEvidenceItem]:
    return {item.ref: item for item in pack.items}


def _canonical_subject(
    claim: StructuredClaim,
    pack: EvidencePack,
    subject_aliases: Mapping[str, str],
) -> str:
    items = _item_map(pack)
    referenced = [
        items[ref].subject
        for ref in [*claim.evidence_refs, *claim.operand_refs]
        if ref in items
    ]
    if referenced and len(set(referenced)) == 1:
        return referenced[0]
    normalized = claim.subject.strip()
    return subject_aliases.get(normalized, normalized)


def assertion_identity(
    claim: StructuredClaim,
    pack: EvidencePack,
    subject_aliases: Mapping[str, str] | None = None,
) -> str:
    aliases = subject_aliases or {}
    payload = {
        "claim_type": claim.claim_type,
        "subject": _canonical_subject(claim, pack, aliases),
        "predicate": claim.predicate,
        "evidence_refs": sorted(set(claim.evidence_refs)),
        "unit": _canonical_unit(claim.unit),
        "derived_operation": claim.predicate
        if claim.predicate in {ClaimPredicate.DELTA, ClaimPredicate.PERCENT_CHANGE}
        else None,
        "operand_refs": list(claim.operand_refs),
    }
    return fingerprint_payload(payload)


def _drift_group(
    *,
    claim_type: str,
    subject: str,
    predicate: str,
    unit: str | None,
    evidence_refs: Sequence[str],
    operand_refs: Sequence[str],
) -> str:
    return fingerprint_payload(
        {
            "claim_type": claim_type,
            "subject": subject,
            "predicate": predicate,
            "unit": _canonical_unit(unit),
            "evidence_refs": sorted(set(evidence_refs)),
            "operand_set": sorted(operand_refs),
        }
    )


def _decimal(value: EvidenceScalar) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise InvalidOperation
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _values_equal(
    left: EvidenceScalar,
    right: EvidenceScalar,
    unit: str | None,
    policy: AI2Policy,
) -> bool:
    try:
        left_number = _decimal(left)
        right_number = _decimal(right)
    except (InvalidOperation, ValueError):
        return left == right
    canonical_unit = _canonical_unit(unit)
    if canonical_unit in {"CNY", "USD"}:
        tolerance = policy.money_tolerance
    elif canonical_unit == "COUNT":
        tolerance = policy.count_tolerance
    elif canonical_unit in {"RATIO", "PERCENT"}:
        tolerance = max(
            policy.ratio_absolute_tolerance,
            abs(right_number) * policy.ratio_relative_tolerance,
        )
    else:
        tolerance = max(
            policy.number_absolute_tolerance,
            abs(right_number) * policy.number_relative_tolerance,
        )
    return abs(left_number - right_number) <= tolerance


def _finding(
    layer: ValidationLayer,
    code: str,
    *,
    retryable: bool,
    claim_id: str | None = None,
    evidence_ref: str | None = None,
) -> ValidationFinding:
    return ValidationFinding(
        layer=layer,
        code=code,
        severity=FindingSeverity.ERROR,
        message_safe=code,
        retryable=retryable,
        claim_id=claim_id,
        evidence_ref=evidence_ref,
    )


class ValidationService:
    def __init__(
        self,
        *,
        policy: AI2Policy = AI2_POLICY,
        subject_aliases: Mapping[str, str] | None = None,
    ) -> None:
        self.policy = policy
        self.subject_aliases = dict(subject_aliases or {})

    @staticmethod
    def parse_claim(value: Mapping[str, object]) -> StructuredClaim:
        return StructuredClaim.model_validate(value)

    def _observation(
        self,
        value: object,
        pack: EvidencePack,
        origin_attempt_id: str,
    ) -> AssertionObservation | None:
        if not isinstance(value, Mapping):
            return None
        sanitized = {key: item for key, item in value.items() if key in _CLAIM_KEYS}
        sanitized.setdefault("evidence_refs", [])
        sanitized.setdefault("operand_refs", [])
        try:
            claim = StructuredClaim.model_validate(sanitized)
        except ValidationError:
            return None
        subject = _canonical_subject(claim, pack, self.subject_aliases)
        return AssertionObservation(
            assertion_identity=assertion_identity(claim, pack, self.subject_aliases),
            claim_type=claim.claim_type.value,
            subject=subject,
            predicate=claim.predicate.value,
            value=claim.value,
            unit=_canonical_unit(claim.unit),
            evidence_refs=tuple(sorted(set(claim.evidence_refs))),
            operand_refs=claim.operand_refs,
            origin_attempt_id=origin_attempt_id,
            trusted=False,
        )

    @staticmethod
    def _result(
        *,
        findings: Sequence[ValidationFinding],
        accepted: Sequence[AcceptedAssertion],
        observations: Sequence[AssertionObservation],
        candidate_fingerprint: str,
        policy_version: str,
    ) -> ValidationResult:
        has_error = any(
            finding.severity is FindingSeverity.ERROR for finding in findings
        )
        return ValidationResult(
            disposition=(
                ValidationDisposition.REJECTED
                if has_error
                else ValidationDisposition.ACCEPTED
            ),
            findings=tuple(findings),
            accepted_assertions=() if has_error else tuple(accepted),
            observations=tuple(observations),
            candidate_fingerprint=candidate_fingerprint,
            policy_version=policy_version,
        )

    def validate(
        self,
        candidate: str | bytes | Mapping[str, object],
        pack: EvidencePack,
        *,
        origin_attempt_id: str,
        prior_assertions: Sequence[AcceptedAssertion | AssertionObservation] = (),
    ) -> ValidationResult:
        findings: list[ValidationFinding] = []
        observations: list[AssertionObservation] = []
        raw_fingerprint = fingerprint_payload(
            candidate.decode("utf-8", errors="replace")
            if isinstance(candidate, bytes)
            else candidate
        )
        if isinstance(candidate, bytes | str):
            try:
                parsed = json.loads(candidate)
            except (json.JSONDecodeError, UnicodeDecodeError):
                findings.append(
                    _finding(ValidationLayer.SYNTAX, "SYNTAX_INVALID", retryable=True)
                )
                return self._result(
                    findings=findings,
                    accepted=(),
                    observations=(),
                    candidate_fingerprint=raw_fingerprint,
                    policy_version=self.policy.validation_policy_version,
                )
        else:
            parsed = dict(candidate)
        try:
            structured = StructuredCandidate.model_validate(parsed)
        except ValidationError:
            claims = parsed.get("claims", []) if isinstance(parsed, Mapping) else []
            if isinstance(claims, list | tuple):
                observations.extend(
                    observation
                    for value in claims
                    if (observation := self._observation(value, pack, origin_attempt_id))
                    is not None
                )
            findings.append(_finding(ValidationLayer.SCHEMA, "SCHEMA_INVALID", retryable=True))
            return self._result(
                findings=findings,
                accepted=(),
                observations=observations,
                candidate_fingerprint=raw_fingerprint,
                policy_version=self.policy.validation_policy_version,
            )

        if structured.action_type not in ALLOWED_ACTION_TYPES:
            findings.append(
                _finding(
                    ValidationLayer.SEMANTIC,
                    "FORBIDDEN_AI_AUTHORITY",
                    retryable=False,
                )
            )

        items = _item_map(pack)
        accepted: list[AcceptedAssertion] = []
        candidate_claims: list[tuple[StructuredClaim, str, EvidenceScalar]] = []
        for claim in structured.claims:
            derived = claim.predicate in {
                ClaimPredicate.DELTA,
                ClaimPredicate.PERCENT_CHANGE,
            }
            if claim.claim_type is ClaimType.FACT and not (
                claim.evidence_refs or claim.operand_refs
            ):
                findings.append(
                    _finding(
                        ValidationLayer.SEMANTIC,
                        "FACT_EVIDENCE_REQUIRED",
                        retryable=True,
                        claim_id=claim.claim_id,
                    )
                )
                continue
            if claim.claim_type is ClaimType.INFERENCE and not claim.evidence_refs:
                findings.append(
                    _finding(
                        ValidationLayer.SEMANTIC,
                        "INFERENCE_EVIDENCE_REQUIRED",
                        retryable=True,
                        claim_id=claim.claim_id,
                    )
                )
                continue
            if derived and len(claim.operand_refs) != 2:
                findings.append(
                    _finding(
                        ValidationLayer.SEMANTIC,
                        "DERIVED_OPERANDS_INVALID",
                        retryable=True,
                        claim_id=claim.claim_id,
                    )
                )
                continue

            all_refs = tuple([*claim.evidence_refs, *claim.operand_refs])
            missing = tuple(ref for ref in all_refs if ref not in items)
            if missing:
                findings.extend(
                    _finding(
                        ValidationLayer.GROUNDING,
                        "FABRICATED_EVIDENCE_REF",
                        retryable=False,
                        claim_id=claim.claim_id,
                        evidence_ref=ref,
                    )
                    for ref in sorted(set(missing))
                )
                continue
            if claim.claim_type is ClaimType.FACT and any(
                items[ref].classification is EvidenceClassification.USER_NOTE
                for ref in all_refs
            ):
                findings.append(
                    _finding(
                        ValidationLayer.GROUNDING,
                        "USER_NOTE_CANNOT_SUPPORT_FACT",
                        retryable=False,
                        claim_id=claim.claim_id,
                    )
                )
                continue

            grounded_value: EvidenceScalar = claim.value
            if derived:
                try:
                    left = _decimal(items[claim.operand_refs[0]].value)
                    right = _decimal(items[claim.operand_refs[1]].value)
                    if claim.predicate is ClaimPredicate.DELTA:
                        grounded_value = left - right
                    elif right == 0:
                        findings.append(
                            _finding(
                                ValidationLayer.GROUNDING,
                                "DERIVED_ZERO_DENOMINATOR",
                                retryable=False,
                                claim_id=claim.claim_id,
                            )
                        )
                        continue
                    else:
                        grounded_value = (left - right) / right
                except (InvalidOperation, ValueError):
                    findings.append(
                        _finding(
                            ValidationLayer.GROUNDING,
                            "DERIVED_OPERAND_NOT_NUMERIC",
                            retryable=False,
                            claim_id=claim.claim_id,
                        )
                    )
                    continue
                if not _values_equal(claim.value, grounded_value, claim.unit, self.policy):
                    findings.append(
                        _finding(
                            ValidationLayer.GROUNDING,
                            "GROUNDING_CONTRADICTION",
                            retryable=False,
                            claim_id=claim.claim_id,
                        )
                    )
            elif claim.claim_type is ClaimType.FACT:
                if any(
                    not _values_equal(claim.value, items[ref].value, claim.unit, self.policy)
                    for ref in claim.evidence_refs
                ):
                    findings.append(
                        _finding(
                            ValidationLayer.GROUNDING,
                            "GROUNDING_CONTRADICTION",
                            retryable=False,
                            claim_id=claim.claim_id,
                        )
                    )
                else:
                    try:
                        grounded_value = _decimal(claim.value)
                    except (InvalidOperation, ValueError):
                        grounded_value = claim.value

            for ref in all_refs:
                item = items[ref]
                if (
                    item.known_at > pack.temporal_context.knowledge_cutoff
                    or item.effective_at > pack.temporal_context.market_data_cutoff
                ):
                    findings.append(
                        _finding(
                            ValidationLayer.TEMPORAL,
                            "TEMPORAL_LEAK",
                            retryable=False,
                            claim_id=claim.claim_id,
                            evidence_ref=ref,
                        )
                    )
            subject = _canonical_subject(claim, pack, self.subject_aliases)
            candidate_claims.append((claim, subject, grounded_value))
            accepted.append(
                AcceptedAssertion(
                    assertion_identity=assertion_identity(
                        claim, pack, self.subject_aliases
                    ),
                    claim_id=claim.claim_id,
                    claim_type=claim.claim_type,
                    subject=subject,
                    predicate=claim.predicate,
                    value=grounded_value,
                    unit=_canonical_unit(claim.unit),
                    evidence_refs=tuple(sorted(set(claim.evidence_refs))),
                    operand_refs=claim.operand_refs,
                )
            )

        prior_by_group = {
            _drift_group(
                claim_type=str(prior.claim_type),
                subject=prior.subject,
                predicate=str(prior.predicate),
                unit=prior.unit,
                evidence_refs=prior.evidence_refs,
                operand_refs=prior.operand_refs,
            ): prior
            for prior in prior_assertions
        }
        for claim, subject, _grounded in candidate_claims:
            group = _drift_group(
                claim_type=claim.claim_type.value,
                subject=subject,
                predicate=claim.predicate.value,
                unit=claim.unit,
                evidence_refs=claim.evidence_refs,
                operand_refs=claim.operand_refs,
            )
            prior = prior_by_group.get(group)
            if prior is None:
                continue
            if prior.operand_refs != claim.operand_refs or not _values_equal(
                prior.value, claim.value, claim.unit, self.policy
            ):
                findings.append(
                    _finding(
                        ValidationLayer.IMMUTABLE_FACT,
                        "IMMUTABLE_FACT_DRIFT",
                        retryable=False,
                        claim_id=claim.claim_id,
                    )
                )

        return self._result(
            findings=findings,
            accepted=accepted,
            observations=observations,
            candidate_fingerprint=raw_fingerprint,
            policy_version=self.policy.validation_policy_version,
        )
