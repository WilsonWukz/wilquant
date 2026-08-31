from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator

from quant_lab.ai.contracts import (
    AssetType,
    CanonicalEvidenceItem,
    EvidenceClassification,
    EvidenceScalar,
    EvidenceSemanticType,
    EvidenceSourceType,
    FreshnessClass,
    Market,
    canonical_unit,
)
from quant_lab.ai.fingerprints import fingerprint_payload


class EvidenceResolverError(ValueError):
    pass


class UnsupportedEvidenceSource(EvidenceResolverError):
    pass


class DisallowedEvidenceField(EvidenceResolverError):
    pass


class EvidenceSourceNotFound(EvidenceResolverError):
    pass


class TemporalMetadataUnavailable(EvidenceResolverError):
    pass


class EvidenceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_type: EvidenceSourceType
    source_id: str = Field(min_length=1, max_length=100)
    fields: tuple[str, ...] = ()


class SourceSnapshot(BaseModel):
    """Versioned domain snapshot returned by an explicitly wired source adapter."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_entity_id: str
    source_version_id: str
    source_fingerprint: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    subject: str
    effective_at: datetime
    known_at: datetime
    observed_at: datetime | None = None
    market_timestamp: datetime | None = None
    freshness_class: FreshnessClass = FreshnessClass.IMMUTABLE_HISTORICAL
    known_delay_seconds: int | None = Field(default=None, ge=0)
    market: Market
    asset_type: AssetType
    instrument_id: str | None = None
    currency: str | None = None
    context: dict[str, object] = Field(default_factory=dict)
    values: Mapping[str, EvidenceScalar]

    @field_validator("effective_at", "known_at", "observed_at", "market_timestamp")
    @classmethod
    def _aware_utc(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("datetime must be timezone-aware")
        return value.astimezone(UTC)


SourceLoader = Callable[[str], SourceSnapshot]


class EvidenceResolver(Protocol):
    source_type: EvidenceSourceType
    allowed_fields: frozenset[str]

    def resolve(self, request: EvidenceRequest) -> tuple[CanonicalEvidenceItem, ...]: ...


class ExplicitSnapshotResolver:
    def __init__(
        self,
        *,
        source_type: EvidenceSourceType,
        field_classifications: Mapping[str, EvidenceClassification],
        field_semantic_types: Mapping[str, EvidenceSemanticType],
        field_units: Mapping[str, str | None],
        resolver_policy_version: str,
        loader: SourceLoader,
    ) -> None:
        self.source_type = source_type
        self._field_classifications = dict(field_classifications)
        self._field_semantic_types = dict(field_semantic_types)
        self._field_units = dict(field_units)
        self.resolver_policy_version = resolver_policy_version
        self._loader = loader
        self.allowed_fields = frozenset(self._field_classifications)
        if set(self._field_semantic_types) != set(self._field_classifications):
            raise ValueError("semantic type policy must cover every allowed field")

    def resolve(self, request: EvidenceRequest) -> tuple[CanonicalEvidenceItem, ...]:
        requested = frozenset(request.fields) if request.fields else self.allowed_fields
        disallowed = requested - self.allowed_fields
        if disallowed:
            raise DisallowedEvidenceField(f"{self.source_type}: {','.join(sorted(disallowed))}")
        snapshot = self._loader(request.source_id)
        missing = requested - set(snapshot.values)
        if missing:
            raise EvidenceSourceNotFound(f"{self.source_type}: missing {','.join(sorted(missing))}")
        resolved: list[CanonicalEvidenceItem] = []
        for field in sorted(requested):
            unit = canonical_unit(self._field_units.get(field))
            semantic_type = self._field_semantic_types[field]
            value_fingerprint = fingerprint_payload(
                {
                    "value": snapshot.values[field],
                    "semantic_type": semantic_type,
                    "unit": unit,
                }
            )
            ref_fingerprint = fingerprint_payload(
                {
                    "source_type": self.source_type,
                    "source_id": snapshot.source_entity_id,
                    "source_version_id": snapshot.source_version_id,
                    "field_path": field,
                    "source_fingerprint": snapshot.source_fingerprint,
                    "value_fingerprint": value_fingerprint,
                    "effective_at": snapshot.effective_at,
                    "known_at": snapshot.known_at,
                    "observed_at": snapshot.observed_at,
                    "market_timestamp": snapshot.market_timestamp,
                    "freshness_class": snapshot.freshness_class,
                    "known_delay_seconds": snapshot.known_delay_seconds,
                    "resolver_policy_version": self.resolver_policy_version,
                }
            )
            resolved.append(
                CanonicalEvidenceItem(
                    ref_id=f"ev-{ref_fingerprint}",
                    source_type=self.source_type,
                    source_id=snapshot.source_entity_id,
                    source_version_id=snapshot.source_version_id,
                    field_path=field,
                    classification=self._field_classifications[field],
                    semantic_type=semantic_type,
                    value=snapshot.values[field],
                    unit=unit,
                    subject=snapshot.subject,
                    source_fingerprint=snapshot.source_fingerprint,
                    value_fingerprint=value_fingerprint,
                    effective_at=snapshot.effective_at,
                    known_at=snapshot.known_at,
                    observed_at=snapshot.observed_at,
                    market_timestamp=snapshot.market_timestamp,
                    freshness_class=snapshot.freshness_class,
                    known_delay_seconds=snapshot.known_delay_seconds,
                    market=snapshot.market,
                    asset_type=snapshot.asset_type,
                    instrument_id=snapshot.instrument_id,
                    currency=snapshot.currency,
                    context=snapshot.context,
                    resolver_policy_version=self.resolver_policy_version,
                )
            )
        return tuple(resolved)


class EvidenceResolverRegistry:
    def __init__(self) -> None:
        self._resolvers: dict[EvidenceSourceType, EvidenceResolver] = {}

    def register(self, resolver: EvidenceResolver) -> None:
        if resolver.source_type in self._resolvers:
            raise ValueError(f"{resolver.source_type} already registered")
        self._resolvers[resolver.source_type] = resolver

    def get(self, source_type: EvidenceSourceType) -> EvidenceResolver:
        resolver = self._resolvers.get(source_type)
        if resolver is None:
            raise UnsupportedEvidenceSource(source_type.value)
        return resolver

    def resolve(self, request: EvidenceRequest) -> tuple[CanonicalEvidenceItem, ...]:
        return self.get(request.source_type).resolve(request)

    def resolve_source(
        self, source_type: str, source_id: str, fields: tuple[str, ...] = ()
    ) -> tuple[CanonicalEvidenceItem, ...]:
        try:
            typed_source = EvidenceSourceType(source_type)
        except ValueError as error:
            raise UnsupportedEvidenceSource(source_type) from error
        return self.resolve(
            EvidenceRequest(source_type=typed_source, source_id=source_id, fields=fields)
        )
