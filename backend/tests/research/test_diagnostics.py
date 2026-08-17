from __future__ import annotations

from datetime import date
from decimal import Decimal

from quant_lab.backtest.engine import BacktestEngine
from quant_lab.backtest.rules import FeePolicy, InstrumentSpec, SlippagePolicy
from quant_lab.backtest.strategies import BuyAndHoldStrategy

from .conftest import make_succeeded_run


def test_diagnostics_are_deterministic(research_context):
    run = make_succeeded_run(research_context, name="diag-det")
    artifacts = research_context["backtest_repo"].artifacts(run.backtest_run_id)
    first = research_context["diagnostics"].compute(run, artifacts)
    second = research_context["diagnostics"].compute(run, artifacts)
    assert first == second
    assert first["policy_version"] == "1"
    assert set(first) == {
        "run_id",
        "policy_version",
        "summary",
        "diagnostics",
        "execution",
        "portfolio",
        "cost",
        "data_quality",
    }


def test_low_trade_count_diagnostic(research_context):
    run = make_succeeded_run(research_context, name="diag-low")
    artifacts = research_context["backtest_repo"].artifacts(run.backtest_run_id)
    result = research_context["diagnostics"].compute(run, artifacts)
    codes = [d["code"] for d in result["diagnostics"]]
    assert "LOW_TRADE_COUNT" in codes


def test_fee_drag_diagnostic(research_context):
    run = make_succeeded_run(
        research_context,
        name="diag-fee",
        fee_policy=FeePolicy(stock_commission_rate=Decimal("0.05")),
    )
    artifacts = research_context["backtest_repo"].artifacts(run.backtest_run_id)
    result = research_context["diagnostics"].compute(run, artifacts)
    assert result["cost"]["fees_to_initial_cash"] is not None


def test_partial_fill_diagnostic(research_context):
    runs = research_context["backtest_repo"]
    writer = research_context["writer"]
    instrument = InstrumentSpec("600000.XSHG", "EQUITY", 100, Decimal("0.01"))
    strategy = BuyAndHoldStrategy(instrument, Decimal("0.1"), date(2026, 1, 1))
    bars = {
        date(2026, 1, 2): {"600000.XSHG": {"open": Decimal("10"), "close": Decimal("10")}},
        date(2026, 1, 5): {
            "600000.XSHG": {
                "open": Decimal("10"),
                "close": Decimal("10"),
                "volume": Decimal("1500"),
            }
        },
    }
    result = BacktestEngine().run(
        sessions=(date(2026, 1, 2), date(2026, 1, 5)),
        bars_by_date=bars,
        strategy=strategy,
        initial_cash=Decimal("100000"),
        fee_policy=FeePolicy(),
        slippage_policy=SlippagePolicy(),
        max_volume_participation=Decimal("0.5"),
    )
    import hashlib
    import json

    run = runs.claim(
        name="diag-partial",
        market_data_profile_id="p",
        market_data_snapshot_json=json.dumps(
            {"bars_dataset_version_id": "v", "calendar_version_id": "cv"}
        ),
        market_data_snapshot_fingerprint="a" * 64,
        strategy_type="BUY_AND_HOLD",
        strategy_spec_json="{}",
        strategy_fingerprint="b" * 64,
        engine_version="backtest-engine@1",
        config_json=json.dumps(
            {
                "fee_policy": {},
                "slippage_policy": {},
                "max_volume_participation": "0.5",
                "instrument_metadata_overrides": {},
            }
        ),
        config_fingerprint="c" * 64,
        run_input_fingerprint=hashlib.sha256(b"diag-partial").hexdigest(),
        initial_cash=Decimal("100000"),
        start_date=date(2026, 1, 2),
        end_date=date(2026, 1, 5),
    )
    runs.mark_running(run.backtest_run_id)
    manifest, artifacts = writer.write(
        run_id=run.backtest_run_id, result=result, run_metadata={"config": {}}
    )
    runs.add_artifacts(run.backtest_run_id, artifacts)
    run = runs.mark_succeeded(run.backtest_run_id, manifest)
    artifacts = runs.artifacts(run.backtest_run_id)
    diagnostics = research_context["diagnostics"].compute(run, artifacts)
    assert diagnostics["execution"]["partial_fill_count"] == 1
    assert diagnostics["execution"]["volume_participation_trigger_count"] == 1
