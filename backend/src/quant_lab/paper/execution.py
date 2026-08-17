from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from quant_lab.backtest.rules import FeePolicy, InstrumentSpec, SlippagePolicy
from quant_lab.execution.kernel import ExecutionKernel, ExecutionRequest
from quant_lab.execution.lots import (
    LotConsumption,
    LotSnapshot,
    plan_sell_lot_consumption,
    realized_cost_basis,
)
from quant_lab.paper.errors import PaperError


@dataclass(frozen=True, slots=True)
class PaperOrderSnapshot:
    order_id: str
    instrument_id: str
    side: str
    requested_quantity: int
    order_type: str
    limit_price: Decimal | None
    risk_decision: str


@dataclass(frozen=True, slots=True)
class NewLot:
    instrument_id: str
    quantity: int
    cost_price: Decimal
    acquired_date: date
    sellable_from_date: date


@dataclass(frozen=True, slots=True)
class PaperExecutionRequest:
    order: PaperOrderSnapshot
    cash: Decimal
    lots: tuple[LotSnapshot, ...]
    instrument: InstrumentSpec
    bar: dict[str, object] | None
    fee_policy: FeePolicy
    slippage_policy: SlippagePolicy
    max_volume_participation: Decimal | None
    execution_date: date
    sellable_from_date: date


@dataclass(frozen=True, slots=True)
class PaperExecutionResult:
    status: str
    requested_quantity: int
    accepted_quantity: int
    filled_quantity: int
    remaining_quantity: int
    raw_price: Decimal | None
    slippage: Decimal
    fill_price: Decimal | None
    commission: Decimal
    stamp_tax: Decimal
    transfer_fee: Decimal
    total_fee: Decimal
    cash_delta: Decimal
    reject_reason: str | None
    new_lot: NewLot | None
    lot_consumptions: tuple[LotConsumption, ...]
    realized_pnl_delta: Decimal | None


class PaperExecutionEngine:
    """Pure execution adapter over the shared ExecutionKernel.

    No DB, no RiskEngine, no session-advance. It only computes the execution
    outcome and the position/lot delta information that 5D will persist.
    """

    def execute(self, request: PaperExecutionRequest) -> PaperExecutionResult:
        if request.order.risk_decision != "APPROVE":
            raise PaperError("RISK_DECISION_NOT_APPROVED", "订单未通过风控")
        sellable = sum(
            lot.remaining_quantity
            for lot in request.lots
            if lot.sellable_from_date <= request.execution_date
        )
        kernel_request = ExecutionRequest(
            instrument_id=request.order.instrument_id,
            side=request.order.side,
            requested_quantity=request.order.requested_quantity,
            order_type=request.order.order_type,
            limit_price=request.order.limit_price,
            execution_date=request.execution_date,
            cash=request.cash,
            sellable_quantity=sellable,
            instrument=request.instrument,
            bar=request.bar,
            fee_policy=request.fee_policy,
            slippage_policy=request.slippage_policy,
            max_volume_participation=request.max_volume_participation,
        )
        kernel_result = ExecutionKernel().execute(kernel_request)

        new_lot: NewLot | None = None
        lot_consumptions: tuple[LotConsumption, ...] = ()
        realized_pnl: Decimal | None = None
        if kernel_result.filled_quantity > 0:
            if request.order.side == "BUY":
                new_lot = NewLot(
                    instrument_id=request.order.instrument_id,
                    quantity=kernel_result.filled_quantity,
                    cost_price=kernel_result.fill_price or Decimal("0"),
                    acquired_date=request.execution_date,
                    sellable_from_date=request.sellable_from_date,
                )
            else:
                consumptions = plan_sell_lot_consumption(
                    request.lots, kernel_result.filled_quantity
                )
                lot_consumptions = consumptions
                proceeds = Decimal(kernel_result.filled_quantity) * (
                    kernel_result.fill_price or Decimal("0")
                )
                realized_pnl = (
                    proceeds - realized_cost_basis(consumptions) - kernel_result.total_fee
                )

        return PaperExecutionResult(
            status=kernel_result.status,
            requested_quantity=kernel_result.requested_quantity,
            accepted_quantity=kernel_result.accepted_quantity,
            filled_quantity=kernel_result.filled_quantity,
            remaining_quantity=kernel_result.remaining_quantity,
            raw_price=kernel_result.raw_price,
            slippage=kernel_result.slippage,
            fill_price=kernel_result.fill_price,
            commission=kernel_result.commission,
            stamp_tax=kernel_result.stamp_tax,
            transfer_fee=kernel_result.transfer_fee,
            total_fee=kernel_result.total_fee,
            cash_delta=kernel_result.cash_delta,
            reject_reason=kernel_result.reject_reason,
            new_lot=new_lot,
            lot_consumptions=lot_consumptions,
            realized_pnl_delta=realized_pnl,
        )
