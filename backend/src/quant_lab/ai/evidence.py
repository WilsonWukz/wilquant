from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from string import hexdigits
from uuid import uuid4

from quant_lab.ai.cases import require_utc, stored_utc
from quant_lab.ai.configuration import AIProvenanceError
from quant_lab.ai.fingerprints import fingerprint_payload
from quant_lab.ai.persistence import AIEvidenceRefModel
from quant_lab.ai.repository import AIRepository
from quant_lab.market_data.fingerprints import canonical_json_bytes


@dataclass(frozen=True, slots=True)
class EvidenceRefInput:
    evidence_type: str
    source_entity_type: str
    source_entity_id: str
    source_version_id: str
    content_sha256: str
    locator: Mapping[str, object]
    effective_at: datetime
    known_at: datetime
    captured_at: datetime
    market: str
    instrument_id: str
    currency: str
    temporal_status: str
    integrity_status: str


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(character in hexdigits for character in value)


class EvidenceRefService:
    def __init__(self, repository: AIRepository) -> None:
        self.repository = repository

    def register(self, case_id: str, value: EvidenceRefInput) -> AIEvidenceRefModel:
        case = self.repository.get_research_case(case_id)
        if case is None:
            raise AIProvenanceError("AI_CASE_NOT_FOUND", "研究案例不存在")
        effective_at = require_utc(value.effective_at, "AI_EVIDENCE_TIMEZONE_REQUIRED")
        known_at = require_utc(value.known_at, "AI_EVIDENCE_TIMEZONE_REQUIRED")
        captured_at = require_utc(value.captured_at, "AI_EVIDENCE_TIMEZONE_REQUIRED")
        if known_at > stored_utc(case.as_of_utc):
            raise AIProvenanceError(
                "AI_EVIDENCE_FUTURE_KNOWLEDGE", "证据在研究时间截断后才可知"
            )
        if (value.market, value.instrument_id, value.currency) != (
            case.market,
            case.instrument_id,
            case.currency,
        ):
            raise AIProvenanceError(
                "AI_EVIDENCE_CASE_IDENTITY_MISMATCH", "证据与研究案例的市场标的身份不一致"
            )
        if not _is_sha256(value.content_sha256):
            raise AIProvenanceError("AI_EVIDENCE_HASH_INVALID", "证据内容哈希无效")
        locator = dict(value.locator)
        payload = {
            "case_id": case_id,
            "evidence_type": value.evidence_type,
            "source_entity_type": value.source_entity_type,
            "source_entity_id": value.source_entity_id,
            "source_version_id": value.source_version_id,
            "content_sha256": value.content_sha256.lower(),
            "locator": locator,
            "effective_at": effective_at,
            "known_at": known_at,
            "captured_at": captured_at,
            "market": value.market,
            "instrument_id": value.instrument_id,
            "currency": value.currency,
            "temporal_status": value.temporal_status,
            "integrity_status": value.integrity_status,
        }
        fingerprint = fingerprint_payload(payload)
        existing = self.repository.find_evidence_ref_by_fingerprint(fingerprint)
        if existing is not None:
            return existing
        return self.repository.add_evidence_ref(
            AIEvidenceRefModel(
                id=str(uuid4()),
                case_id=case_id,
                evidence_type=value.evidence_type,
                source_entity_type=value.source_entity_type,
                source_entity_id=value.source_entity_id,
                source_version_id=value.source_version_id,
                content_sha256=value.content_sha256.lower(),
                locator_json=canonical_json_bytes(locator).decode("utf-8"),
                effective_at=effective_at,
                known_at=known_at,
                captured_at=captured_at,
                market=value.market,
                instrument_id=value.instrument_id,
                currency=value.currency,
                temporal_status=value.temporal_status,
                integrity_status=value.integrity_status,
                fingerprint=fingerprint,
                created_at=datetime.now(UTC),
            )
        )
