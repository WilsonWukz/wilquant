# ruff: noqa: E501

from __future__ import annotations

import hashlib
import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import text

from alembic import command
from quant_lab.backtest.artifacts import BacktestArtifactWriter
from quant_lab.backtest.engine import BacktestEngine
from quant_lab.backtest.repository import BacktestRepository
from quant_lab.backtest.rules import FeePolicy, InstrumentSpec, SlippagePolicy
from quant_lab.backtest.strategies import BuyAndHoldStrategy
from quant_lab.backtest.strategy_library import StrategyLibrary
from quant_lab.core.config import Settings
from quant_lab.db.sqlite import create_sqlite_engine
from quant_lab.market_data.calendar_persistence import TradingCalendarRepository
from quant_lab.research.artifacts import ArtifactReader
from quant_lab.research.comparability import (
    BacktestComparabilityService,
    BacktestComparisonService,
)
from quant_lab.research.diagnostics import ResearchDiagnosticsService
from quant_lab.research.reports import ResearchReportService
from quant_lab.research.repository import ResearchRepository


def _seed_profile(engine) -> str:
    calendars = TradingCalendarRepository(engine)
    calendar = calendars.create_calendar(
        name="CN",
        market="CN_A_SHARE",
        exchange="SSE",
        timezone="Asia/Shanghai",
        source_type="LOCAL_CSV",
        source_name="calendar.csv",
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
def research_context(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    settings = Settings(project_root=tmp_path, runtime_root=tmp_path / "runtime")
    monkeypatch.setenv("QUANT_LAB_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("QUANT_LAB_RUNTIME_ROOT", str(settings.runtime_root))
    command.upgrade(Config("backend/alembic.ini"), "head")
    engine = create_sqlite_engine(settings)
    _seed_profile(engine)
    research_repo = ResearchRepository(engine)
    backtest_repo = BacktestRepository(engine)
    reader = ArtifactReader(settings.runtime_root)
    comparability = BacktestComparabilityService()
    comparison = BacktestComparisonService(
        backtest_repo, reader, StrategyLibrary(engine), comparability
    )
    diagnostics = ResearchDiagnosticsService(reader)
    reports = ResearchReportService(backtest_repo, reader, diagnostics, research_repo)
    writer = BacktestArtifactWriter(settings.runtime_root or settings.project_root)
    yield {
        "engine": engine,
        "settings": settings,
        "research_repo": research_repo,
        "backtest_repo": backtest_repo,
        "reader": reader,
        "comparability": comparability,
        "comparison": comparison,
        "diagnostics": diagnostics,
        "reports": reports,
        "writer": writer,
        "strategy_library": StrategyLibrary(engine),
    }
    engine.dispose()


def make_succeeded_run(
    context, *, name, fee_policy=None, slippage_policy=None, initial_cash=Decimal("100000")
):
    runs = context["backtest_repo"]
    writer = context["writer"]
    instrument = InstrumentSpec("600000.XSHG", "EQUITY", 100, Decimal("0.01"))
    strategy = BuyAndHoldStrategy(instrument, Decimal("0.1"), date(2026, 1, 1))
    bars = {
        date(2026, 1, 2): {"600000.XSHG": {"open": Decimal("10"), "close": Decimal("10")}},
        date(2026, 1, 5): {"600000.XSHG": {"open": Decimal("10"), "close": Decimal("11")}},
        date(2026, 1, 6): {"600000.XSHG": {"open": Decimal("11"), "close": Decimal("12")}},
    }
    result = BacktestEngine().run(
        sessions=(date(2026, 1, 2), date(2026, 1, 5), date(2026, 1, 6)),
        bars_by_date=bars,
        strategy=strategy,
        initial_cash=initial_cash,
        fee_policy=fee_policy or FeePolicy(),
        slippage_policy=slippage_policy or SlippagePolicy(),
    )
    config = {
        "fee_policy": {},
        "slippage_policy": {},
        "max_volume_participation": None,
        "instrument_metadata_overrides": {},
    }
    run = runs.claim(
        name=name,
        market_data_profile_id="p",
        market_data_snapshot_json=json.dumps(
            {"bars_dataset_version_id": "v", "calendar_version_id": "cv"}
        ),
        market_data_snapshot_fingerprint="a" * 64,
        strategy_type="BUY_AND_HOLD",
        strategy_spec_json="{}",
        strategy_fingerprint="b" * 64,
        engine_version="backtest-engine@1",
        config_json=json.dumps(config),
        config_fingerprint="c" * 64,
        run_input_fingerprint=hashlib.sha256(name.encode()).hexdigest(),
        initial_cash=initial_cash,
        start_date=date(2026, 1, 2),
        end_date=date(2026, 1, 6),
    )
    runs.mark_running(run.backtest_run_id)
    manifest, artifacts = writer.write(
        run_id=run.backtest_run_id,
        result=result,
        run_metadata={"engine_version": "backtest-engine@1", "config": config},
    )
    runs.add_artifacts(run.backtest_run_id, artifacts)
    return runs.mark_succeeded(run.backtest_run_id, manifest)
