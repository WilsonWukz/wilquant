from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Protocol
from uuid import uuid4

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
    EvidenceSemanticType,
    FindingSeverity,
    FreshnessClass,
    FreshnessRequirement,
    StructuredCandidate,
    StructuredClaim,
    ValidationDisposition,
    ValidationFinding,
    ValidationLayer,
    ValidationResult,
    canonical_unit,
)
from quant_lab.ai.fingerprints import fingerprint_payload
from quant_lab.ai.persistence import AIValidationResultModel
from quant_lab.ai.policies import AI2_POLICY, AI2Policy
from quant_lab.market_data.fingerprints import canonical_json_bytes

ALLOWED_ACTION_TYPES = frozenset(
    {
        "RESEARCH_RECOMMENDATION",
        "EXPERIMENT_DRAFT",
        "JOURNAL_DRAFT",
        "THESIS_REVISION_DRAFT",
    }
)
ALLOWED_RECOMMENDATIONS = frozenset(
    {
        "CREATE_EXPERIMENT_DRAFT",
        "ADD_RESEARCH_JOURNAL_DRAFT",
        "CREATE_THESIS_REVISION_DRAFT",
        "WAIT_FOR_MORE_DATA",
        "REVIEW_STRATEGY",
        "REVIEW_PAPER_RESULTS",
    }
)
_CLAIM_KEYS = frozenset(
    {
        "claim_id",
        "claim_type",
        "text",
        "subject",
        "predicate",
        "value",
        "unit",
        "evidence_refs",
        "operand_refs",
        "uncertainty",
        "recommendation",
    }
)


def _canonical_unit(value: str | None) -> str | None:
    return canonical_unit(value)


def _item_map(pack: EvidencePack) -> dict[str, CanonicalEvidenceItem]:
    return {item.ref: item for item in pack.items}


def _canonical_subject(
    claim: StructuredClaim,
    pack: EvidencePack,
    subject_aliases: Mapping[str, str],
) -> str:
    items = _item_map(pack)
    referenced = [
        items[ref].subject for ref in [*claim.evidence_refs, *claim.operand_refs] if ref in items
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
    semantic_type: EvidenceSemanticType,
    policy: AI2Policy,
) -> bool:
    if semantic_type in {
        EvidenceSemanticType.TEXT,
        EvidenceSemanticType.ENUM,
        EvidenceSemanticType.BOOLEAN,
        EvidenceSemanticType.IDENTIFIER,
        EvidenceSemanticType.JSON,
        EvidenceSemanticType.DATETIME,
    }:
        return left == right
    try:
        left_number = _decimal(left)
        right_number = _decimal(right)
    except (InvalidOperation, ValueError):
        return left == right
    if semantic_type is EvidenceSemanticType.MONEY:
        tolerance = policy.money_tolerance
    elif semantic_type is EvidenceSemanticType.COUNT:
        tolerance = policy.count_tolerance
    elif semantic_type is EvidenceSemanticType.RATIO:
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
    field_path: str | None = None,
) -> ValidationFinding:
    return ValidationFinding(
        layer=layer,
        code=code,
        severity=FindingSeverity.ERROR,
        message_safe=code,
        retryable=retryable,
        claim_id=claim_id,
        evidence_ref=evidence_ref,
        field_path=field_path,
    )


def _schema_field_path(location: Sequence[str | int]) -> str:
    output = ""
    for part in location:
        if isinstance(part, int):
            output += f"[{part}]"
        elif output:
            output += f".{part}"
        else:
            output = str(part)
    return output or "$"


def _schema_findings(error: ValidationError) -> tuple[ValidationFinding, ...]:
    findings: list[ValidationFinding] = []
    for detail in error.errors(include_url=False, include_context=False, include_input=False):
        kind = str(detail["type"])
        if kind == "missing":
            code = "SCHEMA_MISSING_FIELD"
        elif kind in {"enum", "literal_error"}:
            code = "SCHEMA_INVALID_ENUM"
        else:
            code = "SCHEMA_INVALID_TYPE"
        findings.append(
            _finding(
                ValidationLayer.SCHEMA,
                code,
                retryable=True,
                field_path=_schema_field_path(detail["loc"]),
            )
        )
    return tuple(findings)


_ORDERED_SEMANTIC_TYPES = frozenset(
    {
        EvidenceSemanticType.NUMBER,
        EvidenceSemanticType.MONEY,
        EvidenceSemanticType.RATIO,
        EvidenceSemanticType.COUNT,
        EvidenceSemanticType.DATETIME,
    }
)


def _ordered_value(
    value: EvidenceScalar, semantic_type: EvidenceSemanticType
) -> Decimal | datetime:
    if semantic_type is EvidenceSemanticType.DATETIME:
        if isinstance(value, datetime):
            parsed = value
        elif isinstance(value, str):
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        else:
            raise ValueError("datetime evidence is not comparable")
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("datetime evidence must be timezone-aware")
        return parsed.astimezone(UTC)
    return _decimal(value)


def _predicate_matches(
    *,
    predicate: ClaimPredicate,
    actual: EvidenceScalar,
    expected: EvidenceScalar,
    semantic_type: EvidenceSemanticType,
    policy: AI2Policy,
) -> bool:
    equal = _values_equal(actual, expected, semantic_type, policy)
    if predicate is ClaimPredicate.EQ:
        return equal
    if predicate is ClaimPredicate.NE:
        return not equal
    if semantic_type not in _ORDERED_SEMANTIC_TYPES:
        raise TypeError("semantic predicate is not supported")
    left = _ordered_value(actual, semantic_type)
    right = _ordered_value(expected, semantic_type)
    if semantic_type is EvidenceSemanticType.DATETIME:
        if not isinstance(left, datetime) or not isinstance(right, datetime):
            raise TypeError("datetime predicate operands are invalid")
        if predicate is ClaimPredicate.GT:
            return left > right
        if predicate is ClaimPredicate.GTE:
            return left > right or equal
        if predicate is ClaimPredicate.LT:
            return left < right
        if predicate is ClaimPredicate.LTE:
            return left < right or equal
    else:
        if not isinstance(left, Decimal) or not isinstance(right, Decimal):
            raise TypeError("numeric predicate operands are invalid")
        if predicate is ClaimPredicate.GT:
            return left > right
        if predicate is ClaimPredicate.GTE:
            return left > right or equal
        if predicate is ClaimPredicate.LT:
            return left < right
        if predicate is ClaimPredicate.LTE:
            return left < right or equal
    raise TypeError("predicate is not a direct comparison")


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
        sanitized.setdefault("text", "schema-invalid observation")
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
        has_error = any(finding.severity is FindingSeverity.ERROR for finding in findings)
        return ValidationResult(
            disposition=(
                ValidationDisposition.REJECTED if has_error else ValidationDisposition.ACCEPTED
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
        freshness_requirement: FreshnessRequirement = FreshnessRequirement.HISTORICAL_OK,
        reference_now: datetime | None = None,
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
                findings.append(_finding(ValidationLayer.SYNTAX, "SYNTAX_INVALID", retryable=True))
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
        except ValidationError as error:
            claims = parsed.get("claims", []) if isinstance(parsed, Mapping) else []
            if isinstance(claims, list | tuple):
                observations.extend(
                    observation
                    for value in claims
                    if (observation := self._observation(value, pack, origin_attempt_id))
                    is not None
                )
            findings.extend(_schema_findings(error))
            return self._result(
                findings=findings,
                accepted=(),
                observations=observations,
                candidate_fingerprint=raw_fingerprint,
                policy_version=self.policy.validation_policy_version,
            )

        recommendations = {
            value
            for value in (
                structured.recommendation,
                *(claim.recommendation for claim in structured.claims),
            )
            if value is not None
        }
        if (
            structured.action_type not in ALLOWED_ACTION_TYPES
            or not recommendations <= ALLOWED_RECOMMENDATIONS
        ):
            findings.append(
                _finding(
                    ValidationLayer.SEMANTIC,
                    "FORBIDDEN_AI_AUTHORITY",
                    retryable=False,
                )
            )

        claim_ids = [claim.claim_id for claim in structured.claims]
        duplicate_ids = sorted(
            claim_id for claim_id in set(claim_ids) if claim_ids.count(claim_id) > 1
        )
        findings.extend(
            _finding(
                ValidationLayer.SCHEMA,
                "DUPLICATE_CLAIM_ID",
                retryable=True,
                claim_id=claim_id,
                field_path="claims",
            )
            for claim_id in duplicate_ids
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
                claim.operand_refs if derived else claim.evidence_refs
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
                        "EVIDENCE_REF_NOT_FOUND",
                        retryable=False,
                        claim_id=claim.claim_id,
                        evidence_ref=ref,
                    )
                    for ref in sorted(set(missing))
                )
                continue
            if derived or claim.claim_type is ClaimType.FACT:
                compared = [
                    items[ref] for ref in (claim.operand_refs if derived else claim.evidence_refs)
                ]
                units = {_canonical_unit(item.unit) for item in compared}
                expected_unit = (
                    "RATIO"
                    if claim.predicate is ClaimPredicate.PERCENT_CHANGE
                    else _canonical_unit(compared[0].unit)
                )
                if len(units) != 1 or _canonical_unit(claim.unit) != expected_unit:
                    findings.append(
                        _finding(
                            ValidationLayer.GROUNDING,
                            "EVIDENCE_UNIT_MISMATCH",
                            retryable=False,
                            claim_id=claim.claim_id,
                        )
                    )
                    continue
            freshness_findings: list[ValidationFinding] = []
            for ref in sorted(set(all_refs)):
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
                acceptable = {
                    FreshnessRequirement.HISTORICAL_OK: set(FreshnessClass),
                    FreshnessRequirement.EOD_REQUIRED: {
                        FreshnessClass.EOD,
                        FreshnessClass.REALTIME,
                    },
                    FreshnessRequirement.DELAYED_OK: {
                        FreshnessClass.EOD,
                        FreshnessClass.DELAYED,
                        FreshnessClass.REALTIME,
                    },
                    FreshnessRequirement.REALTIME_REQUIRED: {FreshnessClass.REALTIME},
                }[freshness_requirement]
                if item.freshness_class not in acceptable:
                    freshness_findings.append(
                        _finding(
                            ValidationLayer.TEMPORAL,
                            "STALE_MARKET_DATA",
                            retryable=True,
                            claim_id=claim.claim_id,
                            evidence_ref=ref,
                        )
                    )
                    continue
                if freshness_requirement is FreshnessRequirement.REALTIME_REQUIRED:
                    if item.observed_at is None:
                        freshness_findings.append(
                            _finding(
                                ValidationLayer.TEMPORAL,
                                "TEMPORAL_METADATA_UNAVAILABLE",
                                retryable=True,
                                claim_id=claim.claim_id,
                                evidence_ref=ref,
                            )
                        )
                        continue
                    if reference_now is None:
                        raise ValueError(
                            "reference_now is required for realtime freshness validation"
                        )
                    if reference_now.tzinfo is None or reference_now.utcoffset() is None:
                        raise ValueError("reference_now must be timezone-aware")
                    age_seconds = (reference_now.astimezone(UTC) - item.observed_at).total_seconds()
                    if age_seconds > self.policy.realtime_max_age_seconds:
                        freshness_findings.append(
                            _finding(
                                ValidationLayer.TEMPORAL,
                                "STALE_MARKET_DATA",
                                retryable=True,
                                claim_id=claim.claim_id,
                                evidence_ref=ref,
                            )
                        )
            if freshness_findings:
                findings.extend(freshness_findings)
                continue
            if claim.claim_type is ClaimType.FACT and any(
                items[ref].classification is EvidenceClassification.USER_NOTE for ref in all_refs
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
                    first_item = items[claim.operand_refs[0]]
                    second_item = items[claim.operand_refs[1]]
                    if (
                        first_item.semantic_type not in _ORDERED_SEMANTIC_TYPES
                        or second_item.semantic_type not in _ORDERED_SEMANTIC_TYPES
                        or first_item.semantic_type is EvidenceSemanticType.DATETIME
                        or second_item.semantic_type is EvidenceSemanticType.DATETIME
                    ):
                        raise ValueError("derived operands must be numeric")
                    first = _decimal(first_item.value)
                    second = _decimal(second_item.value)
                    if claim.predicate is ClaimPredicate.DELTA:
                        grounded_value = first - second
                    elif first == 0:
                        findings.append(
                            _finding(
                                ValidationLayer.GROUNDING,
                                "DERIVED_DIVISION_BY_ZERO",
                                retryable=False,
                                claim_id=claim.claim_id,
                            )
                        )
                        continue
                    else:
                        grounded_value = (second - first) / abs(first)
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
                result_semantic_type = (
                    EvidenceSemanticType.RATIO
                    if claim.predicate is ClaimPredicate.PERCENT_CHANGE
                    else first_item.semantic_type
                )
                if not _values_equal(
                    claim.value, grounded_value, result_semantic_type, self.policy
                ):
                    findings.append(
                        _finding(
                            ValidationLayer.GROUNDING,
                            "EVIDENCE_VALUE_MISMATCH",
                            retryable=False,
                            claim_id=claim.claim_id,
                        )
                    )
            elif claim.claim_type is ClaimType.FACT:
                predicate_error = False
                for ref in claim.evidence_refs:
                    item = items[ref]
                    try:
                        matches = _predicate_matches(
                            predicate=claim.predicate,
                            actual=item.value,
                            expected=claim.value,
                            semantic_type=item.semantic_type,
                            policy=self.policy,
                        )
                    except (TypeError, ValueError, InvalidOperation):
                        findings.append(
                            _finding(
                                ValidationLayer.SEMANTIC,
                                "SEMANTIC_PREDICATE_NOT_SUPPORTED",
                                retryable=False,
                                claim_id=claim.claim_id,
                                evidence_ref=ref,
                            )
                        )
                        predicate_error = True
                        continue
                    if not matches:
                        predicate_error = True
                        findings.append(
                            _finding(
                                ValidationLayer.GROUNDING,
                                "EVIDENCE_VALUE_MISMATCH",
                                retryable=False,
                                claim_id=claim.claim_id,
                                evidence_ref=ref,
                            )
                        )
                if predicate_error:
                    pass
                else:
                    try:
                        grounded_value = _decimal(claim.value)
                    except (InvalidOperation, ValueError):
                        grounded_value = claim.value

            subject = _canonical_subject(claim, pack, self.subject_aliases)
            candidate_claims.append((claim, subject, grounded_value))
            accepted.append(
                AcceptedAssertion(
                    assertion_identity=assertion_identity(claim, pack, self.subject_aliases),
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
            semantic_type = (
                items[claim.operand_refs[0]].semantic_type
                if claim.operand_refs and claim.operand_refs[0] in items
                else items[claim.evidence_refs[0]].semantic_type
                if claim.evidence_refs and claim.evidence_refs[0] in items
                else EvidenceSemanticType.NUMBER
            )
            if prior.operand_refs != claim.operand_refs or not _values_equal(
                prior.value, claim.value, semantic_type, self.policy
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


class ValidationResultRepository(Protocol):
    def find_validation_result_by_fingerprint(
        self, fingerprint: str
    ) -> AIValidationResultModel | None: ...

    def add_validation_result(self, model: AIValidationResultModel) -> AIValidationResultModel: ...


class ValidationResultRecorder:
    def __init__(
        self,
        repository: ValidationResultRepository,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.repository = repository
        self.clock = clock

    def record(
        self,
        *,
        run_id: str,
        attempt_id: str,
        evidence_pack_id: str,
        result: ValidationResult,
    ) -> AIValidationResultModel:
        payload = {
            "run_id": run_id,
            "attempt_id": attempt_id,
            "evidence_pack_id": evidence_pack_id,
            "disposition": result.disposition,
            "findings": [item.model_dump(mode="python") for item in result.findings],
            "accepted_assertions": [
                item.model_dump(mode="python") for item in result.accepted_assertions
            ],
            "observations": [item.model_dump(mode="python") for item in result.observations],
            "candidate_fingerprint": result.candidate_fingerprint,
            "policy_version": result.policy_version,
        }
        fingerprint = fingerprint_payload(payload)
        existing = self.repository.find_validation_result_by_fingerprint(fingerprint)
        if existing is not None:
            return existing
        return self.repository.add_validation_result(
            AIValidationResultModel(
                id=str(uuid4()),
                run_id=run_id,
                attempt_id=attempt_id,
                evidence_pack_id=evidence_pack_id,
                disposition=result.disposition.value,
                findings_json=canonical_json_bytes(payload["findings"]).decode("utf-8"),
                accepted_assertions_json=canonical_json_bytes(
                    payload["accepted_assertions"]
                ).decode("utf-8"),
                observations_json=canonical_json_bytes(payload["observations"]).decode("utf-8"),
                candidate_fingerprint=result.candidate_fingerprint,
                policy_version=result.policy_version,
                fingerprint=fingerprint,
                created_at=self.clock().astimezone(UTC),
            )
        )
