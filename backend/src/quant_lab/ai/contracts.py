from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class EvidenceSourceType(StrEnum):
    DATASET_VERSION = "DATASET_VERSION"
    MARKET_DATA_SNAPSHOT = "MARKET_DATA_SNAPSHOT"
    STRATEGY_VERSION = "STRATEGY_VERSION"
    BACKTEST_RUN = "BACKTEST_RUN"
    RESEARCH_EXPERIMENT = "RESEARCH_EXPERIMENT"
    RESEARCH_COMPARISON = "RESEARCH_COMPARISON"
    RESEARCH_DIAGNOSTIC = "RESEARCH_DIAGNOSTIC"
    RESEARCH_REPORT = "RESEARCH_REPORT"
    PAPER_SESSION = "PAPER_SESSION"
    PAPER_ACCOUNT_SNAPSHOT = "PAPER_ACCOUNT_SNAPSHOT"
    RISK_DECISION = "RISK_DECISION"


class EvidenceClassification(StrEnum):
    FACT = "FACT"
    USER_NOTE = "USER_NOTE"
    DERIVED_METRIC = "DERIVED_METRIC"
    SYSTEM_STATE = "SYSTEM_STATE"


class ClaimType(StrEnum):
    FACT = "FACT"
    INFERENCE = "INFERENCE"
    HYPOTHESIS = "HYPOTHESIS"


class ClaimPredicate(StrEnum):
    EQUALS = "EQUALS"
    GREATER_THAN = "GREATER_THAN"
    LESS_THAN = "LESS_THAN"
    DELTA = "DELTA"
    PERCENT_CHANGE = "PERCENT_CHANGE"


class ValidationLayer(StrEnum):
    SYNTAX = "SYNTAX"
    SCHEMA = "SCHEMA"
    SEMANTIC = "SEMANTIC"
    GROUNDING = "GROUNDING"
    TEMPORAL = "TEMPORAL"
    IMMUTABLE_FACT = "IMMUTABLE_FACT"


class FindingSeverity(StrEnum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


class GateDecision(StrEnum):
    REJECT = "REJECT"
    WAIT_FOR_EVIDENCE = "WAIT_FOR_EVIDENCE"
    ABSTAIN = "ABSTAIN"
    PROCEED = "PROCEED"


class ValidationDisposition(StrEnum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


Market = Literal["CN_A_SHARE", "US_EQUITY"]
AssetType = Literal["EQUITY", "ETF"]
AnalysisMode = Literal["CURRENT_RESEARCH", "HISTORICAL_REPLAY"]
RuleTopic = Literal[
    "T_PLUS_ONE",
    "SAME_DAY_SELL",
    "LOT_SIZE",
    "PRICE_LIMIT",
    "FRACTIONAL_QUANTITY",
    "TRADING_SESSION",
    "SETTLEMENT",
    "SELLABILITY",
]


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must be timezone-aware")
    return value.astimezone(UTC)


class TemporalContext(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    market_data_cutoff: datetime
    knowledge_cutoff: datetime
    market: Market
    timezone: str = Field(min_length=1, max_length=64)
    asset_type: AssetType
    analysis_mode: AnalysisMode

    _utc_cutoffs = field_validator("market_data_cutoff", "knowledge_cutoff")(_aware_utc)


class EvidenceContext(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    market: Market
    exchange: str | None = Field(default=None, max_length=32)
    instrument_id: str = Field(min_length=1, max_length=100)
    currency: str | None = Field(default=None, max_length=8)
    asset_type: AssetType
    timezone: str = Field(min_length=1, max_length=64)
    market_rules_version: str | None = Field(default=None, max_length=100)


class AnalysisRequirements(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    requires_market_rules: bool = False
    required_rule_topics: tuple[RuleTopic, ...] = ()
    requires_comparability: bool = False

    @property
    def market_rules_required(self) -> bool:
        return self.requires_market_rules or bool(self.required_rule_topics)


EvidenceScalar = str | int | float | bool | Decimal | None


class CanonicalEvidenceItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    ref: str = Field(min_length=1, max_length=255)
    source_type: EvidenceSourceType
    source_entity_id: str = Field(min_length=1, max_length=100)
    source_version_id: str = Field(min_length=1, max_length=100)
    field: str = Field(min_length=1, max_length=100)
    value: EvidenceScalar
    value_type: Literal["STRING", "INTEGER", "DECIMAL", "BOOLEAN", "NULL"]
    unit: str | None = Field(default=None, max_length=32)
    classification: EvidenceClassification
    subject: str = Field(min_length=1, max_length=160)
    effective_at: datetime
    known_at: datetime
    market: Market
    asset_type: AssetType
    instrument_id: str = Field(min_length=1, max_length=100)
    currency: str | None = Field(default=None, max_length=8)
    content_fingerprint: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    integrity_status: Literal["VERIFIED", "MISSING", "INVALID"] = "VERIFIED"

    _utc_times = field_validator("effective_at", "known_at")(_aware_utc)


class EvidencePack(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    case_id: str
    temporal_context: TemporalContext
    evidence_context: EvidenceContext
    requirements: AnalysisRequirements
    items: tuple[CanonicalEvidenceItem, ...]
    policy_version: str
    fingerprint: str = Field(min_length=64, max_length=64)
    created_at: datetime

    _utc_created = field_validator("created_at")(_aware_utc)


class StructuredClaim(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    claim_id: str = Field(min_length=1, max_length=100)
    claim_type: ClaimType
    subject: str = Field(min_length=1, max_length=160)
    predicate: ClaimPredicate
    value: EvidenceScalar
    unit: str | None = Field(default=None, max_length=32)
    evidence_refs: tuple[str, ...] = ()
    operand_refs: tuple[str, ...] = ()


class StructuredCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["ai-structured-output-v1"]
    action_type: str = Field(min_length=1, max_length=64)
    claims: tuple[StructuredClaim, ...]


class ValidationFinding(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    layer: ValidationLayer
    code: str
    severity: FindingSeverity
    message_safe: str
    retryable: bool
    claim_id: str | None = None
    evidence_ref: str | None = None


class AssertionObservation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    assertion_identity: str
    claim_type: str
    subject: str
    predicate: str
    value: EvidenceScalar
    unit: str | None
    evidence_refs: tuple[str, ...]
    operand_refs: tuple[str, ...]
    origin_attempt_id: str
    trusted: Literal[False] = False


class AcceptedAssertion(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    assertion_identity: str
    claim_id: str
    claim_type: ClaimType
    subject: str
    predicate: ClaimPredicate
    value: EvidenceScalar
    unit: str | None
    evidence_refs: tuple[str, ...]
    operand_refs: tuple[str, ...]


class ValidationResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    disposition: ValidationDisposition
    findings: tuple[ValidationFinding, ...]
    accepted_assertions: tuple[AcceptedAssertion, ...]
    observations: tuple[AssertionObservation, ...]
    candidate_fingerprint: str
    policy_version: str

    @property
    def accepted(self) -> bool:
        return self.disposition is ValidationDisposition.ACCEPTED

    @property
    def error_codes(self) -> tuple[str, ...]:
        return tuple(
            finding.code
            for finding in self.findings
            if finding.severity is FindingSeverity.ERROR
        )


class GateResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    decision: GateDecision
    reason_codes: tuple[str, ...]


class RetrievalQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    market: Market
    asset_type: AssetType
    market_data_cutoff: datetime
    knowledge_cutoff: datetime
    query_text: str = Field(default="", max_length=500)
    universe: tuple[str, ...] = ()
    strategy_family: str | None = Field(default=None, max_length=100)
    regime_labels: tuple[str, ...] = ()
    safe_tags: tuple[str, ...] = ()
    market_rules_version: str | None = Field(default=None, max_length=100)
    requires_market_rules: bool = False
    limit: Annotated[int, Field(ge=1, le=20)] = 20

    _utc_cutoffs = field_validator("market_data_cutoff", "knowledge_cutoff")(_aware_utc)


class RetrievalCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str
    document_id: str
    document_fingerprint: str
    case_end_at: datetime
    known_at: datetime
    structured_score: int
    lexical_score: int
    final_score: int
    rank: int

    _utc_times = field_validator("case_end_at", "known_at")(_aware_utc)
