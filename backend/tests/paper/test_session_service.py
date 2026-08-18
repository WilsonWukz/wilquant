from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from quant_lab.backtest.strategy_library import StrategyLibrary
from quant_lab.paper.enums import (
    AuditEventType,
    IntentSourceType,
    LedgerEntryType,
    PaperAccountStatus,
    PaperOrderStatus,
    PaperSessionStatus,
)
from quant_lab.paper.errors import PaperError
from quant_lab.paper.models import (
    PaperAccountSnapshotModel,
    PaperAuditEventModel,
    PaperFillModel,
    PaperLedgerEntryModel,
    PaperOrderModel,
    PaperPositionLotModel,
    PaperPositionModel,
    PaperRiskDecisionModel,
    PaperSessionAdvanceModel,
)
from quant_lab.paper.repository import PaperRepository
from quant_lab.paper.risk import RiskEngine
from quant_lab.paper.risk_service import PaperRiskService
from quant_lab.paper.service import AdvanceSessionRequest, PaperSessionService

ZERO_EXECUTION_CONFIG = {
    "fee_policy": {
        "stock_commission_rate": "0",
        "etf_commission_rate": "0",
        "stock_min_commission": "0",
        "etf_min_commission": "0",
        "stock_stamp_tax_rate": "0",
        "etf_stamp_tax_rate": "0",
        "transfer_fee_rate": "0",
    },
    "slippage_policy": {"buy_bps": "0", "sell_bps": "0"},
    "max_volume_participation": None,
}

D1 = date(2026, 1, 2)
D2 = date(2026, 1, 5)
D3 = date(2026, 1, 6)
D4 = date(2026, 1, 7)


def _running_session(env, *, replay_start: date = D1, replay_end: date | None = None,
                     strategy_version_id: str | None = None,
                     initial_cash: Decimal = Decimal("100000")):
    account = env.repository.create_account(name="a", initial_cash=initial_cash)
    view = env.session_service.create_session(
        name="s",
        paper_account_id=account.id,
        market_data_profile_id=env.profile_id,
        replay_start_date=replay_start,
        replay_end_date=replay_end,
        execution_config=ZERO_EXECUTION_CONFIG,
        strategy_version_id=strategy_version_id,
    )
    started = env.session_service.start_session(view.paper_session_id)
    return account.id, started


def _ensure_policy(env, account_id: str):
    for policy in env.repository.list_risk_policies(account_id):
        if policy.status == "ACTIVE":
            return policy
    policy = env.repository.create_risk_policy(paper_account_id=account_id, name="p")
    env.repository.create_risk_policy_version(
        risk_policy_id=policy.id,
        max_single_order_notional=Decimal("1000000"),
        max_single_position_weight=Decimal("1"),
        max_total_exposure=Decimal("1"),
        cash_buffer_ratio=Decimal("0"),
        max_daily_loss=Decimal("0.5"),
        max_drawdown=Decimal("0.5"),
        max_open_orders=100,
        allowed_security_types=["EQUITY"],
    )
    return policy


def _submitted_order(env, account_id: str, session_id: str, *, instrument_id: str,
                     side: str, quantity: int, execution_date: date) -> str:
    _ensure_policy(env, account_id)
    intent = env.repository.create_intent(
        paper_session_id=session_id,
        source_type=IntentSourceType.MANUAL.value,
        source_id=None,
        instrument_id=instrument_id,
        side=side,
        quantity=quantity,
        order_type="MARKET_ON_OPEN_SIMULATED",
        limit_price=None,
        signal_session_date=execution_date,
        intended_execution_session=execution_date,
        strategy_version_id=None,
        reason=None,
        metadata_json="{}",
        idempotency_key=f"intent-{uuid4()}",
    )
    decision = env.risk_service.evaluate_intent(
        intent_id=intent.id,
        reference_price=Decimal("10"),
        security_type="EQUITY",
        estimated_fee=Decimal("0"),
    )
    assert decision.decision == "APPROVE"
    order = env.repository.create_order(
        client_order_id=f"co-{uuid4()}",
        paper_session_id=session_id,
        order_intent_id=intent.id,
        risk_decision_id=decision.id,
        instrument_id=instrument_id,
        side=side,
        requested_quantity=quantity,
        order_type="MARKET_ON_OPEN_SIMULATED",
        limit_price=None,
        status=PaperOrderStatus.SUBMITTED.value,
    )
    with Session(env.engine) as session:
        model = session.get(PaperOrderModel, order.id)
        model.execution_session_date = execution_date
        model.submitted_session_date = execution_date
        session.commit()
    return order.id


def _advance(env, session_id: str, key: str, version: int, expected_date: date | None = None):
    return env.session_service.advance_session(
        AdvanceSessionRequest(session_id, key, version, expected_date)
    )


def make_strategy(env) -> str:
    library = StrategyLibrary(env.engine)
    definition = library.create_definition(
        name="BuyAndHold", description="b&h", strategy_type="BUY_AND_HOLD"
    )
    version = library.create_version(
        definition.id, {"instrument_id": "600000.XSHG", "target_weight": "1"}, "v1"
    )
    return version.id


def rebuild_services(env):
    repository = PaperRepository(env.engine)
    risk_service = PaperRiskService(repository, RiskEngine())
    session_service = PaperSessionService(
        env.engine, repository, env.market_data, env.calendars,
        env.dataset_query, risk_service,
    )
    return SimpleNamespace(
        engine=env.engine, repository=repository, risk_service=risk_service,
        session_service=session_service, market_data=env.market_data,
        calendars=env.calendars, dataset_query=env.dataset_query,
    )


def _session_advanced_audit(env, session_id: str) -> dict:
    with Session(env.engine) as session:
        event = session.scalars(
            select(PaperAuditEventModel)
            .where(
                PaperAuditEventModel.paper_session_id == session_id,
                PaperAuditEventModel.event_type == AuditEventType.SESSION_ADVANCED.value,
            )
            .order_by(PaperAuditEventModel.created_at.desc())
        ).first()
    assert event is not None
    return json.loads(event.payload_json)


# --- lifecycle ---


def test_lifecycle_created_to_running(paper_env):
    _, started = _running_session(paper_env)
    assert started.status == PaperSessionStatus.RUNNING.value
    assert started.current_session_date is None
    assert started.version == 2


def test_lifecycle_running_to_paused(paper_env):
    _, started = _running_session(paper_env)
    paused = paper_env.session_service.pause_session(started.paper_session_id)
    assert paused.status == PaperSessionStatus.PAUSED.value
    assert paused.version == started.version + 1


def test_lifecycle_paused_to_running(paper_env):
    _, started = _running_session(paper_env)
    paused = paper_env.session_service.pause_session(started.paper_session_id)
    resumed = paper_env.session_service.resume_session(started.paper_session_id)
    assert resumed.status == PaperSessionStatus.RUNNING.value
    assert resumed.version == paused.version + 1


def test_lifecycle_running_to_stopped(paper_env):
    _, started = _running_session(paper_env)
    stopped = paper_env.session_service.stop_session(started.paper_session_id)
    assert stopped.status == PaperSessionStatus.STOPPED.value


def test_lifecycle_illegal_transition_rejected(paper_env):
    _, started = _running_session(paper_env)
    with pytest.raises(PaperError, match="SESSION_STATE_TRANSITION_INVALID"):
        paper_env.session_service.start_session(started.paper_session_id)


def test_lifecycle_mutations_increment_version(paper_env):
    _, started = _running_session(paper_env)
    paused = paper_env.session_service.pause_session(started.paper_session_id)
    assert paused.version == 3
    resumed = paper_env.session_service.resume_session(started.paper_session_id)
    assert resumed.version == 4
    stopped = paper_env.session_service.stop_session(started.paper_session_id)
    assert stopped.version == 5


def test_lifecycle_audit_created(paper_env):
    _, started = _running_session(paper_env)
    paper_env.session_service.pause_session(started.paper_session_id)
    with Session(paper_env.engine) as session:
        events = session.scalars(
            select(PaperAuditEventModel).where(
                PaperAuditEventModel.paper_session_id == started.paper_session_id,
                PaperAuditEventModel.event_type == AuditEventType.SESSION_PAUSED.value,
            )
        ).all()
    assert len(events) == 1


# --- advance calendar ---


def test_advance_first_uses_first_open_session(paper_env):
    _, started = _running_session(paper_env)
    result = _advance(paper_env, started.paper_session_id, "k1", started.version, None)
    assert result.resulting_session_date == D1
    assert result.previous_session_date is None


def test_advance_skips_closed_calendar_date(paper_env):
    _, started = _running_session(paper_env)
    r1 = _advance(paper_env, started.paper_session_id, "k1", started.version, None)
    r2 = _advance(paper_env, started.paper_session_id, "k2", r1.session_version, D1)
    assert r2.resulting_session_date == D2


def test_advance_next_uses_next_open_session(paper_env):
    _, started = _running_session(paper_env)
    r1 = _advance(paper_env, started.paper_session_id, "k1", started.version, None)
    r2 = _advance(paper_env, started.paper_session_id, "k2", r1.session_version, D1)
    r3 = _advance(paper_env, started.paper_session_id, "k3", r2.session_version, D2)
    assert r3.resulting_session_date == D3


def test_advance_does_not_follow_changed_profile(paper_env):
    _, started = _running_session(paper_env)
    new_version = paper_env.calendars.create_version(
        calendar_id=paper_env.calendar_id,
        source_sha256="c" * 64,
        schema_version="trading-calendar@1",
        fingerprint="d" * 64,
        sessions=[
            {
                "session_date": date(2030, 1, 2),
                "is_open": True,
                "open_time": None,
                "close_time": None,
                "timezone": "Asia/Shanghai",
                "session_type": "REGULAR",
            }
        ],
    )
    paper_env.market_data.profiles.update_bindings(
        "p", {"calendar_version_id": new_version.trading_calendar_version_id}
    )
    result = _advance(paper_env, started.paper_session_id, "k1", started.version, None)
    assert result.resulting_session_date == D1


def test_advance_end_date_respected(paper_env):
    _, started = _running_session(paper_env, replay_end=D2)
    r1 = _advance(paper_env, started.paper_session_id, "k1", started.version, None)
    assert r1.resulting_session_date == D1
    r2 = _advance(paper_env, started.paper_session_id, "k2", r1.session_version, D1)
    assert r2.resulting_session_date == D2
    with pytest.raises(PaperError, match="NO_FUTURE_SESSION"):
        _advance(paper_env, started.paper_session_id, "k3", r2.session_version, D2)


def test_advance_no_future_session_flag(paper_env):
    _, started = _running_session(paper_env, replay_end=D4)
    r1 = _advance(paper_env, started.paper_session_id, "k1", started.version, None)
    r2 = _advance(paper_env, started.paper_session_id, "k2", r1.session_version, D1)
    r3 = _advance(paper_env, started.paper_session_id, "k3", r2.session_version, D2)
    r4 = _advance(paper_env, started.paper_session_id, "k4", r3.session_version, D3)
    assert r4.resulting_session_date == D4
    assert r4.no_future_session is True


# --- idempotency / concurrency ---


def test_duplicate_advance_returns_same_date(paper_env):
    _, started = _running_session(paper_env)
    first = _advance(paper_env, started.paper_session_id, "dup", started.version, None)
    second = _advance(paper_env, started.paper_session_id, "dup", started.version, None)
    assert second.resulting_session_date == first.resulting_session_date == D1
    assert second.idempotent_replay is True
    assert second.session_version == first.session_version


def test_duplicate_advance_no_duplicate_snapshot(paper_env):
    _, started = _running_session(paper_env)
    _advance(paper_env, started.paper_session_id, "dup", started.version, None)
    _advance(paper_env, started.paper_session_id, "dup", started.version, None)
    with Session(paper_env.engine) as session:
        snapshots = session.scalars(
            select(PaperAccountSnapshotModel).where(
                PaperAccountSnapshotModel.paper_session_id == started.paper_session_id
            )
        ).all()
    assert len(snapshots) == 1


def test_stale_expected_version_rejected(paper_env):
    _, started = _running_session(paper_env)
    with pytest.raises(PaperError, match="SESSION_VERSION_CONFLICT"):
        _advance(paper_env, started.paper_session_id, "k1", started.version - 1, None)


def test_stale_expected_date_rejected(paper_env):
    _, started = _running_session(paper_env)
    r1 = _advance(paper_env, started.paper_session_id, "k1", started.version, None)
    with pytest.raises(PaperError, match="SESSION_VERSION_CONFLICT"):
        _advance(paper_env, started.paper_session_id, "k2", r1.session_version, D2)


def test_advance_rejected_when_not_running(paper_env):
    _, started = _running_session(paper_env)
    paper_env.session_service.pause_session(started.paper_session_id)
    with pytest.raises(PaperError, match="SESSION_NOT_RUNNING"):
        _advance(paper_env, started.paper_session_id, "k1", started.version + 1, None)


# --- execution persistence ---


def test_full_buy_creates_fill_ledger_lot(paper_env):
    env = paper_env
    account_id, started = _running_session(env)
    _submitted_order(env, account_id, started.paper_session_id, instrument_id="600000.XSHG",
                     side="BUY", quantity=100, execution_date=D2)
    r1 = _advance(env, started.paper_session_id, "k1", started.version, None)
    r2 = _advance(env, started.paper_session_id, "k2", r1.session_version, D1)
    assert len(r2.fills) == 1
    with Session(env.engine) as session:
        fills = session.scalars(select(PaperFillModel)).all()
        ledgers = session.scalars(select(PaperLedgerEntryModel)).all()
        lots = session.scalars(select(PaperPositionLotModel)).all()
        positions = session.scalars(select(PaperPositionModel)).all()
    assert len(fills) == 1
    assert fills[0].quantity == 100
    assert fills[0].fill_price == Decimal("10.2")
    assert len(ledgers) == 2
    assert ledgers[1].entry_type == LedgerEntryType.TRADE_SETTLEMENT.value
    assert ledgers[1].cash_delta == Decimal("-1020")
    assert lots[0].remaining_quantity == 100
    assert positions[0].total_quantity == 100
    assert positions[0].average_cost == Decimal("10.2")
    assert env.repository.get_account(account_id).cash == Decimal("98980")


def test_buy_cash_delta_correct(paper_env):
    env = paper_env
    account_id, started = _running_session(env)
    _submitted_order(env, account_id, started.paper_session_id, instrument_id="600000.XSHG",
                     side="BUY", quantity=200, execution_date=D2)
    r1 = _advance(env, started.paper_session_id, "k1", started.version, None)
    _advance(env, started.paper_session_id, "k2", r1.session_version, D1)
    account = env.repository.get_account(account_id)
    assert account.cash == Decimal("100000") - Decimal(200) * Decimal("10.2")


def test_full_sell_consumes_fifo_lots(paper_env):
    env = paper_env
    account_id, started = _running_session(env)
    _submitted_order(env, account_id, started.paper_session_id, instrument_id="600000.XSHG",
                     side="BUY", quantity=100, execution_date=D2)
    r1 = _advance(env, started.paper_session_id, "k1", started.version, None)
    r2 = _advance(env, started.paper_session_id, "k2", r1.session_version, D1)
    _submitted_order(env, account_id, started.paper_session_id, instrument_id="600000.XSHG",
                     side="SELL", quantity=100, execution_date=D3)
    r3 = _advance(env, started.paper_session_id, "k3", r2.session_version, D2)
    assert len(r3.fills) == 1
    with Session(env.engine) as session:
        lots = session.scalars(select(PaperPositionLotModel)).all()
        positions = session.scalars(select(PaperPositionModel)).all()
    assert lots[0].remaining_quantity == 0
    assert positions[0].total_quantity == 0
    assert positions[0].sellable_quantity == 0


def test_sell_realized_pnl_persists(paper_env):
    env = paper_env
    account_id, started = _running_session(env)
    _submitted_order(env, account_id, started.paper_session_id, instrument_id="600000.XSHG",
                     side="BUY", quantity=100, execution_date=D2)
    r1 = _advance(env, started.paper_session_id, "k1", started.version, None)
    r2 = _advance(env, started.paper_session_id, "k2", r1.session_version, D1)
    _submitted_order(env, account_id, started.paper_session_id, instrument_id="600000.XSHG",
                     side="SELL", quantity=100, execution_date=D3)
    _advance(env, started.paper_session_id, "k3", r2.session_version, D2)
    with Session(env.engine) as session:
        position = session.scalars(select(PaperPositionModel)).one()
    assert position.realized_pnl == Decimal("20")


def test_market_reject_no_fill_no_cash_mutation(paper_env):
    env = paper_env
    account_id, started = _running_session(env)
    _submitted_order(env, account_id, started.paper_session_id, instrument_id="600000.XSHG",
                     side="SELL", quantity=100, execution_date=D2)
    r1 = _advance(env, started.paper_session_id, "k1", started.version, None)
    r2 = _advance(env, started.paper_session_id, "k2", r1.session_version, D1)
    assert r2.fills == ()
    with Session(env.engine) as session:
        order = session.scalars(select(PaperOrderModel)).one()
        fills = session.scalars(select(PaperFillModel)).all()
    assert order.status == PaperOrderStatus.REJECTED.value
    assert order.reject_reason == "T1_SELL_RESTRICTED"
    assert fills == []
    assert env.repository.get_account(account_id).cash == Decimal("100000")


def test_zero_position_row_retained_after_sell(paper_env):
    env = paper_env
    account_id, started = _running_session(env)
    _submitted_order(env, account_id, started.paper_session_id, instrument_id="600000.XSHG",
                     side="BUY", quantity=100, execution_date=D2)
    r1 = _advance(env, started.paper_session_id, "k1", started.version, None)
    r2 = _advance(env, started.paper_session_id, "k2", r1.session_version, D1)
    _submitted_order(env, account_id, started.paper_session_id, instrument_id="600000.XSHG",
                     side="SELL", quantity=100, execution_date=D3)
    _advance(env, started.paper_session_id, "k3", r2.session_version, D2)
    with Session(env.engine) as session:
        positions = session.scalars(select(PaperPositionModel)).all()
    assert len(positions) == 1
    assert positions[0].total_quantity == 0
    assert positions[0].average_cost == Decimal("0")
    assert positions[0].market_value == Decimal("0")


# --- valuation ---


def test_mark_to_market_close(paper_env):
    env = paper_env
    account_id, started = _running_session(env)
    _submitted_order(env, account_id, started.paper_session_id, instrument_id="600000.XSHG",
                     side="BUY", quantity=100, execution_date=D2)
    r1 = _advance(env, started.paper_session_id, "k1", started.version, None)
    _advance(env, started.paper_session_id, "k2", r1.session_version, D1)
    with Session(env.engine) as session:
        position = session.scalars(select(PaperPositionModel)).one()
    assert position.market_value == Decimal(100) * Decimal("10.4")


def test_missing_bar_uses_last_known_close(paper_env):
    env = paper_env
    account_id, started = _running_session(env)
    _submitted_order(env, account_id, started.paper_session_id, instrument_id="000001.XSHE",
                     side="BUY", quantity=100, execution_date=D2)
    r1 = _advance(env, started.paper_session_id, "k1", started.version, None)
    r2 = _advance(env, started.paper_session_id, "k2", r1.session_version, D1)
    _advance(env, started.paper_session_id, "k3", r2.session_version, D2)
    with Session(env.engine) as session:
        position = session.scalars(
            select(PaperPositionModel).where(PaperPositionModel.instrument_id == "000001.XSHE")
        ).one()
    assert position.market_value == Decimal(100) * Decimal("20.4")
    audit = _session_advanced_audit(env, started.paper_session_id)
    assert "000001.XSHE" in audit["stale_instrument_ids"]


def test_daily_and_cumulative_pnl(paper_env):
    env = paper_env
    account_id, started = _running_session(env)
    _submitted_order(env, account_id, started.paper_session_id, instrument_id="600000.XSHG",
                     side="BUY", quantity=100, execution_date=D2)
    r1 = _advance(env, started.paper_session_id, "k1", started.version, None)
    _advance(env, started.paper_session_id, "k2", r1.session_version, D1)
    with Session(env.engine) as session:
        snapshots = session.scalars(
            select(PaperAccountSnapshotModel).order_by(PaperAccountSnapshotModel.session_date)
        ).all()
    assert snapshots[0].session_date == D1
    assert snapshots[0].daily_pnl == Decimal("0")
    assert snapshots[1].daily_pnl == snapshots[1].equity - snapshots[0].equity
    assert snapshots[1].cumulative_pnl == snapshots[1].equity - Decimal("100000")


def test_drawdown_negative_semantics(paper_env):
    env = paper_env
    _, started = _running_session(env)
    _advance(env, started.paper_session_id, "k1", started.version, None)
    with Session(env.engine) as session:
        snapshot = session.scalars(select(PaperAccountSnapshotModel)).one()
    assert snapshot.drawdown == Decimal("0")


# --- strategy / risk ---


def test_buy_and_hold_generates_next_session_intent(paper_env):
    env = paper_env
    strategy_id = make_strategy(env)
    account_id, started = _running_session(env, strategy_version_id=strategy_id)
    _ensure_policy(env, account_id)
    result = _advance(env, started.paper_session_id, "k1", started.version, None)
    assert result.risk_approved_count == 1
    assert len(result.created_order_ids) == 1
    with Session(env.engine) as session:
        order = session.scalars(select(PaperOrderModel)).one()
    assert order.status == PaperOrderStatus.SUBMITTED.value
    assert order.execution_session_date == D2


def test_manual_intent_shares_risk_order_path(paper_env):
    env = paper_env
    account_id, started = _running_session(env)
    _ensure_policy(env, account_id)
    env.repository.create_intent(
        paper_session_id=started.paper_session_id,
        source_type=IntentSourceType.MANUAL.value,
        source_id=None,
        instrument_id="600000.XSHG",
        side="BUY",
        quantity=100,
        order_type="MARKET_ON_OPEN_SIMULATED",
        limit_price=None,
        signal_session_date=D1,
        intended_execution_session=D2,
        strategy_version_id=None,
        reason=None,
        metadata_json="{}",
        idempotency_key="manual-1",
    )
    result = _advance(env, started.paper_session_id, "k1", started.version, None)
    assert result.risk_approved_count == 1
    with Session(env.engine) as session:
        order = session.scalars(select(PaperOrderModel)).one()
        decision = session.scalars(select(PaperRiskDecisionModel)).one()
    assert order.status == PaperOrderStatus.SUBMITTED.value
    assert order.execution_session_date == D2
    assert decision.decision == "APPROVE"


def test_risk_reject_creates_risk_rejected_order(paper_env):
    env = paper_env
    account_id, started = _running_session(env)
    policy = _ensure_policy(env, account_id)
    env.repository.create_risk_policy_version(
        risk_policy_id=policy.id,
        max_single_order_notional=Decimal("10"),
        max_single_position_weight=Decimal("1"),
        max_total_exposure=Decimal("1"),
        cash_buffer_ratio=Decimal("0"),
        max_daily_loss=Decimal("0.5"),
        max_drawdown=Decimal("0.5"),
        max_open_orders=100,
        allowed_security_types=["EQUITY"],
    )
    env.repository.create_intent(
        paper_session_id=started.paper_session_id,
        source_type=IntentSourceType.MANUAL.value,
        source_id=None,
        instrument_id="600000.XSHG",
        side="BUY",
        quantity=100,
        order_type="MARKET_ON_OPEN_SIMULATED",
        limit_price=None,
        signal_session_date=D1,
        intended_execution_session=D2,
        strategy_version_id=None,
        reason=None,
        metadata_json="{}",
        idempotency_key="manual-reject",
    )
    result = _advance(env, started.paper_session_id, "k1", started.version, None)
    assert result.risk_rejected_count == 1
    with Session(env.engine) as session:
        order = session.scalars(select(PaperOrderModel)).one()
    assert order.status == PaperOrderStatus.RISK_REJECTED.value
    assert order.reject_reason is not None


# --- failure / rollback ---


def test_fill_persistence_failure_rolls_back(paper_env, monkeypatch):
    env = paper_env
    account_id, started = _running_session(env)
    _submitted_order(env, account_id, started.paper_session_id, instrument_id="600000.XSHG",
                     side="BUY", quantity=100, execution_date=D2)
    r1 = _advance(env, started.paper_session_id, "k1", started.version, None)

    def fail(*_args, **_kwargs):
        raise RuntimeError("fill persistence failure")

    monkeypatch.setattr(env.session_service, "_apply_fill", fail)
    with pytest.raises(PaperError, match="ADVANCE_FAILED"):
        _advance(env, started.paper_session_id, "k2", r1.session_version, D1)

    assert env.repository.get_account(account_id).cash == Decimal("100000")
    with Session(env.engine) as session:
        fills = session.scalars(select(PaperFillModel)).all()
        snapshots = session.scalars(select(PaperAccountSnapshotModel)).all()
    assert fills == []
    assert [s.session_date for s in snapshots] == [D1]
    model = env.repository.get_session(started.paper_session_id)
    assert model.status == PaperSessionStatus.FAILED.value
    assert model.current_session_date == D1


def test_position_persistence_failure_rolls_back(paper_env, monkeypatch):
    env = paper_env
    account_id, started = _running_session(env)
    _submitted_order(env, account_id, started.paper_session_id, instrument_id="600000.XSHG",
                     side="BUY", quantity=100, execution_date=D2)
    r1 = _advance(env, started.paper_session_id, "k1", started.version, None)

    def fail(*_args, **_kwargs):
        raise RuntimeError("position persistence failure")

    monkeypatch.setattr(env.session_service, "_apply_buy", fail)
    with pytest.raises(PaperError, match="ADVANCE_FAILED"):
        _advance(env, started.paper_session_id, "k2", r1.session_version, D1)

    with Session(env.engine) as session:
        assert session.scalars(select(PaperPositionModel)).all() == []
        assert session.scalars(select(PaperPositionLotModel)).all() == []
        assert session.scalars(select(PaperFillModel)).all() == []
    model = env.repository.get_session(started.paper_session_id)
    assert model.status == PaperSessionStatus.FAILED.value
    assert model.current_session_date == D1


def test_audit_persistence_failure_rolls_back(paper_env, monkeypatch):
    env = paper_env
    _, started = _running_session(env)
    r1 = _advance(env, started.paper_session_id, "k1", started.version, None)

    original_init = PaperAuditEventModel.__init__

    def failing_init(self, **kwargs):
        if kwargs.get("event_type") == AuditEventType.SESSION_ADVANCED.value:
            raise RuntimeError("audit persistence failure")
        original_init(self, **kwargs)

    monkeypatch.setattr(PaperAuditEventModel, "__init__", failing_init)
    with pytest.raises(PaperError, match="ADVANCE_FAILED"):
        _advance(env, started.paper_session_id, "k2", r1.session_version, D1)

    with Session(env.engine) as session:
        snapshots = session.scalars(select(PaperAccountSnapshotModel)).all()
    assert [s.session_date for s in snapshots] == [D1]
    model = env.repository.get_session(started.paper_session_id)
    assert model.status == PaperSessionStatus.FAILED.value
    assert model.current_session_date == D1


def test_failed_advance_is_idempotent(paper_env, monkeypatch):
    env = paper_env
    account_id, started = _running_session(env)
    _submitted_order(env, account_id, started.paper_session_id, instrument_id="600000.XSHG",
                     side="BUY", quantity=100, execution_date=D2)
    r1 = _advance(env, started.paper_session_id, "k1", started.version, None)

    def fail(*_args, **_kwargs):
        raise RuntimeError("fill persistence failure")

    monkeypatch.setattr(env.session_service, "_apply_fill", fail)
    with pytest.raises(PaperError, match="ADVANCE_FAILED"):
        _advance(env, started.paper_session_id, "k2", r1.session_version, D1)
    with pytest.raises(PaperError, match="ADVANCE_FAILED"):
        _advance(env, started.paper_session_id, "k2", r1.session_version, D1)


def test_strategy_error_rolls_back_and_fails(paper_env, monkeypatch):
    env = paper_env
    strategy_id = make_strategy(env)
    account_id, started = _running_session(env, strategy_version_id=strategy_id)
    _ensure_policy(env, account_id)

    class RaisingStrategy:
        def on_close(self, **_kwargs):
            raise RuntimeError("strategy failure")

    monkeypatch.setattr(env.session_service, "_load_strategy", lambda *a, **kw: RaisingStrategy())
    with pytest.raises(PaperError, match="ADVANCE_FAILED"):
        _advance(env, started.paper_session_id, "k1", started.version, None)

    assert env.repository.get_account(account_id).cash == Decimal("100000")
    with Session(env.engine) as session:
        assert session.scalars(select(PaperOrderModel)).all() == []
        assert session.scalars(select(PaperAccountSnapshotModel)).all() == []
    model = env.repository.get_session(started.paper_session_id)
    assert model.status == PaperSessionStatus.FAILED.value
    assert model.current_session_date is None


# --- restart persistence ---


def test_restart_persistence(paper_env):
    env = paper_env
    strategy_id = make_strategy(env)
    account_id, started = _running_session(env, strategy_version_id=strategy_id)
    _ensure_policy(env, account_id)
    r1 = _advance(env, started.paper_session_id, "k1", started.version, None)
    r2 = _advance(env, started.paper_session_id, "k2", r1.session_version, D1)

    with Session(env.engine) as session:
        before_counts = (
            len(session.scalars(select(PaperFillModel)).all()),
            len(session.scalars(select(PaperOrderModel)).all()),
            len(session.scalars(select(PaperPositionModel)).all()),
            len(session.scalars(select(PaperPositionLotModel)).all()),
            len(session.scalars(select(PaperLedgerEntryModel)).all()),
            len(session.scalars(select(PaperRiskDecisionModel)).all()),
            len(session.scalars(select(PaperAccountSnapshotModel)).all()),
            len(session.scalars(select(PaperAuditEventModel)).all()),
            len(session.scalars(select(PaperSessionAdvanceModel)).all()),
        )

    rebuilt = rebuild_services(env)
    account = rebuilt.repository.get_account(account_id)
    session_model = rebuilt.repository.get_session(started.paper_session_id)
    assert session_model.status == PaperSessionStatus.RUNNING.value
    assert session_model.current_session_date == D2
    assert session_model.version == r2.session_version
    assert account.cash > Decimal("0")

    with Session(rebuilt.engine) as session:
        after_counts = (
            len(session.scalars(select(PaperFillModel)).all()),
            len(session.scalars(select(PaperOrderModel)).all()),
            len(session.scalars(select(PaperPositionModel)).all()),
            len(session.scalars(select(PaperPositionLotModel)).all()),
            len(session.scalars(select(PaperLedgerEntryModel)).all()),
            len(session.scalars(select(PaperRiskDecisionModel)).all()),
            len(session.scalars(select(PaperAccountSnapshotModel)).all()),
            len(session.scalars(select(PaperAuditEventModel)).all()),
            len(session.scalars(select(PaperSessionAdvanceModel)).all()),
        )
    assert after_counts == before_counts

# --- partial fill / freeze ---


PARTIAL_EXECUTION_CONFIG = {
    "fee_policy": {
        "stock_commission_rate": "0",
        "etf_commission_rate": "0",
        "stock_min_commission": "0",
        "etf_min_commission": "0",
        "stock_stamp_tax_rate": "0",
        "etf_stamp_tax_rate": "0",
        "transfer_fee_rate": "0",
    },
    "slippage_policy": {"buy_bps": "0", "sell_bps": "0"},
    "max_volume_participation": "0.05",
}


def test_partial_fill_then_expired(paper_env):
    env = paper_env
    account = env.repository.create_account(name="a", initial_cash=Decimal("100000"))
    view = env.session_service.create_session(
        name="s",
        paper_account_id=account.id,
        market_data_profile_id=env.profile_id,
        replay_start_date=D1,
        replay_end_date=None,
        execution_config=PARTIAL_EXECUTION_CONFIG,
        strategy_version_id=None,
    )
    started = env.session_service.start_session(view.paper_session_id)
    _submitted_order(env, account.id, started.paper_session_id, instrument_id="600000.XSHG",
                     side="BUY", quantity=10000, execution_date=D2)
    r1 = _advance(env, started.paper_session_id, "k1", started.version, None)
    _advance(env, started.paper_session_id, "k2", r1.session_version, D1)
    with Session(env.engine) as session:
        order = session.scalars(select(PaperOrderModel)).one()
        fill = session.scalars(select(PaperFillModel)).one()
    assert fill.quantity == 5000
    assert order.status == PaperOrderStatus.EXPIRED.value
    assert order.filled_quantity == 5000
    assert order.accepted_quantity == 5000


def test_freeze_cancels_pending_orders(paper_env):
    env = paper_env
    account_id, started = _running_session(env)
    _ensure_policy(env, account_id)
    # 一个未来 SUBMITTED 订单 (pending)
    _submitted_order(env, account_id, started.paper_session_id, instrument_id="600000.XSHG",
                     side="BUY", quantity=100, execution_date=D3)
    # 历史高点 snapshot, 使 D1 估值产生 -50% 回撤, 触发 drawdown/daily-loss freeze
    env.repository.create_snapshot(
        paper_account_id=account_id,
        paper_session_id=started.paper_session_id,
        session_date=date(2025, 12, 31),
        cash=Decimal("200000"),
        market_value=Decimal("0"),
        equity=Decimal("200000"),
        gross_exposure=Decimal("0"),
        daily_pnl=Decimal("0"),
        cumulative_pnl=Decimal("100000"),
        drawdown=Decimal("0"),
    )
    # 一个待评估 manual intent
    env.repository.create_intent(
        paper_session_id=started.paper_session_id,
        source_type=IntentSourceType.MANUAL.value,
        source_id=None,
        instrument_id="600000.XSHG",
        side="BUY",
        quantity=100,
        order_type="MARKET_ON_OPEN_SIMULATED",
        limit_price=None,
        signal_session_date=D1,
        intended_execution_session=D2,
        strategy_version_id=None,
        reason=None,
        metadata_json="{}",
        idempotency_key="freeze-intent",
    )
    result = _advance(env, started.paper_session_id, "k1", started.version, None)
    assert result.risk_rejected_count == 1

    account = env.repository.get_account(account_id)
    assert account.status == PaperAccountStatus.FROZEN.value
    with Session(env.engine) as session:
        orders = session.scalars(select(PaperOrderModel)).all()
        decisions = session.scalars(select(PaperRiskDecisionModel)).all()
    assert len(orders) == 2
    by_status = {order.status for order in orders}
    assert PaperOrderStatus.CANCELLED.value in by_status
    assert PaperOrderStatus.RISK_REJECTED.value in by_status
    assert len(decisions) == 2
    assert any("DAILY_LOSS_LIMIT" in d.reason_codes_json for d in decisions)

