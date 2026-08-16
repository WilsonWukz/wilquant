from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from typing import cast

from quant_lab.backtest.artifacts import BacktestArtifactWriter
from quant_lab.backtest.engine import BacktestEngine
from quant_lab.backtest.fingerprints import (
    fingerprint_config,
    fingerprint_run_input,
    fingerprint_strategy,
)
from quant_lab.backtest.repository import BacktestRepository
from quant_lab.backtest.rules import FeePolicy, InstrumentSpec, SlippagePolicy
from quant_lab.backtest.strategies import BuyAndHoldStrategy, TopNMomentumRotationStrategy
from quant_lab.backtest.strategy_library import (
    StrategyLibrary,
    contains_unsafe_spec_key,
)
from quant_lab.datasets.errors import DatasetError

ENGINE_VERSION = "backtest-engine@1"

_FEE_FIELDS = (
    "stock_commission_rate",
    "etf_commission_rate",
    "stock_min_commission",
    "etf_min_commission",
    "stock_stamp_tax_rate",
    "etf_stamp_tax_rate",
    "transfer_fee_rate",
)
_SLIPPAGE_FIELDS = ("buy_bps", "sell_bps")
_STRATEGY_TYPE_ALIASES = {"BuyAndHold": "BUY_AND_HOLD"}


def _fee_policy(config: dict[str, object]) -> FeePolicy:
    raw = cast(dict[str, object], config.get("fee_policy") or {})
    return FeePolicy(**{field: Decimal(str(raw[field])) for field in _FEE_FIELDS if field in raw})


def _slippage_policy(config: dict[str, object]) -> SlippagePolicy:
    raw = cast(dict[str, object], config.get("slippage_policy") or {})
    return SlippagePolicy(
        **{field: Decimal(str(raw[field])) for field in _SLIPPAGE_FIELDS if field in raw}
    )


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
        if strategy_version_id is not None and strategy_spec is not None:
            raise DatasetError("STRATEGY_SOURCE_CONFLICT", "不能同时提供策略版本和内嵌策略配置")
        if strategy_version_id is None and strategy_spec is None:
            raise DatasetError("STRATEGY_SPEC_INVALID", "必须提供策略版本或内嵌策略配置")
        if strategy_version_id is not None:
            version, version_type = StrategyLibrary(self.runs.engine).version(strategy_version_id)
            strategy_type = version_type
            strategy_spec = json.loads(version.strategy_spec_json)
            strategy_fp = version.strategy_fingerprint
        else:
            strategy_type = _STRATEGY_TYPE_ALIASES.get(strategy_type, strategy_type)
            if strategy_type not in StrategyLibrary.allowed_types:
                raise DatasetError("STRATEGY_UNSUPPORTED", "策略类型不受支持")
            if contains_unsafe_spec_key(strategy_spec):
                raise DatasetError("STRATEGY_SPEC_INVALID", "策略配置不允许执行代码")
            strategy_fp = fingerprint_strategy(strategy_type, strategy_spec)
        if initial_cash <= 0 or start_date > end_date:
            raise DatasetError("BACKTEST_CONFIG_INVALID", "回测日期或初始资金无效")
        health = self.market_data.health(market_data_profile_id)
        if health["status"] != "READY":
            raise DatasetError("PROFILE_NOT_READY", "MarketDataProfile未就绪")
        snapshot = self.market_data.snapshot(market_data_profile_id)
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
            strategy = self._build_strategy(strategy_type, strategy_spec, start_date, config)
            bars_by_date = self._load_bars(
                market_data_profile_id, strategy.instruments, start_date, end_date
            )
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
                fee_policy=_fee_policy(config),
                slippage_policy=_slippage_policy(config),
                max_volume_participation=cast(
                    Decimal | None, config.get("max_volume_participation")
                ),
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

    def _build_strategy(self, strategy_type, strategy_spec, start_date, config):
        if strategy_type == "BUY_AND_HOLD":
            instrument = self._instrument_spec(strategy_spec["instrument_id"], strategy_spec)
            return BuyAndHoldStrategy(
                instrument, Decimal(str(strategy_spec.get("target_weight", "1"))), start_date
            )
        if strategy_type == "TOP_N_MOMENTUM_ROTATION":
            instrument_ids = [str(item) for item in strategy_spec["instrument_ids"]]
            overrides = cast(
                dict[str, object], config.get("instrument_metadata_overrides") or {}
            )
            instruments = tuple(
                self._instrument_spec(instrument_id, overrides.get(instrument_id))
                for instrument_id in instrument_ids
            )
            if not instruments:
                raise DatasetError("STRATEGY_SPEC_INVALID", "策略配置没有可用标的")
            return TopNMomentumRotationStrategy(
                instruments=instruments,
                lookback_sessions=int(strategy_spec["lookback_sessions"]),
                rebalance_every_n_sessions=int(strategy_spec["rebalance_every_n_sessions"]),
                top_n=int(strategy_spec["top_n"]),
                target_gross_exposure=Decimal(str(strategy_spec["target_gross_exposure"])),
                minimum_momentum=Decimal(str(strategy_spec.get("minimum_momentum", "0"))),
                cash_reserve_ratio=Decimal(str(strategy_spec.get("cash_reserve_ratio", "0"))),
            )
        raise DatasetError("STRATEGY_UNSUPPORTED", "策略类型不受支持")

    @staticmethod
    def _instrument_spec(instrument_id: object, meta: object) -> InstrumentSpec:
        values = cast(dict[str, object], meta or {})
        return InstrumentSpec(
            str(instrument_id),
            str(values.get("security_type", "EQUITY")),
            int(str(values.get("lot_size", 100))),
            Decimal(str(values.get("price_tick", "0.01"))),
        )

    def _load_bars(self, profile_id, instruments, start_date, end_date):
        instrument_ids = [spec.instrument_id for spec in instruments]
        bars_result = self.market_data.bars(
            profile_id,
            instrument_id=None if len(instrument_ids) > 1 else instrument_ids[0],
            start=start_date,
            end=end_date,
            limit=1000,
        )
        bars_by_date: dict[date, dict[str, dict[str, object]]] = {}
        for row in bars_result["bars"]:
            bars_by_date.setdefault(row["trade_date"], {})[row["instrument_id"]] = row
        return bars_by_date
