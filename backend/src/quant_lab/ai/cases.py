from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from uuid import uuid4

from quant_lab.ai.configuration import AIProvenanceError
from quant_lab.ai.fingerprints import fingerprint_payload
from quant_lab.ai.persistence import AIResearchCaseModel
from quant_lab.ai.repository import AIRepository
from quant_lab.market_data.fingerprints import canonical_json_bytes

REQUIRED_BINDING_KEYS = frozenset(
    {"market_data_fingerprint", "calendar_fingerprint", "market_rules_fingerprint"}
)


@dataclass(frozen=True, slots=True)
class ResearchCaseInput:
    purpose: str
    market: str
    exchange: str
    symbol: str
    instrument_id: str
    asset_type: str
    currency: str
    timeframe: str
    as_of_utc: datetime
    market_local_trade_date: date
    bindings: Mapping[str, object]
    previous_case_id: str | None = None
    previous_analysis_run_id: str | None = None
    thesis_revision_id: str | None = None


def require_utc(value: datetime, category: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise AIProvenanceError(category, "时间必须包含时区")
    return value.astimezone(UTC)


def stored_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class ResearchCaseService:
    def __init__(self, repository: AIRepository) -> None:
        self.repository = repository

    def freeze(self, value: ResearchCaseInput, *, actor: str) -> AIResearchCaseModel:
        as_of_utc = require_utc(value.as_of_utc, "AI_CASE_TIMEZONE_REQUIRED")
        bindings = dict(value.bindings)
        missing = REQUIRED_BINDING_KEYS.difference(bindings)
        if missing:
            raise AIProvenanceError(
                "AI_CASE_BINDINGS_INCOMPLETE",
                "研究案例缺少行情、日历或市场规则版本绑定",
            )
        if value.previous_case_id is not None:
            parent = self.repository.get_research_case(value.previous_case_id)
            if parent is None:
                raise AIProvenanceError("AI_CASE_PARENT_NOT_FOUND", "父研究案例不存在")
            self._validate_parent_chain(parent)
        payload = {
            "purpose": value.purpose,
            "market": value.market,
            "exchange": value.exchange,
            "symbol": value.symbol,
            "instrument_id": value.instrument_id,
            "asset_type": value.asset_type,
            "currency": value.currency,
            "timeframe": value.timeframe,
            "as_of_utc": as_of_utc,
            "market_local_trade_date": value.market_local_trade_date,
            "bindings": bindings,
            "previous_case_id": value.previous_case_id,
            "previous_analysis_run_id": value.previous_analysis_run_id,
            "thesis_revision_id": value.thesis_revision_id,
        }
        fingerprint = fingerprint_payload(payload)
        existing = self.repository.find_research_case_by_fingerprint(fingerprint)
        if existing is not None:
            return existing
        return self.repository.add_research_case(
            AIResearchCaseModel(
                id=str(uuid4()),
                purpose=value.purpose,
                market=value.market,
                exchange=value.exchange,
                symbol=value.symbol,
                instrument_id=value.instrument_id,
                asset_type=value.asset_type,
                currency=value.currency,
                timeframe=value.timeframe,
                as_of_utc=as_of_utc,
                market_local_trade_date=value.market_local_trade_date,
                bindings_json=canonical_json_bytes(bindings).decode("utf-8"),
                previous_case_id=value.previous_case_id,
                previous_analysis_run_id=value.previous_analysis_run_id,
                thesis_revision_id=value.thesis_revision_id,
                fingerprint=fingerprint,
                created_by=actor,
                created_at=datetime.now(UTC),
            )
        )

    def _validate_parent_chain(self, parent: AIResearchCaseModel) -> None:
        seen = {parent.id}
        current = parent
        while current.previous_case_id is not None:
            if current.previous_case_id in seen:
                raise AIProvenanceError("AI_CASE_LINEAGE_CYCLE", "研究案例 lineage 存在循环")
            seen.add(current.previous_case_id)
            next_parent = self.repository.get_research_case(current.previous_case_id)
            if next_parent is None:
                raise AIProvenanceError("AI_CASE_PARENT_NOT_FOUND", "父研究案例不存在")
            current = next_parent
