from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from quant_lab.paper.errors import PaperError


@dataclass(frozen=True, slots=True)
class LotSnapshot:
    lot_id: str
    instrument_id: str
    acquired_date: date
    quantity: int
    remaining_quantity: int
    cost_price: Decimal
    sellable_from_date: date


@dataclass(frozen=True, slots=True)
class LotConsumption:
    lot_id: str
    consumed_quantity: int
    remaining_quantity: int
    cost_basis: Decimal


def plan_sell_lot_consumption(
    lots: tuple[LotSnapshot, ...], filled_quantity: int
) -> tuple[LotConsumption, ...]:
    """Deterministically consume sellable lots FIFO (by acquired_date, then id).

    Returns which lots consume how much and the realized cost basis for the
    filled quantity. It never mutates input lots.
    """
    if filled_quantity < 0:
        raise PaperError("INVALID_QUANTITY", "成交数量必须非负")
    ordered = tuple(sorted(lots, key=lambda lot: (lot.acquired_date, lot.lot_id)))
    remaining = filled_quantity
    consumptions: list[LotConsumption] = []
    for lot in ordered:
        if remaining <= 0:
            break
        if lot.remaining_quantity <= 0:
            continue
        consume = min(lot.remaining_quantity, remaining)
        consumptions.append(
            LotConsumption(
                lot_id=lot.lot_id,
                consumed_quantity=consume,
                remaining_quantity=lot.remaining_quantity - consume,
                cost_basis=Decimal(consume) * lot.cost_price,
            )
        )
        remaining -= consume
    if remaining > 0:
        raise PaperError("INSUFFICIENT_SELLABLE", "可卖数量不足")
    return tuple(consumptions)


def realized_cost_basis(consumptions: tuple[LotConsumption, ...]) -> Decimal:
    return sum((item.cost_basis for item in consumptions), Decimal("0"))
