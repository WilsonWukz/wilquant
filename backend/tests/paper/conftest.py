# ruff: noqa: E501

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from alembic.config import Config
from sqlalchemy import text

from alembic import command
from quant_lab.backtest.strategy_library import StrategyLibrary
from quant_lab.core.config import RunMode, Settings
from quant_lab.datasets.publication import PublicationService
from quant_lab.datasets.query import DatasetQueryService
from quant_lab.datasets.repository import DatasetIdentity, DatasetRepository
from quant_lab.db.sqlite import create_sqlite_engine
from quant_lab.market_data.calendar_persistence import TradingCalendarRepository
from quant_lab.market_data.consumption import MarketDataService
from quant_lab.market_data.profile_persistence import MarketDataProfileRepository
from quant_lab.market_data.providers import DataSourceInput, LocalCsvMarketDataProvider
from quant_lab.market_data.repository import MarketDataRepository
from quant_lab.market_data.service import MarketDataImportService
from quant_lab.market_data.staging import ControlledUploadStore
from quant_lab.paper.repository import PaperRepository
from quant_lab.paper.risk import RiskEngine
from quant_lab.paper.risk_service import PaperRiskService
from quant_lab.paper.service import PaperSessionService


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

BARS_CSV = (
    b"symbol,exchange,trade_date,open,high,low,close,volume,amount\n"
    b"600000,XSHG,2026-01-02,10.0,10.5,9.8,10.2,100000,1020000\n"
    b"600000,XSHG,2026-01-05,10.2,10.7,10.0,10.4,100000,1040000\n"
    b"600000,XSHG,2026-01-06,10.4,10.9,10.2,10.6,100000,1060000\n"
    b"600000,XSHG,2026-01-07,10.6,11.1,10.4,10.8,100000,1080000\n"
    b"000001,XSHE,2026-01-02,20.0,20.5,19.8,20.2,100000,2020000\n"
    b"000001,XSHE,2026-01-05,20.2,20.7,20.0,20.4,100000,2040000\n"
)

BARS_MAPPING = {
    name: name
    for name in ("symbol", "exchange", "trade_date", "open", "high", "low", "close", "volume", "amount")
}

OPEN_DATES = [date(2026, 1, 2), date(2026, 1, 5), date(2026, 1, 6), date(2026, 1, 7)]


def _calendar_sessions() -> list[dict[str, object]]:
    sessions: list[dict[str, object]] = []
    for session_date in OPEN_DATES:
        sessions.append(
            {
                "session_date": session_date,
                "is_open": True,
                "open_time": None,
                "close_time": None,
                "timezone": "Asia/Shanghai",
                "session_type": "REGULAR",
            }
        )
    sessions.insert(
        1,
        {
            "session_date": date(2026, 1, 3),
            "is_open": False,
            "open_time": None,
            "close_time": None,
            "timezone": "Asia/Shanghai",
            "session_type": "CLOSED",
        },
    )
    return sessions


@pytest.fixture
def paper_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    settings = Settings(project_root=tmp_path, runtime_root=tmp_path / "runtime")
    monkeypatch.setenv("QUANT_LAB_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("QUANT_LAB_RUNTIME_ROOT", str(settings.runtime_root))
    command.upgrade(Config("backend/alembic.ini"), "head")
    engine = create_sqlite_engine(settings)

    calendars = TradingCalendarRepository(engine)
    calendar = calendars.create_calendar(
        name="CN",
        market="CN_A_SHARE",
        exchange="SSE",
        timezone="Asia/Shanghai",
        source_type="LOCAL_CSV",
        source_name="calendar.csv",
    )
    calendar_version = calendars.create_version(
        calendar_id=calendar.calendar_id,
        source_sha256="a" * 64,
        schema_version="trading-calendar@1",
        fingerprint="b" * 64,
        sessions=_calendar_sessions(),
    )

    store = ControlledUploadStore(settings.import_directory, settings.import_max_bytes)
    upload = store.stage("bars.csv", [BARS_CSV])
    provider = LocalCsvMarketDataProvider()
    mrepo = MarketDataRepository(engine)
    batch = mrepo.create_inspection(
        upload,
        provider.inspect(DataSourceInput(upload.path, upload.original_filename, upload.sha256)),
    )
    importer = MarketDataImportService(mrepo, settings.import_directory, 10)
    importer.preview(batch.batch_id, BARS_MAPPING)
    drepo = DatasetRepository(engine, run_mode=RunMode.RESEARCH)
    dataset = drepo.create_or_get(
        DatasetIdentity("bars", "MARKET_BARS", "CN_A_SHARE", "DAILY", "NONE", "market-bar@1"),
        name="Bars",
        description=None,
    ).dataset
    published = PublicationService(drepo, mrepo, settings).publish(
        dataset_id=dataset.dataset_id,
        batch_id=batch.batch_id,
        expected_preview_fingerprint=mrepo.get_batch(batch.batch_id).preview_fingerprint,
        confirm_warnings=False,
        request_id="seed-1",
    )

    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO market_data_profiles (profile_id,name,market,bar_frequency,"
                "bars_dataset_id,bars_dataset_version_id,calendar_id,calendar_version_id,"
                "status,created_at,updated_at) VALUES "
                "('p','p','CN_A_SHARE','DAILY',:d,:v,:c,:cv,'ACTIVE',"
                "CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"
            ),
            {
                "d": dataset.dataset_id,
                "v": published.dataset_version_id,
                "c": calendar.calendar_id,
                "cv": calendar_version.trading_calendar_version_id,
            },
        )
        connection.execute(
            text(
                "INSERT INTO instruments (instrument_id,symbol,exchange,name,instrument_type,"
                "currency,lot_size,price_tick,is_st,supports_t0,data_source,created_at,"
                "updated_at) VALUES "
                "('600000.XSHG','600000','XSHG','Test','EQUITY','CNY',100,0.01,0,0,"
                "'local',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP),"
                "('000001.XSHE','000001','XSHE','Test2','EQUITY','CNY',100,0.01,0,0,"
                "'local',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"
            )
        )

    dataset_query = DatasetQueryService(drepo, settings.published_directory)
    market_data = MarketDataService(
        MarketDataProfileRepository(engine), calendars, dataset_query, engine
    )
    repository = PaperRepository(engine)
    risk_service = PaperRiskService(repository, RiskEngine())
    session_service = PaperSessionService(
        engine, repository, market_data, calendars, dataset_query, risk_service
    )

    yield SimpleNamespace(
        engine=engine,
        settings=settings,
        repository=repository,
        market_data=market_data,
        calendars=calendars,
        dataset_query=dataset_query,
        risk_service=risk_service,
        session_service=session_service,
        profile_id="p",
        calendar_id=calendar.calendar_id,
        calendar_version_id=calendar_version.trading_calendar_version_id,
        dataset_id=dataset.dataset_id,
        dataset_version_id=published.dataset_version_id,
        open_dates=list(OPEN_DATES),
    )
    engine.dispose()


def make_buy_and_hold_strategy(engine, *, instrument_id: str = "600000.XSHG") -> str:
    library = StrategyLibrary(engine)
    definition = library.create_definition(
        name="BuyAndHold", description="buy and hold", strategy_type="BUY_AND_HOLD"
    )
    version = library.create_version(
        definition.id,
        {"instrument_id": instrument_id, "target_weight": "1"},
        "v1",
    )
    return version.id
