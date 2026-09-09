from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from quant_lab.ai.configuration import contains_forbidden_secret_material
from quant_lab.ai.fingerprints import fingerprint_payload
from quant_lab.market_data.fingerprints import canonical_json_bytes


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


class EvidenceSemanticType(StrEnum):
    NUMBER = "NUMBER"
    MONEY = "MONEY"
    RATIO = "RATIO"
    COUNT = "COUNT"
    TEXT = "TEXT"
    ENUM = "ENUM"
    DATETIME = "DATETIME"
    BOOLEAN = "BOOLEAN"
    IDENTIFIER = "IDENTIFIER"
    JSON = "JSON"


class FreshnessClass(StrEnum):
    IMMUTABLE_HISTORICAL = "IMMUTABLE_HISTORICAL"
    EOD = "EOD"
    DELAYED = "DELAYED"
    REALTIME = "REALTIME"


class FreshnessRequirement(StrEnum):
    HISTORICAL_OK = "HISTORICAL_OK"
    EOD_REQUIRED = "EOD_REQUIRED"
    DELAYED_OK = "DELAYED_OK"
    REALTIME_REQUIRED = "REALTIME_REQUIRED"


class ClaimType(StrEnum):
    FACT = "FACT"
    INFERENCE = "INFERENCE"
    HYPOTHESIS = "HYPOTHESIS"


class ClaimPredicate(StrEnum):
    EQ = "EQ"
    NE = "NE"
    GT = "GT"
    GTE = "GTE"
    LT = "LT"
    LTE = "LTE"
    DELTA = "DELTA"
    PERCENT_CHANGE = "PERCENT_CHANGE"


class Uncertainty(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


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


def _aware_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
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


EvidenceScalar = (
    str
    | int
    | float
    | bool
    | Decimal
    | datetime
    | date
    | tuple[object, ...]
    | list[object]
    | dict[str, object]
    | None
)


def canonical_unit(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = "".join(
        character for character in value.upper() if character.isalnum() or character == "%"
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


_CONTEXT_KEYS = frozenset({"market", "exchange", "universe", "analysis_scope", "strategy_family"})
_SECRET_CONTEXT_KEYS = frozenset(
    {
        "apikey",
        "clientsecret",
        "accesstoken",
        "authorization",
        "bearer",
        "password",
        "gatewaysecret",
        "brokercredential",
    }
)


def _normalized_key(value: str) -> str:
    return "".join(character for character in value.lower() if character.isalnum())


def _context_depth(value: object, depth: int = 0) -> int:
    if isinstance(value, dict):
        return max([_context_depth(item, depth + 1) for item in value.values()] or [depth])
    if isinstance(value, list | tuple):
        return max([_context_depth(item, depth + 1) for item in value] or [depth])
    return depth


def _context_contains_secret_key(value: object) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = _normalized_key(str(key))
            if normalized in _SECRET_CONTEXT_KEYS or normalized.endswith(
                ("apikey", "authorization", "credential", "password", "secret", "token")
            ):
                return True
            if _context_contains_secret_key(item):
                return True
    elif isinstance(value, list | tuple):
        return any(_context_contains_secret_key(item) for item in value)
    return False


class CanonicalEvidenceItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    ref_id: str = Field(
        min_length=1,
        max_length=255,
        validation_alias=AliasChoices("ref_id", "ref"),
    )
    source_type: EvidenceSourceType
    source_id: str = Field(
        min_length=1,
        max_length=100,
        validation_alias=AliasChoices("source_id", "source_entity_id"),
    )
    source_version_id: str = Field(min_length=1, max_length=100)
    field_path: str = Field(
        min_length=1,
        max_length=100,
        validation_alias=AliasChoices("field_path", "field"),
    )
    classification: EvidenceClassification
    semantic_type: EvidenceSemanticType = Field(
        validation_alias=AliasChoices("semantic_type", "value_type")
    )
    value: EvidenceScalar
    unit: str | None = Field(default=None, max_length=32)
    subject: str = Field(min_length=1, max_length=160)
    source_fingerprint: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
        validation_alias=AliasChoices("source_fingerprint", "content_fingerprint"),
    )
    value_fingerprint: str | None = Field(
        default=None, min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$"
    )
    effective_at: datetime
    known_at: datetime
    observed_at: datetime | None = None
    market_timestamp: datetime | None = None
    freshness_class: FreshnessClass = FreshnessClass.IMMUTABLE_HISTORICAL
    known_delay_seconds: int | None = Field(default=None, ge=0)
    market: Market
    asset_type: AssetType
    instrument_id: str | None = Field(default=None, min_length=1, max_length=100)
    currency: str | None = Field(default=None, max_length=8)
    context: dict[str, object] = Field(default_factory=dict)
    resolver_policy_version: str = Field(default="legacy-v1", min_length=1, max_length=64)
    integrity_status: Literal["VERIFIED", "MISSING", "INVALID"] = "VERIFIED"

    @field_validator("semantic_type", mode="before")
    @classmethod
    def _legacy_semantic_type(cls, value: object) -> object:
        aliases = {
            "STRING": EvidenceSemanticType.TEXT,
            "INTEGER": EvidenceSemanticType.COUNT,
            "DECIMAL": EvidenceSemanticType.NUMBER,
            "BOOLEAN": EvidenceSemanticType.BOOLEAN,
            "NULL": EvidenceSemanticType.JSON,
        }
        return aliases.get(value, value) if isinstance(value, str) else value

    _utc_times = field_validator("effective_at", "known_at", "observed_at", "market_timestamp")(
        _aware_utc
    )

    @field_validator("context")
    @classmethod
    def _bounded_context(cls, value: dict[str, object]) -> dict[str, object]:
        disallowed = set(value) - _CONTEXT_KEYS
        if disallowed:
            raise ValueError("evidence context key is not allowlisted")
        if _context_contains_secret_key(value) or contains_forbidden_secret_material(value):
            raise ValueError("secret-shaped evidence context is forbidden")
        if len(value) > 8 or _context_depth(value) > 2:
            raise ValueError("evidence context exceeds structural limits")
        if len(canonical_json_bytes(value)) > 4096:
            raise ValueError("evidence context exceeds size limit")
        return dict(sorted(value.items()))

    @model_validator(mode="after")
    def _derive_value_fingerprint(self) -> CanonicalEvidenceItem:
        expected = fingerprint_payload(
            {
                "value": self.value,
                "semantic_type": self.semantic_type,
                "unit": canonical_unit(self.unit),
            }
        )
        if self.value_fingerprint is None:
            object.__setattr__(self, "value_fingerprint", expected)
        elif self.value_fingerprint != expected:
            raise ValueError("value_fingerprint does not match canonical value")
        return self

    @property
    def ref(self) -> str:
        return self.ref_id

    @property
    def source_entity_id(self) -> str:
        return self.source_id

    @property
    def field(self) -> str:
        return self.field_path

    @property
    def content_fingerprint(self) -> str:
        return self.source_fingerprint

    @property
    def value_type(self) -> str:
        return {
            EvidenceSemanticType.TEXT: "STRING",
            EvidenceSemanticType.ENUM: "STRING",
            EvidenceSemanticType.IDENTIFIER: "STRING",
            EvidenceSemanticType.COUNT: "INTEGER",
            EvidenceSemanticType.BOOLEAN: "BOOLEAN",
        }.get(self.semantic_type, "DECIMAL")


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
    text: str = Field(min_length=1, max_length=2000)
    subject: str = Field(min_length=1, max_length=160)
    predicate: ClaimPredicate
    value: EvidenceScalar
    unit: str | None = Field(default=None, max_length=32)
    evidence_refs: tuple[str, ...] = ()
    operand_refs: tuple[str, ...] = ()
    uncertainty: Uncertainty | None = None
    recommendation: str | None = Field(default=None, max_length=64)

    @field_validator("predicate", mode="before")
    @classmethod
    def _normalize_legacy_predicate(cls, value: object) -> object:
        aliases = {
            "EQUALS": ClaimPredicate.EQ,
            "GREATER_THAN": ClaimPredicate.GT,
            "LESS_THAN": ClaimPredicate.LT,
        }
        return aliases.get(value, value) if isinstance(value, str) else value


class StructuredCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["ai-structured-output-v1"]
    action_type: str = Field(min_length=1, max_length=64)
    recommendation: str | None = Field(default=None, max_length=64)
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
    field_path: str | None = None


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
            finding.code for finding in self.findings if finding.severity is FindingSeverity.ERROR
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


class RetrievalSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    query: RetrievalQuery
    policy_version: str
    candidates: tuple[RetrievalCandidate, ...]
    exclusions: tuple[dict[str, str], ...]
    fingerprint: str = Field(min_length=64, max_length=64)
    created_at: datetime

    _utc_created = field_validator("created_at")(_aware_utc)
