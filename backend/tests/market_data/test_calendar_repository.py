from __future__ import annotations

from datetime import date, time

import pytest
import sqlalchemy as sa
from sqlalchemy import select
from sqlalchemy.orm import Session

from quant_lab.market_data.calendar_persistence import (
    TradingCalendarModel,
    TradingCalendarSessionModel,
    TradingCalendarVersionModel,
)


def test_calendar_repository_creates_version_and_sessions(repository):
    engine, calendars = repository
    calendar = calendars.create_calendar(
        name="CN A Share",
        market="CN_A_SHARE",
        exchange="XSHG_XSHE",
        timezone="Asia/Shanghai",
        source_type="LOCAL_CSV",
        source_name="cn.csv",
    )
    version = calendars.create_version(
        calendar_id=calendar.calendar_id,
        source_sha256="a" * 64,
        schema_version="trading-calendar@1",
        fingerprint="b" * 64,
        sessions=[
            {
                "session_date": date(2024, 1, 1),
                "is_open": False,
                "open_time": None,
                "close_time": None,
                "timezone": "Asia/Shanghai",
                "session_type": "HOLIDAY",
            },
            {
                "session_date": date(2024, 1, 2),
                "is_open": True,
                "open_time": time(9, 30),
                "close_time": time(15, 0),
                "timezone": "Asia/Shanghai",
                "session_type": "REGULAR",
            },
        ],
    )
    assert version.status == "PUBLISHED"
    assert version.session_count == 2
    assert calendars.list_sessions(version.trading_calendar_version_id, open_only=True)[
        0
    ].session_date == date(2024, 1, 2)
    with Session(engine) as session:
        assert session.scalar(select(TradingCalendarModel.calendar_id)) == calendar.calendar_id
        assert session.scalar(select(TradingCalendarVersionModel.status)) == "PUBLISHED"
        assert session.scalar(select(TradingCalendarSessionModel.session_date)) == date(2024, 1, 1)


def test_published_calendar_version_is_immutable(repository):
    engine, calendars = repository
    calendar = calendars.create_calendar(
        name="CN",
        market="CN_A_SHARE",
        exchange="XSHG_XSHE",
        timezone="Asia/Shanghai",
        source_type="LOCAL_CSV",
        source_name="cn.csv",
    )
    version = calendars.create_version(
        calendar_id=calendar.calendar_id,
        source_sha256="c" * 64,
        schema_version="trading-calendar@1",
        fingerprint="d" * 64,
        sessions=[],
    )
    with pytest.raises(sa.exc.IntegrityError), Session(engine) as session:
        model = session.get(TradingCalendarVersionModel, version.trading_calendar_version_id)
        assert model is not None
        model.status = "FAILED"
        session.commit()
