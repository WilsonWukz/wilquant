from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import Protocol
from uuid import uuid4

from quant_lab.ai.configuration import _contains_forbidden_secret_key
from quant_lab.ai.contracts import (
    AnalysisRequirements,
    CanonicalEvidenceItem,
    EvidenceContext,
    EvidencePack,
    TemporalContext,
)
from quant_lab.ai.fingerprints import fingerprint_payload
from quant_lab.ai.persistence import AIEvidencePackModel
from quant_lab.ai.policies import AI2_POLICY, AI2Policy
from quant_lab.market_data.fingerprints import canonical_json_bytes


class EvidencePackError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class EvidencePackRepository(Protocol):
    def find_evidence_pack_by_fingerprint(
        self, fingerprint: str
    ) -> AIEvidencePackModel | None: ...

    def add_evidence_pack(self, model: AIEvidencePackModel) -> AIEvidencePackModel: ...


def _json_text(value: object) -> str:
    return canonical_json_bytes(value).decode("utf-8")


def _pack_from_model(model: AIEvidencePackModel) -> EvidencePack:
    return EvidencePack(
        id=model.id,
        case_id=model.case_id,
        temporal_context=json.loads(model.temporal_context_json),
        evidence_context=json.loads(model.evidence_context_json),
        requirements=json.loads(model.requirements_json),
        items=tuple(json.loads(model.items_json)),
        policy_version=model.policy_version,
        fingerprint=model.fingerprint,
        created_at=model.created_at.replace(tzinfo=UTC)
        if model.created_at.tzinfo is None
        else model.created_at,
    )


class EvidencePackService:
    def __init__(
        self,
        repository: EvidencePackRepository,
        *,
        policy: AI2Policy = AI2_POLICY,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.repository = repository
        self.policy = policy
        self.clock = clock

    @staticmethod
    def _validate_item(
        item: CanonicalEvidenceItem,
        temporal: TemporalContext,
        context: EvidenceContext,
    ) -> None:
        if item.integrity_status != "VERIFIED":
            raise EvidencePackError("INVALID_EVIDENCE", "evidence integrity is not verified")
        if item.known_at > temporal.knowledge_cutoff:
            raise EvidencePackError("FUTURE_KNOWLEDGE", "evidence exceeds knowledge cutoff")
        if item.effective_at > temporal.market_data_cutoff:
            raise EvidencePackError("FUTURE_MARKET_DATA", "evidence exceeds market-data cutoff")
        if item.market != context.market or item.market != temporal.market:
            raise EvidencePackError("MARKET_MISMATCH", "evidence market mismatch")
        if item.asset_type != context.asset_type or item.asset_type != temporal.asset_type:
            raise EvidencePackError("ASSET_TYPE_MISMATCH", "evidence asset type mismatch")
        if item.instrument_id != context.instrument_id:
            raise EvidencePackError("INSTRUMENT_MISMATCH", "evidence instrument mismatch")
        if context.currency is not None and item.currency not in {None, context.currency}:
            raise EvidencePackError("CURRENCY_MISMATCH", "evidence currency mismatch")
        if _contains_forbidden_secret_key({item.field: item.value}):
            raise EvidencePackError(
                "SECRET_MATERIAL_FORBIDDEN", "evidence contains forbidden secret-shaped field"
            )

    def freeze(
        self,
        *,
        case_id: str,
        temporal_context: TemporalContext,
        evidence_context: EvidenceContext,
        requirements: AnalysisRequirements,
        items: Sequence[CanonicalEvidenceItem],
    ) -> EvidencePack:
        ordered = tuple(sorted(items, key=lambda item: item.ref))
        if len(ordered) > self.policy.max_evidence_items:
            raise EvidencePackError("EVIDENCE_PACK_TOO_MANY_ITEMS", "evidence pack is too large")
        refs = [item.ref for item in ordered]
        if len(refs) != len(set(refs)):
            raise EvidencePackError("DUPLICATE_EVIDENCE_REF", "evidence refs must be unique")
        for item in ordered:
            self._validate_item(item, temporal_context, evidence_context)
        payload = {
            "case_id": case_id,
            "temporal_context": temporal_context.model_dump(mode="python"),
            "evidence_context": evidence_context.model_dump(mode="python"),
            "requirements": requirements.model_dump(mode="python"),
            "items": [item.model_dump(mode="python") for item in ordered],
            "policy_version": self.policy.evidence_policy_version,
        }
        encoded = canonical_json_bytes(payload)
        if len(encoded) > self.policy.max_evidence_bytes:
            raise EvidencePackError("EVIDENCE_PACK_TOO_MANY_BYTES", "evidence pack is too large")
        fingerprint = fingerprint_payload(payload)
        existing = self.repository.find_evidence_pack_by_fingerprint(fingerprint)
        if existing is not None:
            return _pack_from_model(existing)
        now = self.clock().astimezone(UTC)
        model = self.repository.add_evidence_pack(
            AIEvidencePackModel(
                id=str(uuid4()),
                case_id=case_id,
                temporal_context_json=_json_text(payload["temporal_context"]),
                evidence_context_json=_json_text(payload["evidence_context"]),
                requirements_json=_json_text(payload["requirements"]),
                items_json=_json_text(payload["items"]),
                policy_version=self.policy.evidence_policy_version,
                fingerprint=fingerprint,
                created_at=now,
            )
        )
        return _pack_from_model(model)


__all__ = ["EvidencePackError", "EvidencePackService", "_pack_from_model"]
