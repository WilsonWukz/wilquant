from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from quant_lab.datasets.errors import DatasetError
from quant_lab.datasets.query import DatasetQueryService
from quant_lab.market_data.calendar_persistence import TradingCalendarRepository
from quant_lab.market_data.fingerprints import canonical_json_bytes
from quant_lab.market_data.persistence import InstrumentModel
from quant_lab.market_data.profile_persistence import (
    MarketDataProfileModel,
    MarketDataProfileRepository,
)


class MarketDataService:
    def __init__(
        self,
        profile_repository: MarketDataProfileRepository,
        calendar_repository: TradingCalendarRepository,
        dataset_query: DatasetQueryService,
        engine,
    ) -> None:
        self.profiles = profile_repository
        self.calendars = calendar_repository
        self.dataset_query = dataset_query
        self.engine = engine

    def _profile(self, profile_id: str) -> MarketDataProfileModel:
        return self.profiles.get(profile_id)

    def bars(
        self,
        profile_id: str,
        *,
        instrument_id: str | None = None,
        start: date | None = None,
        end: date | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, object]:
        profile = self._profile(profile_id)
        calendar = self.calendars.get_version(profile.calendar_id, profile.calendar_version_id)
        rows = self.dataset_query.bars(
            profile.bars_dataset_id,
            profile.bars_dataset_version_id,
            instrument_id=instrument_id,
            start=start,
            end=end,
            limit=limit,
            offset=offset,
        )
        timestamps = [row["timestamp"] for row in rows]
        query_payload = {
            "profile_id": profile_id,
            "dataset_version_id": profile.bars_dataset_version_id,
            "calendar_version_id": profile.calendar_version_id,
            "instrument_id": instrument_id,
            "start": start.isoformat() if start else None,
            "end": end.isoformat() if end else None,
            "limit": limit,
            "offset": offset,
        }
        return {
            "profile_id": profile_id,
            "dataset_version_id": profile.bars_dataset_version_id,
            "calendar_version_id": calendar.trading_calendar_version_id,
            "instrument_id": instrument_id,
            "bars": rows,
            "first_timestamp": min(timestamps) if timestamps else None,
            "last_timestamp": max(timestamps) if timestamps else None,
            "row_count": len(rows),
            "query_fingerprint": hashlib.sha256(canonical_json_bytes(query_payload)).hexdigest(),
        }

    def instruments(self, profile_id: str) -> list[dict[str, object]]:
        self._profile(profile_id)
        with Session(self.engine) as session:
            values = tuple(
                session.scalars(select(InstrumentModel).order_by(InstrumentModel.instrument_id))
            )
        return [
            {
                "instrument_id": item.instrument_id,
                "symbol": item.symbol,
                "exchange": item.exchange,
                "name": item.name,
                "security_type": item.instrument_type,
                "currency": item.currency,
                "lot_size": item.lot_size,
                "price_tick": item.price_tick,
            }
            for item in values
        ]

    def coverage(
        self,
        profile_id: str,
        *,
        instrument_id: str | None = None,
        start: date | None = None,
        end: date | None = None,
        limit: int = 1000,
    ) -> dict[str, object]:
        profile = self._profile(profile_id)
        calendar = self.calendars.get_version(profile.calendar_id, profile.calendar_version_id)
        version = self.dataset_query.repository.get_version(
            profile.bars_dataset_id, profile.bars_dataset_version_id
        )
        if version.min_timestamp and calendar.first_session_date and (
            calendar.first_session_date > version.min_timestamp.date()
        ):
            raise DatasetError("CALENDAR_COVERAGE_INCOMPLETE", "交易日历未覆盖数据起始日期")
        if version.max_timestamp and calendar.last_session_date and (
            calendar.last_session_date < version.max_timestamp.date()
        ):
            raise DatasetError("CALENDAR_COVERAGE_INCOMPLETE", "交易日历未覆盖数据结束日期")
        sessions = self.calendars.list_sessions(
            calendar.trading_calendar_version_id, open_only=True, start=start, end=end, limit=limit
        )
        if not sessions:
            raise DatasetError("CALENDAR_COVERAGE_INCOMPLETE", "交易日日历没有覆盖查询区间")
        rows = self.dataset_query.bars(
            profile.bars_dataset_id,
            profile.bars_dataset_version_id,
            instrument_id=instrument_id,
            start=start,
            end=end,
            limit=limit,
        )
        bar_dates = {row["trade_date"] for row in rows}
        session_dates = {item.session_date for item in sessions}
        missing = sorted(session_dates - bar_dates)
        out_of_calendar = sorted(bar_dates - session_dates)
        return {
            "profile_id": profile_id,
            "dataset_version_id": profile.bars_dataset_version_id,
            "calendar_version_id": profile.calendar_version_id,
            "instrument_id": instrument_id,
            "first_bar_date": min(bar_dates) if bar_dates else None,
            "last_bar_date": max(bar_dates) if bar_dates else None,
            "bar_count": len(rows),
            "expected_session_count": len(session_dates),
            "missing_session_count": len(missing),
            "missing_dates": missing[:100],
            "out_of_calendar_dates": out_of_calendar[:100],
            "non_trading_day_bar": bool(out_of_calendar),
            "missing_rate": len(missing) / len(session_dates),
            "status": "READY" if not out_of_calendar else "DATASET_INCONSISTENT",
        }

    def health(self, profile_id: str) -> dict[str, object]:
        profile = self._profile(profile_id)
        try:
            self.dataset_query.summary(profile.bars_dataset_id, profile.bars_dataset_version_id)
            calendar = self.calendars.get_version(profile.calendar_id, profile.calendar_version_id)
            status = "READY" if calendar.status == "PUBLISHED" else "CALENDAR_NOT_PUBLISHED"
        except DatasetError as error:
            status = error.category
        return {
            "profile_id": profile_id,
            "status": status,
            "bars_dataset_version_id": profile.bars_dataset_version_id,
            "calendar_version_id": profile.calendar_version_id,
        }

    def snapshot(self, profile_id: str) -> dict[str, object]:
        profile = self._profile(profile_id)
        version = self.dataset_query.repository.get_version(
            profile.bars_dataset_id, profile.bars_dataset_version_id
        )
        calendar = self.calendars.get_version(profile.calendar_id, profile.calendar_version_id)
        payload = {
            "profile_id": profile_id,
            "bars_dataset_version_id": version.dataset_version_id,
            "bars_dataset_fingerprint": version.publication_fingerprint,
            "calendar_version_id": calendar.trading_calendar_version_id,
            "calendar_fingerprint": calendar.fingerprint,
            "schema_version": version.schema_version,
            "normalization_version": version.normalization_version,
            "quality_version": version.quality_rules_version,
        }
        return {
            **payload,
            "created_at": datetime.now(UTC),
            "snapshot_fingerprint": hashlib.sha256(canonical_json_bytes(payload)).hexdigest(),
        }
