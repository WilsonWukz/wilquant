from __future__ import annotations

import json
from datetime import date
from decimal import Decimal

from quant_lab.backtest.artifacts import BacktestArtifactWriter
from quant_lab.backtest.engine import BacktestEngine
from quant_lab.backtest.fingerprints import (
    fingerprint_config,
    fingerprint_run_input,
    fingerprint_strategy,
)
from quant_lab.backtest.repository import BacktestRepository
from quant_lab.backtest.rules import FeePolicy, InstrumentSpec, SlippagePolicy
from quant_lab.backtest.strategies import BuyAndHoldStrategy
from quant_lab.backtest.strategy_library import StrategyLibrary
from quant_lab.datasets.errors import DatasetError

ENGINE_VERSION = "backtest-engine@1"


class BacktestService:
    def __init__(
        self,
        repository,
        market_data_service,
        calendar_repository,
        run_repository: BacktestRepository,
        settings,
    ) -> None:
        self.profiles = repository
        self.market_data = market_data_service
        self.calendars = calendar_repository
        self.runs = run_repository
        self.settings = settings
        self.engine = BacktestEngine()
        self.writer = BacktestArtifactWriter(settings.runtime_root or settings.project_root)

    def create_run(
        self,
        *,
        name: str,
        market_data_profile_id: str,
        strategy_type: str,
        strategy_spec: dict[str, object],
        strategy_version_id: str | None = None,
        start_date: date,
        end_date: date,
        initial_cash: Decimal,
        config: dict[str, object],
    ) -> object:
        if strategy_version_id and strategy_spec:
            raise DatasetError("STRATEGY_SOURCE_CONFLICT", "不能同时提供策略版本和内嵌策略配置")
        if not strategy_version_id and strategy_spec is None:
            raise DatasetError("STRATEGY_SPEC_INVALID", "必须提供策略配置")
        if strategy_version_id:
            version, version_type = StrategyLibrary(self.runs.engine).version(strategy_version_id)
            strategy_spec = json.loads(version.strategy_spec_json)
            strategy_type = {"BUY_AND_HOLD": "BuyAndHold"}.get(version_type, version_type)
        if strategy_type != "BuyAndHold":
            raise DatasetError("STRATEGY_UNSUPPORTED", "当前仅支持内置BuyAndHold策略")
        if initial_cash <= 0 or start_date > end_date:
            raise DatasetError("BACKTEST_CONFIG_INVALID", "回测日期或初始资金无效")
        health = self.market_data.health(market_data_profile_id)
        if health["status"] != "READY":
            raise DatasetError("PROFILE_NOT_READY", "MarketDataProfile未就绪")
        snapshot = self.market_data.snapshot(market_data_profile_id)
        strategy_fp = fingerprint_strategy(strategy_type, strategy_spec)
        config_fp = fingerprint_config(config)
        run_fp = fingerprint_run_input(
            market_data_snapshot_fingerprint=str(snapshot["snapshot_fingerprint"]),
            strategy_fingerprint=str(strategy_fp),
            config_fingerprint=str(config_fp),
            initial_cash=initial_cash,
            start_date=start_date.isoformat(),
            end_date=end_date.isoformat(),
        )
        run = self.runs.claim(
            name=name,
            market_data_profile_id=market_data_profile_id,
            market_data_snapshot_json=json.dumps(snapshot, sort_keys=True, default=str),
            market_data_snapshot_fingerprint=str(snapshot["snapshot_fingerprint"]),
            strategy_type=strategy_type,
            strategy_version_id=strategy_version_id,
            strategy_spec_json=json.dumps(strategy_spec, sort_keys=True, default=str),
            strategy_fingerprint=str(strategy_fp),
            engine_version=ENGINE_VERSION,
            config_json=json.dumps(config, sort_keys=True, default=str),
            config_fingerprint=str(config_fp),
            run_input_fingerprint=run_fp,
            initial_cash=initial_cash,
            start_date=start_date,
            end_date=end_date,
        )
        if run.status == "SUCCEEDED":
            return run
        self.runs.mark_running(run.backtest_run_id)
        try:
            instrument_id = str(strategy_spec["instrument_id"])
            instrument = InstrumentSpec(
                instrument_id,
                str(strategy_spec.get("security_type", "EQUITY")),
                int(str(strategy_spec.get("lot_size", 100))),
                Decimal(str(strategy_spec.get("price_tick", "0.01"))),
            )
            strategy = BuyAndHoldStrategy(
                instrument, Decimal(str(strategy_spec.get("target_weight", "1"))), start_date
            )
            bars_result = self.market_data.bars(
                market_data_profile_id,
                instrument_id=instrument_id,
                start=start_date,
                end=end_date,
                limit=5000,
            )
            bars_by_date = {row["trade_date"]: row for row in bars_result["bars"]}
            profile = self.profiles.get(market_data_profile_id)
            calendar = self.calendars.get_version(profile.calendar_id, profile.calendar_version_id)
            sessions = tuple(
                item.session_date
                for item in self.calendars.list_sessions(
                    calendar.trading_calendar_version_id,
                    open_only=True,
                    start=start_date,
                    end=end_date,
                    limit=5000,
                )
            )
            result = self.engine.run(
                sessions=sessions,
                bars_by_date=bars_by_date,
                strategy=strategy,
                initial_cash=initial_cash,
                fee_policy=FeePolicy(),
                slippage_policy=SlippagePolicy(),
            )
            manifest_path, artifacts = self.writer.write(
                run_id=run.backtest_run_id,
                result=result,
                run_metadata={
                    "engine_version": ENGINE_VERSION,
                    "market_data_snapshot": snapshot,
                    "strategy_type": strategy_type,
                    "strategy_spec": strategy_spec,
                    "config": config,
                    "initial_cash": initial_cash,
                    "start_date": start_date,
                    "end_date": end_date,
                },
            )
            self.runs.add_artifacts(run.backtest_run_id, artifacts)
            return self.runs.mark_succeeded(run.backtest_run_id, manifest_path)
        except DatasetError as error:
            self.runs.mark_failed(run.backtest_run_id, error.category, error.safe_message)
            raise
        except Exception as error:
            self.runs.mark_failed(run.backtest_run_id, "BACKTEST_FAILED", "回测执行失败")
            raise DatasetError("BACKTEST_FAILED", "回测执行失败") from error
