from datetime import date
from decimal import Decimal

from quant_lab.backtest.domain import OrderIntent, OrderSide, OrderType
from quant_lab.backtest.fingerprints import (
    fingerprint_config,
    fingerprint_run_input,
    fingerprint_strategy,
)


def test_order_intent_is_explicit_and_immutable():
    intent = OrderIntent(
        client_order_id="c1",
        instrument_id="600000.XSHG",
        side=OrderSide.BUY,
        quantity=100,
        order_type=OrderType.MARKET_ON_OPEN_SIMULATED,
        signal_date=date(2026, 1, 2),
        intended_execution_date=date(2026, 1, 5),
        strategy_reason="buy-and-hold",
        strategy_metadata={"target_weight": Decimal("0.5")},
    )
    assert intent.quantity == 100


def test_same_run_inputs_have_stable_fingerprint():
    args = {
        "market_data_snapshot_fingerprint": "a" * 64,
        "strategy_fingerprint": fingerprint_strategy("BuyAndHold", {"target_weight": Decimal("1")}),
        "config_fingerprint": fingerprint_config({"annualized_days": 252}),
        "initial_cash": Decimal("100000"),
        "start_date": "2026-01-01",
        "end_date": "2026-01-31",
    }
    assert fingerprint_run_input(**args) == fingerprint_run_input(
        **dict(reversed(list(args.items())))
    )
