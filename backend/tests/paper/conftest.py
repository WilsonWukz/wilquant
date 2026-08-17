# ruff: noqa: E501

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import text

from alembic import command
from quant_lab.core.config import Settings
from quant_lab.db.sqlite import create_sqlite_engine
from quant_lab.market_data.calendar_persistence import TradingCalendarRepository
from quant_lab.paper.repository import PaperRepository


def _seed_profile(engine) -> str:
    calendars = TradingCalendarRepository(engine)
    calendar = calendars.create_calendar(
        name="CN", market="CN_A_SHARE", exchange="SSE", timezone="Asia/Shanghai",
        source_type="LOCAL_CSV", source_name="calendar.csv",
    )
    version = calendars.create_version(
        calendar_id=calendar.calendar_id,
        source_sha256="a" * 64,
        schema_version="trading-calendar@1",
        fingerprint="b" * 64,
        sessions=[
            {
                "session_date": date(2026, 1, 2),
                "is_open": True,
                "open_time": None,
                "close_time": None,
                "timezone": "Asia/Shanghai",
                "session_type": "REGULAR",
            }
        ],
    )
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO data_sources (source_id,identifier,name,source_type,is_local,version,original_file,created_at) "
                "VALUES ('s','local','bars.csv','LOCAL_CSV',1,'1','bars.csv',CURRENT_TIMESTAMP)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO import_batches (batch_id,data_source_id,provider_name,source_name,source_file,source_file_hash,requested_at,status,row_count,accepted_count,rejected_count,warning_count,schema_version) "
                "VALUES ('b1','s','local','bars.csv','bars.csv',:h,CURRENT_TIMESTAMP,'PREVIEW_READY',1,1,0,0,'market-bar@1')"
            ),
            {"h": "c" * 64},
        )
        connection.execute(
            text(
                "INSERT INTO datasets (dataset_id,dataset_key,logical_key,name,dataset_type,market,frequency,adjustment_type,schema_version,created_at,updated_at,is_active) "
                "VALUES ('d','dk','bars','Bars','MARKET_BARS','CN_A_SHARE','DAILY','NONE','market-bar@1',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP,1)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO dataset_versions (dataset_version_id,dataset_id,version,status,source_batch_id,source_preview_fingerprint,publication_fingerprint,schema_version,normalization_version,quality_rules_version,publication_format_version,partition_strategy_version,row_count,instrument_count,partition_count,file_count,total_size_bytes,quality_issue_count,warning_count,blocking_issue_count,publication_claimed_at,created_at) "
                "VALUES ('v','d',1,'PUBLISHED','b1',:f,:f,'market-bar@1','normalization@1','quality@1','parquet@1','partition@1',1,1,1,1,1,0,0,0,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"
            ),
            {"f": "d" * 64},
        )
        connection.execute(
            text(
                "INSERT INTO market_data_profiles (profile_id,name,market,bar_frequency,bars_dataset_id,bars_dataset_version_id,calendar_id,calendar_version_id,status,created_at,updated_at) "
                "VALUES ('p','p','CN_A_SHARE','DAILY','d','v',:c,:cv,'ACTIVE',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"
            ),
            {"c": calendar.calendar_id, "cv": version.trading_calendar_version_id},
        )
    return "p"


@pytest.fixture
def engine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    settings = Settings(project_root=tmp_path, runtime_root=tmp_path / "runtime")
    monkeypatch.setenv("QUANT_LAB_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("QUANT_LAB_RUNTIME_ROOT", str(settings.runtime_root))
    command.upgrade(Config("backend/alembic.ini"), "head")
    eng = create_sqlite_engine(settings)
    _seed_profile(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def repository(engine):
    return PaperRepository(engine)


def make_account(repository: PaperRepository):
    return repository.create_account(name="acct", initial_cash=Decimal("100000"))
