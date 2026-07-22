from __future__ import annotations

from pathlib import Path

import pytest

from quant_lab.datasets.errors import DatasetError
from quant_lab.market_data.calendar_service import TradingCalendarImportService

CSV = (
    "session_date,is_open,open_time,close_time,session_type\n"
    "2024-01-01,false,,,HOLIDAY\n"
    "2024-01-02,true,09:30:00,15:00:00,REGULAR\n"
)


def test_local_calendar_csv_import_is_deterministic(repository, tmp_path: Path):
    _engine, calendars = repository
    calendar = calendars.create_calendar(
        name="CN",
        market="CN_A_SHARE",
        exchange="XSHG_XSHE",
        timezone="Asia/Shanghai",
        source_type="LOCAL_CSV",
        source_name="cn.csv",
    )
    path = tmp_path / "calendar.csv"
    path.write_text(CSV, encoding="utf-8")
    service = TradingCalendarImportService(calendars)
    first = service.import_csv(calendar_id=calendar.calendar_id, path=path)
    second = service.import_csv(calendar_id=calendar.calendar_id, path=path)
    assert first.trading_calendar_version_id == second.trading_calendar_version_id
    assert first.fingerprint == second.fingerprint


@pytest.mark.parametrize(
    "content,code",
    [
        (CSV.replace("2024-01-02,true", "2024-01-01,true"), "CALENDAR_DUPLICATE_DATE"),
        (CSV.replace("2024-01-02", "2024-99-99"), "CALENDAR_DATE_INVALID"),
        (CSV.replace("09:30:00", "9:30"), "CALENDAR_TIME_INVALID"),
    ],
)
def test_calendar_csv_rejects_invalid_rows(repository, tmp_path: Path, content: str, code: str):
    _, calendars = repository
    calendar = calendars.create_calendar(
        name="CN",
        market="CN_A_SHARE",
        exchange="XSHG_XSHE",
        timezone="Asia/Shanghai",
        source_type="LOCAL_CSV",
        source_name="cn.csv",
    )
    path = tmp_path / "calendar.csv"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(DatasetError) as error:
        TradingCalendarImportService(calendars).import_csv(
            calendar_id=calendar.calendar_id, path=path
        )
    assert error.value.category == code
