from __future__ import annotations

from datetime import date
from decimal import Decimal

from quant_lab.paper.dto import (
    RiskAccountSnapshot,
    RiskMarketContext,
    RiskPolicyView,
    RiskPositionSnapshot,
    RiskReasonCode,
)
from quant_lab.paper.risk import RiskEngine


def _account(**overrides) -> RiskAccountSnapshot:
    values = dict(
        account_id="a",
        status="ACTIVE",
        cash=Decimal("100000"),
        market_value=Decimal("0"),
        account_equity=Decimal("100000"),
        gross_exposure=Decimal("0"),
        daily_loss_ratio=Decimal("0"),
        drawdown_ratio=Decimal("0"),
    )
    values.update(overrides)
    return RiskAccountSnapshot(**values)


def _policy(**overrides) -> RiskPolicyView:
    values = dict(
        policy_id="p",
        version_id="v",
        version=1,
        fingerprint="f" * 64,
        max_single_order_notional=Decimal("10000"),
        max_single_position_weight=Decimal("0.5"),
        max_total_exposure=Decimal("1.0"),
        cash_buffer_ratio=Decimal("0.1"),
        max_daily_loss=Decimal("0.05"),
        max_drawdown=Decimal("0.2"),
        max_open_orders=10,
        allowed_security_types=frozenset({"EQUITY"}),
    )
    values.update(overrides)
    return RiskPolicyView(**values)


def _context(**overrides) -> RiskMarketContext:
    values = dict(
        instrument_id="600000.XSHG",
        security_type="EQUITY",
        reference_price=Decimal("10"),
        estimated_fee=Decimal("0"),
        session_date=date(2026, 1, 2),
    )
    values.update(overrides)
    return RiskMarketContext(**values)


def _evaluate(
    engine,
    *,
    side="BUY",
    quantity=100,
    limit_price=None,
    session_status="RUNNING",
    account=None,
    position=None,
    policy=None,
    context=None,
    open_order_count=0,
):
    return engine.evaluate(
        instrument_id="600000.XSHG",
        side=side,
        quantity=quantity,
        limit_price=limit_price,
        session_status=session_status,
        account_snapshot=account or _account(),
        position_snapshot=position,
        risk_policy=policy or _policy(),
        market_context=context or _context(),
        open_order_count=open_order_count,
    )


def test_clean_intent_approved():
    result = _evaluate(RiskEngine())
    assert result.decision == "APPROVE"
    assert result.reason_codes == ()


def test_frozen_account_rejected():
    result = _evaluate(RiskEngine(), account=_account(status="FROZEN"))
    assert result.decision == "REJECT"
    assert RiskReasonCode.ACCOUNT_FROZEN.value in result.reason_codes


def test_session_not_running_rejected():
    result = _evaluate(RiskEngine(), session_status="PAUSED")
    assert RiskReasonCode.SESSION_NOT_RUNNING.value in result.reason_codes


def test_security_type_denied():
    result = _evaluate(RiskEngine(), context=_context(security_type="ETF"))
    assert RiskReasonCode.SECURITY_NOT_ALLOWED.value in result.reason_codes


def test_order_notional_exceeded():
    result = _evaluate(
        RiskEngine(),
        quantity=2000,
        policy=_policy(max_single_order_notional=Decimal("10000")),
    )
    assert RiskReasonCode.ORDER_NOTIONAL_LIMIT.value in result.reason_codes


def test_cash_buffer_exceeded():
    result = _evaluate(
        RiskEngine(),
        quantity=10000,
        context=_context(reference_price=Decimal("10")),
    )
    assert RiskReasonCode.CASH_BUFFER_LIMIT.value in result.reason_codes


def test_position_concentration_exceeded():
    result = _evaluate(
        RiskEngine(),
        quantity=6000,
        context=_context(reference_price=Decimal("10")),
        position=RiskPositionSnapshot("600000.XSHG", 0, 0, Decimal("0")),
        policy=_policy(max_single_order_notional=Decimal("100000")),
    )
    assert RiskReasonCode.POSITION_CONCENTRATION_LIMIT.value in result.reason_codes


def test_total_exposure_exceeded():
    result = _evaluate(
        RiskEngine(),
        quantity=5000,
        context=_context(reference_price=Decimal("10")),
        account=_account(market_value=Decimal("70000"), gross_exposure=Decimal("70000")),
    )
    assert RiskReasonCode.TOTAL_EXPOSURE_LIMIT.value in result.reason_codes


def test_open_order_limit():
    result = _evaluate(RiskEngine(), open_order_count=10, policy=_policy(max_open_orders=10))
    assert RiskReasonCode.OPEN_ORDER_LIMIT.value in result.reason_codes


def test_daily_loss_limit_freezes():
    result = _evaluate(
        RiskEngine(),
        account=_account(daily_loss_ratio=Decimal("0.06")),
        policy=_policy(max_daily_loss=Decimal("0.05")),
    )
    assert RiskReasonCode.DAILY_LOSS_LIMIT.value in result.reason_codes
    assert result.freeze_required is True


def test_drawdown_limit_freezes():
    result = _evaluate(
        RiskEngine(),
        account=_account(drawdown_ratio=Decimal("0.21")),
        policy=_policy(max_drawdown=Decimal("0.2")),
    )
    assert RiskReasonCode.DRAWDOWN_LIMIT.value in result.reason_codes
    assert result.freeze_required is True


def test_multiple_violations_deterministic_order():
    result = _evaluate(
        RiskEngine(),
        session_status="PAUSED",
        context=_context(security_type="ETF"),
        quantity=2000,
    )
    assert result.decision == "REJECT"
    assert result.reason_codes == (
        RiskReasonCode.SESSION_NOT_RUNNING.value,
        RiskReasonCode.SECURITY_NOT_ALLOWED.value,
        RiskReasonCode.ORDER_NOTIONAL_LIMIT.value,
    )


def test_invalid_context_fail_closed():
    result = _evaluate(RiskEngine(), context=_context(reference_price=Decimal("0")))
    assert result.decision == "REJECT"
    assert result.reason_codes == (RiskReasonCode.RISK_CONTEXT_INVALID.value,)


def test_sell_not_blocked_by_concentration_or_exposure():
    result = _evaluate(
        RiskEngine(),
        side="SELL",
        quantity=100,
        account=_account(market_value=Decimal("90000"), gross_exposure=Decimal("90000")),
        position=RiskPositionSnapshot("600000.XSHG", 9000, 9000, Decimal("90000")),
    )
    assert RiskReasonCode.POSITION_CONCENTRATION_LIMIT.value not in result.reason_codes
    assert RiskReasonCode.TOTAL_EXPOSURE_LIMIT.value not in result.reason_codes


def test_buy_limit_uses_more_conservative_price():
    result = _evaluate(
        RiskEngine(),
        side="BUY",
        quantity=2000,
        limit_price=Decimal("6"),
        context=_context(reference_price=Decimal("10")),
        policy=_policy(max_single_order_notional=Decimal("15000")),
    )
    # notional = 2000 * max(10, 6) = 20000 > 15000
    assert RiskReasonCode.ORDER_NOTIONAL_LIMIT.value in result.reason_codes
