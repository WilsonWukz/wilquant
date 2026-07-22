# ruff: noqa: E501

from datetime import date
from decimal import Decimal

import pytest
import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.orm import Session

from quant_lab.backtest.persistence import BacktestRunModel
from quant_lab.backtest.repository import BacktestRepository


def test_claim_is_idempotent_and_succeeded_run_is_immutable(repository):
    engine, calendars = repository
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
                "INSERT INTO data_sources (source_id,identifier,name,source_type,is_local,version,original_file,created_at) VALUES ('s','local','bars.csv','LOCAL_CSV',1,'1','bars.csv',CURRENT_TIMESTAMP)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO import_batches (batch_id,data_source_id,provider_name,source_name,source_file,source_file_hash,requested_at,status,row_count,accepted_count,rejected_count,warning_count,schema_version) VALUES ('b1','s','local','bars.csv','bars.csv',:h,CURRENT_TIMESTAMP,'PREVIEW_READY',1,1,0,0,'market-bar@1')"
            ),
            {"h": "c" * 64},
        )
        connection.execute(
            text(
                "INSERT INTO datasets (dataset_id,dataset_key,logical_key,name,dataset_type,market,frequency,adjustment_type,schema_version,created_at,updated_at,is_active) VALUES ('d','dk','bars','Bars','MARKET_BARS','CN_A_SHARE','DAILY','NONE','market-bar@1',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP,1)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO dataset_versions (dataset_version_id,dataset_id,version,status,source_batch_id,source_preview_fingerprint,publication_fingerprint,schema_version,normalization_version,quality_rules_version,publication_format_version,partition_strategy_version,row_count,instrument_count,partition_count,file_count,total_size_bytes,quality_issue_count,warning_count,blocking_issue_count,publication_claimed_at,created_at) VALUES ('v','d',1,'PUBLISHED','b1',:f,:f,'market-bar@1','normalization@1','quality@1','parquet@1','partition@1',1,1,1,1,1,0,0,0,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"
            ),
            {"f": "d" * 64},
        )
        connection.execute(
            text(
                "INSERT INTO market_data_profiles (profile_id,name,market,bar_frequency,bars_dataset_id,bars_dataset_version_id,calendar_id,calendar_version_id,status,created_at,updated_at) VALUES ('p','p','CN_A_SHARE','DAILY','d','v',:c,:cv,'ACTIVE',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"
            ),
            {"c": calendar.calendar_id, "cv": calendar_version.trading_calendar_version_id},
        )
    runs = BacktestRepository(engine)
    kwargs = dict(
        name="run",
        market_data_profile_id="p",
        market_data_snapshot_json="{}",
        market_data_snapshot_fingerprint="a" * 64,
        strategy_type="BuyAndHold",
        strategy_spec_json="{}",
        strategy_fingerprint="b" * 64,
        engine_version="backtest@1",
        config_json="{}",
        config_fingerprint="c" * 64,
        run_input_fingerprint="d" * 64,
        initial_cash=Decimal("100000"),
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 31),
    )
    first = runs.claim(**kwargs)
    second = runs.claim(**kwargs)
    assert second.backtest_run_id == first.backtest_run_id
    runs.mark_succeeded(first.backtest_run_id, "backtests/x/manifest.json")
    with pytest.raises(sa.exc.IntegrityError), Session(engine) as session:
        model = session.get(BacktestRunModel, first.backtest_run_id)
        assert model is not None
        model.name = "mutated"
        session.commit()
