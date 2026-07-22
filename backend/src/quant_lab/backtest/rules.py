from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_DOWN, ROUND_UP, Decimal

from quant_lab.backtest.domain import PositionLot


class BacktestRuleError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class InstrumentSpec:
    instrument_id: str
    security_type: str
    lot_size: int
    price_tick: Decimal
    currency: str = "CNY"


@dataclass(frozen=True, slots=True)
class FeePolicy:
    stock_commission_rate: Decimal = Decimal("0.0003")
    etf_commission_rate: Decimal = Decimal("0.0003")
    stock_min_commission: Decimal = Decimal("5")
    etf_min_commission: Decimal = Decimal("5")
    stock_stamp_tax_rate: Decimal = Decimal("0.0005")
    etf_stamp_tax_rate: Decimal = Decimal("0")
    transfer_fee_rate: Decimal = Decimal("0.00001")


@dataclass(frozen=True, slots=True)
class SlippagePolicy:
    buy_bps: Decimal = Decimal("0")
    sell_bps: Decimal = Decimal("0")


def round_price(price: Decimal, tick: Decimal, *, direction: str) -> Decimal:
    if price <= 0 or tick <= 0:
        raise BacktestRuleError("PRICE_INVALID", "价格和最小价位必须为正")
    units = price / tick
    rounding = ROUND_UP if direction == "UP" else ROUND_DOWN
    return (units.quantize(Decimal("1"), rounding=rounding) * tick).quantize(tick)


def round_lot(quantity: int, lot_size: int) -> int:
    if lot_size <= 0:
        raise BacktestRuleError("LOT_SIZE_INVALID", "最小交易单位必须为正")
    return quantity - quantity % lot_size


def validate_quantity(quantity: int, *, side: str, lot_size: int) -> int:
    if quantity <= 0:
        raise BacktestRuleError("QUANTITY_INVALID", "数量必须为正")
    rounded = round_lot(quantity, lot_size)
    if rounded < lot_size:
        raise BacktestRuleError("QUANTITY_BELOW_LOT", "数量低于一手")
    if side == "BUY" and rounded != quantity:
        raise BacktestRuleError("QUANTITY_NOT_LOT_ALIGNED", "买入数量必须按一手取整")
    return rounded


def sellable_quantity(lots: tuple[PositionLot, ...], instrument_id: str, trade_date: date) -> int:
    return sum(
        lot.remaining_quantity
        for lot in lots
        if lot.instrument_id == instrument_id and lot.sellable_from_date <= trade_date
    )


def validate_sell_quantity(
    lots: tuple[PositionLot, ...], instrument_id: str, quantity: int, trade_date: date
) -> int:
    if quantity <= 0:
        raise BacktestRuleError("QUANTITY_INVALID", "数量必须为正")
    available = sellable_quantity(lots, instrument_id, trade_date)
    if quantity > available:
        raise BacktestRuleError("T1_SELL_RESTRICTED", "卖出数量超过可卖T+1持仓")
    return quantity


def apply_slippage(
    price: Decimal, policy: SlippagePolicy, *, side: str, tick: Decimal
) -> tuple[Decimal, Decimal]:
    rate = (
        policy.buy_bps / Decimal("10000") if side == "BUY" else policy.sell_bps / Decimal("10000")
    )
    raw = price * (Decimal("1") + rate if side == "BUY" else Decimal("1") - rate)
    adjusted = round_price(raw, tick, direction="UP" if side == "BUY" else "DOWN")
    return adjusted, adjusted - price


def calculate_fees(
    *, security_type: str, side: str, quantity: int, price: Decimal, policy: FeePolicy
) -> tuple[Decimal, Decimal, Decimal, Decimal]:
    amount = quantity * price
    is_etf = security_type == "ETF"
    commission = max(
        amount * (policy.etf_commission_rate if is_etf else policy.stock_commission_rate),
        policy.etf_min_commission if is_etf else policy.stock_min_commission,
    )
    stamp = (
        amount * (policy.etf_stamp_tax_rate if is_etf else policy.stock_stamp_tax_rate)
        if side == "SELL"
        else Decimal("0")
    )
    transfer = amount * policy.transfer_fee_rate
    return commission, stamp, transfer, commission + stamp + transfer


def validate_execution_price(
    price: Decimal, *, limit_up: Decimal | None, limit_down: Decimal | None, side: str
) -> None:
    if price <= 0:
        raise BacktestRuleError("PRICE_INVALID", "成交价必须为正")
    if side == "BUY" and limit_up is not None and price >= limit_up:
        raise BacktestRuleError("LIMIT_UP_REJECTED", "涨停价不可买入成交")
    if side == "SELL" and limit_down is not None and price <= limit_down:
        raise BacktestRuleError("LIMIT_DOWN_REJECTED", "跌停价不可卖出成交")
