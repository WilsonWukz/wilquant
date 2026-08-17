from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
import sqlalchemy as sa
from sqlalchemy import select
from sqlalchemy.orm import Session

from quant_lab.paper.enums import (
    IntentSourceType,
    LedgerEntryType,
    PaperAccountStatus,
    PaperOrderStatus,
)
from quant_lab.paper.errors import PaperError
from quant_lab.paper.models import (
    PaperAuditEventModel,
    PaperFillModel,
    PaperLedgerEntryModel,
    PaperOrderModel,
    PaperPositionLotModel,
    PaperPositionModel,
    PaperRiskDecisionModel,
)
from quant_lab.paper.repository import PaperRepository

from .conftest import make_account


def test_create_account_has_cash_equity_invariant(repository: PaperRepository):
    account = make_account(repository)
    assert account.status == PaperAccountStatus.ACTIVE.value
    assert account.initial_cash == Decimal("100000")
    assert account.cash == Decimal("100000")
    assert account.market_value == Decimal("0")
    assert account.account_equity == Decimal("100000")


def test_create_account_writes_deposit_ledger_and_audit(repository: PaperRepository, engine):
    account = make_account(repository)
    with Session(engine) as session:
        ledger = session.scalars(
            select(PaperLedgerEntryModel).where(
                PaperLedgerEntryModel.paper_account_id == account.id
            )
        ).all()
        audit = session.scalars(
            select(PaperAuditEventModel).where(
                PaperAuditEventModel.paper_account_id == account.id
            )
        ).all()
    assert len(ledger) == 1
    assert ledger[0].entry_type == LedgerEntryType.INITIAL_DEPOSIT.value
    assert ledger[0].cash_delta == Decimal("100000")
    assert len(audit) == 1
    assert audit[0].event_type == "ACCOUNT_CREATED"


@pytest.mark.parametrize("initial_cash", [Decimal("0"), Decimal("-1")])
def test_zero_or_negative_initial_cash_rejected(repository: PaperRepository, initial_cash):
    with pytest.raises(PaperError, match="INITIAL_CASH_INVALID"):
        repository.create_account(name="x", initial_cash=initial_cash)


def test_create_session_freezes_snapshot_and_version(repository: PaperRepository):
    account = make_account(repository)
    session = repository.create_session(
        name="sess",
        paper_account_id=account.id,
        market_data_profile_id="p",
        market_data_snapshot_json='{"bars_dataset_version_id": "v"}',
        market_data_snapshot_fingerprint="f" * 64,
    )
    assert session.status == "CREATED"
    assert session.version == 1
    assert session.market_data_snapshot_fingerprint == "f" * 64


def test_create_session_rejects_invalid_strategy_version(repository: PaperRepository):
    account = make_account(repository)
    with pytest.raises(PaperError, match="STRATEGY_VERSION_NOT_FOUND"):
        repository.create_session(
            name="sess",
            paper_account_id=account.id,
            market_data_profile_id="p",
            market_data_snapshot_json="{}",
            market_data_snapshot_fingerprint="f" * 64,
            strategy_version_id="missing-version",
        )


def test_create_intent_and_duplicate_idempotency(repository: PaperRepository):
    account = make_account(repository)
    session = repository.create_session(
        name="sess", paper_account_id=account.id, market_data_profile_id="p",
        market_data_snapshot_json="{}", market_data_snapshot_fingerprint="f" * 64,
    )
    kwargs = dict(
        paper_session_id=session.id,
        source_type=IntentSourceType.MANUAL.value,
        source_id=None,
        instrument_id="600000.XSHG",
        side="BUY",
        quantity=100,
        order_type="MARKET_ON_OPEN_SIMULATED",
        limit_price=None,
        signal_session_date=date(2026, 1, 2),
        intended_execution_session=date(2026, 1, 5),
        strategy_version_id=None,
        reason=None,
        metadata_json="{}",
        idempotency_key="intent-1",
    )
    first = repository.create_intent(**kwargs)
    second = repository.create_intent(**kwargs)
    assert second.id == first.id


def test_risk_policy_version_increments_and_fingerprint_deterministic(repository: PaperRepository):
    account = make_account(repository)
    policy = repository.create_risk_policy(paper_account_id=account.id, name="p")
    fields = dict(
        max_single_order_notional=Decimal("10000"),
        max_single_position_weight=Decimal("0.5"),
        max_total_exposure=Decimal("1.0"),
        cash_buffer_ratio=Decimal("0.1"),
        max_daily_loss=Decimal("0.05"),
        max_drawdown=Decimal("0.2"),
        max_open_orders=10,
        allowed_security_types=["EQUITY"],
    )
    v1 = repository.create_risk_policy_version(risk_policy_id=policy.id, **fields)
    v2 = repository.create_risk_policy_version(risk_policy_id=policy.id, **fields)
    assert v1.version == 1
    assert v2.version == 2
    assert v1.policy_fingerprint == v2.policy_fingerprint
    assert len(v1.policy_fingerprint) == 64


def _full_order(repository: PaperRepository, client_order_id: str = "co-1"):
    account = make_account(repository)
    session = repository.create_session(
        name="sess", paper_account_id=account.id, market_data_profile_id="p",
        market_data_snapshot_json="{}", market_data_snapshot_fingerprint="f" * 64,
    )
    intent = repository.create_intent(
        paper_session_id=session.id,
        source_type=IntentSourceType.MANUAL.value,
        source_id=None,
        instrument_id="600000.XSHG",
        side="BUY",
        quantity=100,
        order_type="MARKET_ON_OPEN_SIMULATED",
        limit_price=None,
        signal_session_date=date(2026, 1, 2),
        intended_execution_session=date(2026, 1, 5),
        strategy_version_id=None,
        reason=None,
        metadata_json="{}",
        idempotency_key="intent-x",
    )
    policy = repository.create_risk_policy(paper_account_id=account.id, name="p")
    version = repository.create_risk_policy_version(
        risk_policy_id=policy.id,
        max_single_order_notional=Decimal("10000"),
        max_single_position_weight=Decimal("0.5"),
        max_total_exposure=Decimal("1.0"),
        cash_buffer_ratio=Decimal("0.1"),
        max_daily_loss=Decimal("0.05"),
        max_drawdown=Decimal("0.2"),
        max_open_orders=10,
        allowed_security_types=["EQUITY"],
    )
    decision = repository.create_risk_decision(
        order_intent_id=intent.id,
        decision="APPROVE",
        reason_codes=[],
        risk_policy_id=policy.id,
        risk_policy_version_id=version.id,
        risk_policy_version=version.version,
        account_snapshot_json="{}",
        position_snapshot_json="{}",
        market_context_json="{}",
    )
    order = repository.create_order(
        client_order_id=client_order_id,
        paper_session_id=session.id,
        order_intent_id=intent.id,
        risk_decision_id=decision.id,
        instrument_id="600000.XSHG",
        side="BUY",
        requested_quantity=100,
        order_type="MARKET_ON_OPEN_SIMULATED",
        limit_price=None,
        status=PaperOrderStatus.CREATED.value,
    )
    return account, session, order


def test_order_legal_transition(repository: PaperRepository):
    _, _, order = _full_order(repository)
    approved = repository.transition_order(order.id, PaperOrderStatus.APPROVED.value)
    assert approved.status == PaperOrderStatus.APPROVED.value


def test_order_illegal_transition_rejected(repository: PaperRepository):
    _, _, order = _full_order(repository)
    with pytest.raises(PaperError, match="ORDER_STATE_TRANSITION_INVALID"):
        repository.transition_order(order.id, PaperOrderStatus.FILLED.value)


def test_approved_and_submitted_can_cancel(repository: PaperRepository):
    _, _, order = _full_order(repository)
    approved = repository.transition_order(order.id, PaperOrderStatus.APPROVED.value)
    cancelled = repository.transition_order(approved.id, PaperOrderStatus.CANCELLED.value)
    assert cancelled.status == PaperOrderStatus.CANCELLED.value


def test_duplicate_client_order_id_rejected(repository: PaperRepository):
    _full_order(repository, client_order_id="co-dup")
    with pytest.raises(sa.exc.IntegrityError):
        _full_order(repository, client_order_id="co-dup")


def test_risk_decision_immutable(repository: PaperRepository, engine):
    _, _, _order = _full_order(repository)
    with Session(engine) as session:
        decision = session.scalars(select(PaperRiskDecisionModel)).one()
        decision.decision = "REJECT"
        with pytest.raises(sa.exc.IntegrityError):
            session.commit()


def test_fill_immutable(repository: PaperRepository, engine):
    _account, session, _ = _full_order(repository)
    with Session(engine) as session_obj:
        order = session_obj.scalars(select(PaperOrderModel)).one()
        fill = PaperFillModel(
            id="fill-1",
            paper_order_id=order.id,
            paper_session_id=session.id,
            instrument_id="600000.XSHG",
            side="BUY",
            quantity=100,
            raw_price=Decimal("10"),
            slippage=Decimal("0"),
            fill_price=Decimal("10"),
            commission=Decimal("0"),
            stamp_tax=Decimal("0"),
            transfer_fee=Decimal("0"),
            total_fee=Decimal("0"),
            trade_date=date(2026, 1, 5),
            created_at=sa.func.now(),
        )
        session_obj.add(fill)
        session_obj.commit()
        fill.total_fee = Decimal("1")
        with pytest.raises(sa.exc.IntegrityError):
            session_obj.commit()


def test_position_unique_per_account_instrument(repository: PaperRepository, engine):
    account = make_account(repository)
    repository.upsert_position(
        paper_account_id=account.id,
        instrument_id="600000.XSHG",
        total_quantity=100,
        sellable_quantity=100,
        average_cost=Decimal("10"),
        market_value=Decimal("1000"),
        unrealized_pnl=Decimal("0"),
        realized_pnl=Decimal("0"),
    )
    repository.upsert_position(
        paper_account_id=account.id,
        instrument_id="600000.XSHG",
        total_quantity=200,
        sellable_quantity=200,
        average_cost=Decimal("10"),
        market_value=Decimal("2000"),
        unrealized_pnl=Decimal("0"),
        realized_pnl=Decimal("0"),
    )
    with Session(engine) as session:
        positions = session.scalars(
            select(PaperPositionModel).where(
                PaperPositionModel.paper_account_id == account.id
            )
        ).all()
    assert len(positions) == 1
    assert positions[0].total_quantity == 200


def test_position_lot_quantity_constraint(repository: PaperRepository, engine):
    account = make_account(repository)
    position = repository.upsert_position(
        paper_account_id=account.id,
        instrument_id="600000.XSHG",
        total_quantity=100,
        sellable_quantity=100,
        average_cost=Decimal("10"),
        market_value=Decimal("1000"),
        unrealized_pnl=Decimal("0"),
        realized_pnl=Decimal("0"),
    )
    lot = repository.create_position_lot(
        paper_account_id=account.id,
        paper_position_id=position.id,
        instrument_id="600000.XSHG",
        acquired_date=date(2026, 1, 5),
        quantity=100,
        cost_price=Decimal("10"),
        sellable_from_date=date(2026, 1, 6),
    )
    assert lot.remaining_quantity == 100
    with Session(engine) as session:
        lot_model = session.get(PaperPositionLotModel, lot.id)
        lot_model.remaining_quantity = 200
        with pytest.raises(sa.exc.IntegrityError):
            session.commit()


def test_advance_idempotency(repository: PaperRepository):
    account = make_account(repository)
    session = repository.create_session(
        name="sess", paper_account_id=account.id, market_data_profile_id="p",
        market_data_snapshot_json="{}", market_data_snapshot_fingerprint="f" * 64,
    )
    first = repository.create_or_get_advance(
        paper_session_id=session.id,
        idempotency_key="adv-1",
        expected_session_date=date(2026, 1, 5),
    )
    second = repository.create_or_get_advance(
        paper_session_id=session.id,
        idempotency_key="adv-1",
        expected_session_date=date(2026, 1, 5),
    )
    assert second.id == first.id
