from __future__ import annotations

import csv
import hashlib
from datetime import date, time
from pathlib import Path

from quant_lab.datasets.errors import DatasetError
from quant_lab.market_data.calendar_persistence import (
    TradingCalendarRepository,
    TradingCalendarVersionModel,
)
from quant_lab.market_data.fingerprints import canonical_json_bytes

_HEADERS = ("session_date", "is_open", "open_time", "close_time", "session_type")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class TradingCalendarImportService:
    def __init__(self, repository: TradingCalendarRepository) -> None:
        self.repository = repository

    def import_csv(self, *, calendar_id: str, path: Path) -> TradingCalendarVersionModel:
        calendar = self.repository.get_calendar(calendar_id)
        if not path.is_file():
            raise DatasetError("CALENDAR_SOURCE_NOT_FOUND", "交易日日历文件不存在")
        try:
            with path.open("r", encoding="utf-8-sig", newline="") as stream:
                reader = csv.DictReader(stream)
                if tuple(reader.fieldnames or ()) != _HEADERS:
                    raise DatasetError("CALENDAR_SCHEMA_INVALID", "交易日日历字段无效")
                sessions: list[dict[str, object]] = []
                seen: set[date] = set()
                for row in reader:
                    try:
                        session_date = date.fromisoformat((row["session_date"] or "").strip())
                    except ValueError as exc:
                        raise DatasetError("CALENDAR_DATE_INVALID", "交易日日历日期无效") from exc
                    if session_date in seen:
                        raise DatasetError("CALENDAR_DUPLICATE_DATE", "交易日日历日期重复")
                    seen.add(session_date)
                    raw_open = (row["is_open"] or "").strip().lower()
                    if raw_open not in {"true", "false"}:
                        raise DatasetError("CALENDAR_OPEN_FLAG_INVALID", "交易日日历开市标记无效")
                    is_open = raw_open == "true"
                    open_time = self._parse_time(row["open_time"] or "")
                    close_time = self._parse_time(row["close_time"] or "")
                    if is_open and (open_time is None or close_time is None):
                        raise DatasetError("CALENDAR_TIME_REQUIRED", "开市日必须提供开闭市时间")
                    if not is_open and (open_time is not None or close_time is not None):
                        raise DatasetError("CALENDAR_CLOSED_TIME_INVALID", "休市日不应提供交易时间")
                    session_type = (row["session_type"] or "").strip().upper()
                    if not session_type:
                        raise DatasetError("CALENDAR_SESSION_TYPE_INVALID", "交易日类型不能为空")
                    sessions.append(
                        {
                            "session_date": session_date,
                            "is_open": is_open,
                            "open_time": open_time,
                            "close_time": close_time,
                            "timezone": calendar.timezone,
                            "session_type": session_type,
                        }
                    )
        except UnicodeDecodeError as exc:
            raise DatasetError(
                "CALENDAR_ENCODING_INVALID", "交易日日历必须使用 UTF-8 编码"
            ) from exc
        source_sha256 = _sha256(path)
        payload = {
            "schema_version": "trading-calendar@1",
            "timezone": calendar.timezone,
            "sessions": [self._canonical_session(item) for item in sessions],
        }
        fingerprint = hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
        return self.repository.create_version(
            calendar_id=calendar_id,
            source_sha256=source_sha256,
            schema_version="trading-calendar@1",
            fingerprint=fingerprint,
            sessions=sessions,
        )

    @staticmethod
    def _parse_time(value: str) -> time | None:
        if not value:
            return None
        try:
            parsed = time.fromisoformat(value)
        except ValueError as exc:
            raise DatasetError("CALENDAR_TIME_INVALID", "交易日日历时间无效") from exc
        if parsed.second != 0 or parsed.microsecond != 0:
            raise DatasetError("CALENDAR_TIME_INVALID", "交易日日历时间必须精确到分钟")
        return parsed

    @staticmethod
    def _canonical_session(item: dict[str, object]) -> dict[str, object]:
        return {
            "session_date": item["session_date"].isoformat(),
            "is_open": item["is_open"],
            "open_time": item["open_time"].isoformat() if item["open_time"] else None,
            "close_time": item["close_time"].isoformat() if item["close_time"] else None,
            "timezone": item["timezone"],
            "session_type": item["session_type"],
        }
