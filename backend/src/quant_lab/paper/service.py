from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Protocol, cast
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from quant_lab.backtest.domain import OrderIntent, PositionLot
from quant_lab.backtest.rules import FeePolicy, InstrumentSpec, SlippagePolicy
from quant_lab.backtest.strategies import BuyAndHoldStrategy, TopNMomentumRotationStrategy
from quant_lab.backtest.strategy_library import StrategyLibrary
from quant_lab.datasets.query import DatasetQueryService
from quant_lab.execution.lots import LotConsumption, LotSnapshot
from quant_lab.market_data.calendar_persistence import TradingCalendarRepository
from quant_lab.market_data.consumption import MarketDataService
from quant_lab.market_data.fingerprints import canonical_json_bytes
from quant_lab.paper.enums import (
    AdvanceStatus,
    AuditEventType,
    IntentSourceType,
    LedgerEntryType,
    PaperAccountStatus,
    PaperOrderStatus,
    PaperSessionStatus,
)
from quant_lab.paper.errors import PaperError
from quant_lab.paper.execution import (
    NewLot,
    PaperExecutionEngine,
    PaperExecutionRequest,
    PaperExecutionResult,
    PaperOrderSnapshot,
)
from quant_lab.paper.models import (
    PaperAccountModel,
    PaperAccountSnapshotModel,
    PaperAuditEventModel,
    PaperFillModel,
    PaperLedgerEntryModel,
    PaperOrderIntentModel,
    PaperOrderModel,
    PaperPositionLotModel,
    PaperPositionModel,
    PaperRiskDecisionModel,
    PaperSessionAdvanceModel,
    PaperSessionModel,
)
from quant_lab.paper.repository import PaperRepository
from quant_lab.paper.risk_service import PaperRiskService
from quant_lab.paper.state import validate_session_transition


class StrategyLike(Protocol):
    def on_close(
        self,
        *,
        signal_date: date,
        execution_date: date | None,
        bars: dict[str, dict[str, object]],
        cash: Decimal,
        equity: Decimal,
        lots: tuple[PositionLot, ...],
        closes_history: dict[str, list[Decimal]],
        session_index: int,
        fee_policy: FeePolicy,
    ) -> tuple[OrderIntent, ...]: ...


class AdvanceFatalError(Exception):
    """Advance failure that must mark the session FAILED (corrupt state or
    internal error), distinct from a normal business rejection."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class AdvanceSessionRequest:
    paper_session_id: str
    idempotency_key: str
    expected_version: int
    expected_current_session_date: date | None


@dataclass(frozen=True, slots=True)
class SessionView:
    paper_session_id: str
    name: str
    paper_account_id: str
    status: str
    current_session_date: date | None
    version: int
    replay_start_date: date
    replay_end_date: date | None


@dataclass(frozen=True, slots=True)
class PaperAdvanceResult:
    paper_session_id: str
    previous_session_date: date | None
    resulting_session_date: date | None
    session_version: int
    executed_orders: tuple[str, ...]
    fills: tuple[str, ...]
    risk_approved_count: int
    risk_rejected_count: int
    created_order_ids: tuple[str, ...]
    cash: Decimal
    market_value: Decimal
    account_equity: Decimal
    snapshot_id: str | None
    idempotent_replay: bool
    no_future_session: bool


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
_FROZEN = PaperAccountStatus.FROZEN.value


def _fee_policy(config: dict[str, object]) -> FeePolicy:
    raw = cast(dict[str, object], config.get("fee_policy") or {})
    return FeePolicy(**{field: Decimal(str(raw[field])) for field in _FEE_FIELDS if field in raw})


def _slippage_policy(config: dict[str, object]) -> SlippagePolicy:
    raw = cast(dict[str, object], config.get("slippage_policy") or {})
    return SlippagePolicy(
        **{field: Decimal(str(raw[field])) for field in _SLIPPAGE_FIELDS if field in raw}
    )


def _max_volume_participation(config: dict[str, object]) -> Decimal | None:
    raw = config.get("max_volume_participation")
    return None if raw is None else Decimal(str(raw))


def _execution_config_fingerprint(config: dict[str, object]) -> str:
    return hashlib.sha256(canonical_json_bytes(config)).hexdigest()


def _to_date(value: object) -> date:
    if isinstance(value, datetime):
        return value.date()
    return cast(date, value)


class PaperSessionService:
    """Owns the paper session lifecycle and the atomic ADVANCE transaction.

    Only this service decides commit/rollback; the risk service and execution
    engine participate in its caller-owned SQLAlchemy session and never commit
    on their own.
    """

    def __init__(
        self,
        engine: Engine,
        repository: PaperRepository,
        market_data: MarketDataService,
        calendar_repository: TradingCalendarRepository,
        dataset_query: DatasetQueryService,
        risk_service: PaperRiskService,
    ) -> None:
        self.engine = engine
        self.repository = repository
        self.market_data = market_data
        self.calendars = calendar_repository
        self.dataset_query = dataset_query
        self.risk_service = risk_service
        self.execution_engine = PaperExecutionEngine()

    # --- creation ---
    def create_session(
        self,
        *,
        name: str,
        paper_account_id: str,
        market_data_profile_id: str,
        replay_start_date: date,
        replay_end_date: date | None,
        execution_config: dict[str, object],
        strategy_version_id: str | None = None,
    ) -> SessionView:
        if replay_end_date is not None and replay_end_date < replay_start_date:
            raise PaperError("REPLAY_RANGE_INVALID", "回放结束日期早于开始日期")
        profile = self.market_data.profiles.get(market_data_profile_id)
        snapshot = self.market_data.snapshot(market_data_profile_id)
        frozen = dict(snapshot)
        frozen["bars_dataset_id"] = profile.bars_dataset_id
        snapshot_json = json.dumps(frozen, sort_keys=True, default=str)
        fingerprint = _execution_config_fingerprint(execution_config)
        model = self.repository.create_session(
            name=name,
            paper_account_id=paper_account_id,
            market_data_profile_id=market_data_profile_id,
            market_data_snapshot_json=snapshot_json,
            market_data_snapshot_fingerprint=str(snapshot["snapshot_fingerprint"]),
            strategy_version_id=strategy_version_id,
            replay_start_date=replay_start_date,
            replay_end_date=replay_end_date,
            execution_config_json=json.dumps(execution_config, sort_keys=True, default=str),
            execution_config_fingerprint=fingerprint,
        )
        self.repository.append_audit(
            paper_account_id=paper_account_id,
            paper_session_id=model.id,
            event_type=AuditEventType.SESSION_CREATED.value,
            payload={
                "replay_start_date": replay_start_date.isoformat(),
                "replay_end_date": replay_end_date.isoformat() if replay_end_date else None,
                "execution_config_fingerprint": fingerprint,
                "strategy_version_id": strategy_version_id,
            },
        )
        return self._view(model)

    # --- lifecycle ---
    def start_session(self, session_id: str, *, expected_version: int | None = None) -> SessionView:
        return self._lifecycle(session_id, PaperSessionStatus.RUNNING, expected_version)

    def pause_session(self, session_id: str, *, expected_version: int | None = None) -> SessionView:
        return self._lifecycle(session_id, PaperSessionStatus.PAUSED, expected_version)

    def resume_session(
        self, session_id: str, *, expected_version: int | None = None
    ) -> SessionView:
        return self._lifecycle(session_id, PaperSessionStatus.RUNNING, expected_version)

    def stop_session(self, session_id: str, *, expected_version: int | None = None) -> SessionView:
        return self._lifecycle(session_id, PaperSessionStatus.STOPPED, expected_version)

    def _lifecycle(
        self,
        session_id: str,
        target: PaperSessionStatus,
        expected_version: int | None,
    ) -> SessionView:
        now = datetime.now(UTC)
        with Session(self.engine) as session:
            model = session.get(PaperSessionModel, session_id)
            if model is None:
                raise PaperError("PAPER_SESSION_NOT_FOUND", "模拟会话不存在")
            if expected_version is not None and model.version != expected_version:
                raise PaperError("SESSION_VERSION_CONFLICT", "会话版本冲突")
            current = PaperSessionStatus(model.status)
            validate_session_transition(current, target)
            if target == PaperSessionStatus.RUNNING:
                event = (
                    AuditEventType.SESSION_RESUMED.value
                    if current == PaperSessionStatus.PAUSED
                    else AuditEventType.SESSION_STARTED.value
                )
                if current == PaperSessionStatus.CREATED:
                    model.started_at = now
                model.paused_at = None
            elif target == PaperSessionStatus.PAUSED:
                event = AuditEventType.SESSION_PAUSED.value
                model.paused_at = now
            else:
                event = AuditEventType.SESSION_STOPPED.value
                model.stopped_at = now
            model.status = target.value
            model.version += 1
            model.updated_at = now
            session.add(
                PaperAuditEventModel(
                    id=str(uuid4()),
                    paper_account_id=model.paper_account_id,
                    paper_session_id=model.id,
                    event_type=event,
                    payload_json=json.dumps({"version": model.version}),
                    created_at=now,
                )
            )
            session.commit()
            return self._view(model)

    # --- advance ---
    def advance_session(self, request: AdvanceSessionRequest) -> PaperAdvanceResult:
        session_model = self.repository.get_session(request.paper_session_id)
        snapshot = cast(dict[str, object], json.loads(session_model.market_data_snapshot_json))
        calendar_version_id = str(snapshot["calendar_version_id"])

        open_dates = sorted(
            item.session_date
            for item in self.calendars.list_sessions(
                calendar_version_id, open_only=True, limit=5000
            )
        )
        target, sellable_from, strategy_next = self._select_target(
            session_model.current_session_date,
            open_dates,
            session_model.replay_start_date,
            session_model.replay_end_date,
        )
        if target is None:
            raise PaperError("NO_FUTURE_SESSION", "没有可推进的交易日")
        sellable_from = cast(date, sellable_from)

        exec_config = cast(dict[str, object], json.loads(session_model.execution_config_json))
        fee_policy = _fee_policy(exec_config)
        slippage_policy = _slippage_policy(exec_config)
        max_vol = _max_volume_participation(exec_config)

        instrument_map = self._instrument_map(session_model.market_data_profile_id)

        rows = self.dataset_query.bars(
            str(snapshot["bars_dataset_id"]),
            str(snapshot["bars_dataset_version_id"]),
            instrument_id=None,
            start=None,
            end=target,
            limit=1000,
        )
        bars_by_instrument, closes_history, last_valid_close = self._index_bars(rows, target)

        strategy = self._load_strategy(session_model, instrument_map)
        session_index = self._session_index(open_dates, session_model, target)

        with Session(self.engine) as session:
            session.connection().exec_driver_sql("BEGIN IMMEDIATE")
            try:
                model = session.get(PaperSessionModel, request.paper_session_id)
                if model is None:
                    raise PaperError("PAPER_SESSION_NOT_FOUND", "模拟会话不存在")
                account = session.get(PaperAccountModel, model.paper_account_id)
                if account is None:
                    raise PaperError("PAPER_ACCOUNT_NOT_FOUND", "模拟账户不存在")

                existing = session.scalar(
                    select(PaperSessionAdvanceModel).where(
                        PaperSessionAdvanceModel.paper_session_id == model.id,
                        PaperSessionAdvanceModel.idempotency_key == request.idempotency_key,
                    )
                )
                if existing is not None:
                    if existing.status == AdvanceStatus.COMPLETED.value:
                        return self._replay(session, existing, model, account)
                    if existing.status == AdvanceStatus.FAILED.value:
                        raise PaperError(
                            existing.error_code or "ADVANCE_FAILED", "advance 已失败"
                        )
                    raise PaperError("ADVANCE_IN_PROGRESS", "advance 正在进行中")

                if model.status != PaperSessionStatus.RUNNING.value:
                    raise PaperError("SESSION_NOT_RUNNING", "会话不在运行中")
                if model.version != request.expected_version:
                    raise PaperError("SESSION_VERSION_CONFLICT", "会话版本冲突")
                if (
                    request.expected_current_session_date is not None
                    and model.current_session_date != request.expected_current_session_date
                ):
                    raise PaperError("SESSION_VERSION_CONFLICT", "会话当前日期冲突")

                now = datetime.now(UTC)
                advance = PaperSessionAdvanceModel(
                    id=str(uuid4()),
                    paper_session_id=model.id,
                    idempotency_key=request.idempotency_key,
                    expected_session_date=target,
                    status=AdvanceStatus.PENDING.value,
                    created_at=now,
                )
                session.add(advance)

                executed_orders, fill_ids = self._execute_pending(
                    session,
                    model,
                    account,
                    target,
                    bars_by_instrument,
                    instrument_map,
                    fee_policy,
                    slippage_policy,
                    max_vol,
                    sellable_from,
                )

                snapshot_model, stale_ids = self._mark_to_market(
                    session, model, account, target, bars_by_instrument, last_valid_close
                )

                created_orders, approved, rejected, no_future = self._close_phase(
                    session,
                    model,
                    account,
                    target,
                    strategy_next,
                    bars_by_instrument,
                    last_valid_close,
                    closes_history,
                    strategy,
                    instrument_map,
                    fee_policy,
                    session_index,
                )

                previous_date = model.current_session_date
                model.current_session_date = target
                model.version += 1
                model.updated_at = now

                advance.status = AdvanceStatus.COMPLETED.value
                advance.resulting_session_date = target
                advance.completed_at = now

                session.add(
                    PaperAuditEventModel(
                        id=str(uuid4()),
                        paper_account_id=account.id,
                        paper_session_id=model.id,
                        event_type=AuditEventType.SESSION_ADVANCED.value,
                        payload_json=json.dumps(
                            {
                                "previous_session_date": previous_date.isoformat()
                                if previous_date
                                else None,
                                "resulting_session_date": target.isoformat(),
                                "executed_order_count": len(executed_orders),
                                "fill_count": len(fill_ids),
                                "risk_approved_count": approved,
                                "risk_rejected_count": rejected,
                                "stale_instrument_ids": stale_ids,
                                "account_equity": str(account.account_equity),
                                "cash": str(account.cash),
                                "market_value": str(account.market_value),
                                "no_future_session": no_future,
                            },
                            default=str,
                        ),
                        created_at=now,
                    )
                )
                session.commit()

                return PaperAdvanceResult(
                    paper_session_id=model.id,
                    previous_session_date=previous_date,
                    resulting_session_date=target,
                    session_version=model.version,
                    executed_orders=tuple(executed_orders),
                    fills=tuple(fill_ids),
                    risk_approved_count=approved,
                    risk_rejected_count=rejected,
                    created_order_ids=tuple(created_orders),
                    cash=account.cash,
                    market_value=account.market_value,
                    account_equity=account.account_equity,
                    snapshot_id=snapshot_model.id,
                    idempotent_replay=False,
                    no_future_session=no_future,
                )
            except PaperError:
                session.rollback()
                raise
            except AdvanceFatalError as error:
                session.rollback()
                self._mark_failed(request, target, error.code)
                raise PaperError(error.code, error.message) from error
            except Exception as error:
                session.rollback()
                self._mark_failed(request, target, "ADVANCE_FAILED")
                raise PaperError("ADVANCE_FAILED", "advance 执行失败") from error

    # --- advance helpers ---
    @staticmethod
    def _select_target(
        current: date | None,
        open_dates: list[date],
        replay_start: date,
        replay_end: date | None,
    ) -> tuple[date | None, date | None, date | None]:
        candidates = [
            d for d in open_dates if d >= replay_start and (replay_end is None or d <= replay_end)
        ]
        if current is None:
            target = candidates[0] if candidates else None
        else:
            target = next((d for d in candidates if d > current), None)
        if target is None:
            return None, None, None
        sellable_from = next((d for d in open_dates if d > target), target)
        strategy_next = next((d for d in candidates if d > target), None)
        return target, sellable_from, strategy_next

    @staticmethod
    def _session_index(
        open_dates: list[date], session_model: PaperSessionModel, target: date
    ) -> int:
        candidates = [
            d
            for d in open_dates
            if d >= session_model.replay_start_date
            and (session_model.replay_end_date is None or d <= session_model.replay_end_date)
        ]
        try:
            return candidates.index(target)
        except ValueError:
            return 0

    def _instrument_map(self, profile_id: str) -> dict[str, InstrumentSpec]:
        result: dict[str, InstrumentSpec] = {}
        for item in self.market_data.instruments(profile_id):
            result[str(item["instrument_id"])] = InstrumentSpec(
                str(item["instrument_id"]),
                str(item["security_type"]),
                int(str(item["lot_size"])),
                Decimal(str(item["price_tick"])),
                str(item["currency"]),
            )
        return result

    @staticmethod
    def _spec_for(instrument_id: str, instrument_map: dict[str, InstrumentSpec]) -> InstrumentSpec:
        spec = instrument_map.get(instrument_id)
        if spec is not None:
            return spec
        return InstrumentSpec(instrument_id, "EQUITY", 100, Decimal("0.01"))

    def _load_strategy(
        self, session_model: PaperSessionModel, instrument_map: dict[str, InstrumentSpec]
    ) -> StrategyLike | None:
        if session_model.strategy_version_id is None:
            return None
        version_model, strategy_type = StrategyLibrary(self.engine).version(
            session_model.strategy_version_id
        )
        spec = cast(dict[str, object], json.loads(version_model.strategy_spec_json))
        strategy = self._build_strategy(
            strategy_type, spec, instrument_map, session_model.replay_start_date
        )
        return cast(StrategyLike, strategy)

    def _build_strategy(
        self,
        strategy_type: str,
        spec: dict[str, object],
        instrument_map: dict[str, InstrumentSpec],
        first_trade_date: date,
    ) -> BuyAndHoldStrategy | TopNMomentumRotationStrategy:
        if strategy_type == "BUY_AND_HOLD":
            instrument = self._spec_for(str(spec.get("instrument_id", "")), instrument_map)
            return BuyAndHoldStrategy(
                instrument, Decimal(str(spec.get("target_weight", "1"))), first_trade_date
            )
        if strategy_type == "TOP_N_MOMENTUM_ROTATION":
            instrument_ids = [str(item) for item in cast(list[object], spec["instrument_ids"])]
            instruments = tuple(self._spec_for(item, instrument_map) for item in instrument_ids)
            return TopNMomentumRotationStrategy(
                instruments=instruments,
                lookback_sessions=int(str(spec["lookback_sessions"])),
                rebalance_every_n_sessions=int(str(spec["rebalance_every_n_sessions"])),
                top_n=int(str(spec["top_n"])),
                target_gross_exposure=Decimal(str(spec["target_gross_exposure"])),
                minimum_momentum=Decimal(str(spec.get("minimum_momentum", "0"))),
                cash_reserve_ratio=Decimal(str(spec.get("cash_reserve_ratio", "0"))),
            )
        raise PaperError("STRATEGY_UNSUPPORTED", "策略类型不受支持")

    @staticmethod
    def _index_bars(
        rows: list[dict[str, object]], target: date
    ) -> tuple[dict[str, dict[str, object]], dict[str, list[Decimal]], dict[str, Decimal]]:
        bars_by_instrument: dict[str, dict[str, object]] = {}
        closes_history: dict[str, list[Decimal]] = defaultdict(list)
        last_valid_close: dict[str, Decimal] = {}
        for row in rows:
            instrument_id = str(row["instrument_id"])
            close_value = row.get("close")
            if close_value is None:
                continue
            close = Decimal(str(close_value))
            closes_history[instrument_id].append(close)
            last_valid_close[instrument_id] = close
            if _to_date(row["trade_date"]) == target:
                bars_by_instrument[instrument_id] = row
        return bars_by_instrument, dict(closes_history), last_valid_close

    def _execute_pending(
        self,
        session: Session,
        model: PaperSessionModel,
        account: PaperAccountModel,
        target: date,
        bars_by_instrument: dict[str, dict[str, object]],
        instrument_map: dict[str, InstrumentSpec],
        fee_policy: FeePolicy,
        slippage_policy: SlippagePolicy,
        max_vol: Decimal | None,
        sellable_from: date,
    ) -> tuple[list[str], list[str]]:
        orders = session.scalars(
            select(PaperOrderModel)
            .where(
                PaperOrderModel.paper_session_id == model.id,
                PaperOrderModel.status == PaperOrderStatus.SUBMITTED.value,
                PaperOrderModel.execution_session_date == target,
            )
            .order_by(PaperOrderModel.created_at, PaperOrderModel.id)
        ).all()
        executed_orders: list[str] = []
        fill_ids: list[str] = []
        for order in orders:
            decision = session.get(PaperRiskDecisionModel, order.risk_decision_id)
            if decision is None or decision.decision != "APPROVE":
                raise AdvanceFatalError(
                    "CORRUPT_ORDER_RISK_DECISION", "Submitted 订单未关联 APPROVE 风控决策"
                )
            instrument = self._spec_for(order.instrument_id, instrument_map)
            lots = tuple(self._lot_snapshots(session, account.id, order.instrument_id))
            result = self.execution_engine.execute(
                PaperExecutionRequest(
                    order=PaperOrderSnapshot(
                        order.id,
                        order.instrument_id,
                        order.side,
                        order.requested_quantity,
                        order.order_type,
                        order.limit_price,
                        decision.decision,
                    ),
                    cash=account.cash,
                    lots=lots,
                    instrument=instrument,
                    bar=bars_by_instrument.get(order.instrument_id),
                    fee_policy=fee_policy,
                    slippage_policy=slippage_policy,
                    max_volume_participation=max_vol,
                    execution_date=target,
                    sellable_from_date=sellable_from,
                )
            )
            executed_orders.append(order.id)
            if result.status in ("FILLED", "PARTIALLY_FILLED"):
                fill_id = self._apply_fill(session, account, model, order, result, target)
                fill_ids.append(fill_id)
                if result.status == "PARTIALLY_FILLED":
                    order.status = PaperOrderStatus.EXPIRED.value
                    order.updated_at = datetime.now(UTC)
                    session.add(
                        PaperAuditEventModel(
                            id=str(uuid4()),
                            paper_account_id=account.id,
                            paper_session_id=model.id,
                            event_type=AuditEventType.ORDER_EXPIRED.value,
                            payload_json=json.dumps({"order_id": order.id}),
                            created_at=datetime.now(UTC),
                        )
                    )
            elif result.status == "REJECTED":
                order.status = PaperOrderStatus.REJECTED.value
                order.reject_reason = result.reject_reason
                order.updated_at = datetime.now(UTC)
                session.add(
                    PaperAuditEventModel(
                        id=str(uuid4()),
                        paper_account_id=account.id,
                        paper_session_id=model.id,
                        event_type=AuditEventType.ORDER_REJECTED.value,
                        payload_json=json.dumps(
                            {"order_id": order.id, "reject_reason": result.reject_reason}
                        ),
                        created_at=datetime.now(UTC),
                    )
                )
            elif result.status == "EXPIRED":
                order.status = PaperOrderStatus.EXPIRED.value
                order.reject_reason = result.reject_reason
                order.updated_at = datetime.now(UTC)
                session.add(
                    PaperAuditEventModel(
                        id=str(uuid4()),
                        paper_account_id=account.id,
                        paper_session_id=model.id,
                        event_type=AuditEventType.ORDER_EXPIRED.value,
                        payload_json=json.dumps(
                            {"order_id": order.id, "reject_reason": result.reject_reason}
                        ),
                        created_at=datetime.now(UTC),
                    )
                )
        return executed_orders, fill_ids

    def _apply_fill(
        self,
        session: Session,
        account: PaperAccountModel,
        model: PaperSessionModel,
        order: PaperOrderModel,
        result: PaperExecutionResult,
        target: date,
    ) -> str:
        now = datetime.now(UTC)
        fill = PaperFillModel(
            id=str(uuid4()),
            paper_order_id=order.id,
            paper_session_id=model.id,
            instrument_id=order.instrument_id,
            side=order.side,
            quantity=result.filled_quantity,
            raw_price=result.raw_price or Decimal("0"),
            slippage=result.slippage,
            fill_price=result.fill_price or Decimal("0"),
            commission=result.commission,
            stamp_tax=result.stamp_tax,
            transfer_fee=result.transfer_fee,
            total_fee=result.total_fee,
            trade_date=target,
            created_at=now,
        )
        session.add(fill)
        session.flush()

        account.cash += result.cash_delta
        if account.cash < 0:
            raise AdvanceFatalError("NEGATIVE_CASH", "现金余额为负")
        account.updated_at = now

        order.filled_quantity = result.filled_quantity
        order.accepted_quantity = result.accepted_quantity
        order.status = (
            PaperOrderStatus.FILLED.value
            if result.status == "FILLED"
            else PaperOrderStatus.PARTIALLY_FILLED.value
        )
        order.updated_at = now

        session.add(
            PaperLedgerEntryModel(
                id=str(uuid4()),
                paper_account_id=account.id,
                paper_session_id=model.id,
                paper_fill_id=fill.id,
                entry_type=LedgerEntryType.TRADE_SETTLEMENT.value,
                cash_delta=result.cash_delta,
                cash_after=account.cash,
                created_at=now,
            )
        )

        if order.side == "BUY" and result.new_lot is not None:
            self._apply_buy(session, account, order.instrument_id, result.new_lot, target)
        elif order.side == "SELL" and result.realized_pnl_delta is not None:
            self._apply_sell(
                session,
                account,
                order.instrument_id,
                result.lot_consumptions,
                result.realized_pnl_delta,
                target,
            )

        audit_type = (
            AuditEventType.ORDER_FILLED.value
            if order.status == PaperOrderStatus.FILLED.value
            else AuditEventType.ORDER_PARTIALLY_FILLED.value
        )
        session.add(
            PaperAuditEventModel(
                id=str(uuid4()),
                paper_account_id=account.id,
                paper_session_id=model.id,
                event_type=audit_type,
                payload_json=json.dumps({"order_id": order.id, "fill_id": fill.id}),
                created_at=now,
            )
        )
        return fill.id

    def _apply_buy(
        self,
        session: Session,
        account: PaperAccountModel,
        instrument_id: str,
        new_lot: NewLot,
        target: date,
    ) -> None:
        now = datetime.now(UTC)
        position = session.scalar(
            select(PaperPositionModel).where(
                PaperPositionModel.paper_account_id == account.id,
                PaperPositionModel.instrument_id == instrument_id,
            )
        )
        if position is None:
            position = PaperPositionModel(
                id=str(uuid4()),
                paper_account_id=account.id,
                instrument_id=instrument_id,
                total_quantity=0,
                sellable_quantity=0,
                average_cost=Decimal("0"),
                market_value=Decimal("0"),
                unrealized_pnl=Decimal("0"),
                realized_pnl=Decimal("0"),
                updated_at=now,
            )
            session.add(position)
            session.flush()
        session.add(
            PaperPositionLotModel(
                id=str(uuid4()),
                paper_account_id=account.id,
                paper_position_id=position.id,
                instrument_id=instrument_id,
                acquired_date=new_lot.acquired_date,
                quantity=new_lot.quantity,
                remaining_quantity=new_lot.quantity,
                cost_price=new_lot.cost_price,
                sellable_from_date=new_lot.sellable_from_date,
                created_at=now,
                updated_at=now,
            )
        )
        self._recompute_position(session, position, target)

    def _apply_sell(
        self,
        session: Session,
        account: PaperAccountModel,
        instrument_id: str,
        consumptions: tuple[LotConsumption, ...],
        realized_pnl_delta: Decimal,
        target: date,
    ) -> None:
        now = datetime.now(UTC)
        for consumption in consumptions:
            lot = session.get(PaperPositionLotModel, consumption.lot_id)
            if lot is None:
                raise AdvanceFatalError("LOT_MISSING", "卖出消费的持仓批次不存在")
            lot.remaining_quantity = consumption.remaining_quantity
            lot.updated_at = now
        position = session.scalar(
            select(PaperPositionModel).where(
                PaperPositionModel.paper_account_id == account.id,
                PaperPositionModel.instrument_id == instrument_id,
            )
        )
        if position is None:
            raise AdvanceFatalError("POSITION_MISSING", "卖出但无持仓")
        position.realized_pnl += realized_pnl_delta
        self._recompute_position(session, position, target)

    def _recompute_position(
        self, session: Session, position: PaperPositionModel, target: date
    ) -> None:
        now = datetime.now(UTC)
        lots = session.scalars(
            select(PaperPositionLotModel).where(
                PaperPositionLotModel.paper_position_id == position.id
            )
        ).all()
        total = sum(lot.remaining_quantity for lot in lots)
        sellable = sum(
            lot.remaining_quantity for lot in lots if lot.sellable_from_date <= target
        )
        total_cost = sum(
            (Decimal(lot.remaining_quantity) * lot.cost_price for lot in lots), Decimal("0")
        )
        position.total_quantity = total
        position.sellable_quantity = sellable
        position.average_cost = total_cost / total if total > 0 else Decimal("0")
        position.updated_at = now

    def _lot_snapshots(
        self, session: Session, account_id: str, instrument_id: str
    ) -> tuple[LotSnapshot, ...]:
        lots = session.scalars(
            select(PaperPositionLotModel).where(
                PaperPositionLotModel.paper_account_id == account_id,
                PaperPositionLotModel.instrument_id == instrument_id,
            )
        ).all()
        return tuple(
            LotSnapshot(
                lot.id,
                lot.instrument_id,
                lot.acquired_date,
                lot.quantity,
                lot.remaining_quantity,
                lot.cost_price,
                lot.sellable_from_date,
            )
            for lot in lots
        )

    def _mark_to_market(
        self,
        session: Session,
        model: PaperSessionModel,
        account: PaperAccountModel,
        target: date,
        bars_by_instrument: dict[str, dict[str, object]],
        last_valid_close: dict[str, Decimal],
    ) -> tuple[PaperAccountSnapshotModel, list[str]]:
        now = datetime.now(UTC)
        stale_ids: list[str] = []
        total_mv = Decimal("0")
        positions = session.scalars(
            select(PaperPositionModel).where(
                PaperPositionModel.paper_account_id == account.id
            )
        ).all()
        for position in positions:
            if position.total_quantity <= 0:
                position.market_value = Decimal("0")
                position.unrealized_pnl = Decimal("0")
                position.updated_at = now
                continue
            bar = bars_by_instrument.get(position.instrument_id)
            if bar is not None and bar.get("close") is not None:
                close = Decimal(str(bar["close"]))
            else:
                stale_close = last_valid_close.get(position.instrument_id)
                close = stale_close if stale_close is not None else position.average_cost
                stale_ids.append(position.instrument_id)
            market_value = Decimal(position.total_quantity) * close
            cost_basis = self._remaining_cost_basis(session, position.id)
            position.market_value = market_value
            position.unrealized_pnl = market_value - cost_basis
            position.updated_at = now
            total_mv += market_value

        account.market_value = total_mv
        account.account_equity = account.cash + total_mv
        account.updated_at = now

        previous = session.scalar(
            select(PaperAccountSnapshotModel)
            .where(PaperAccountSnapshotModel.paper_account_id == account.id)
            .order_by(PaperAccountSnapshotModel.session_date.desc())
            .limit(1)
        )
        previous_equity = previous.equity if previous is not None else account.initial_cash
        daily_pnl = account.account_equity - previous_equity
        cumulative_pnl = account.account_equity - account.initial_cash

        max_previous_equity = session.scalar(
            select(func.max(PaperAccountSnapshotModel.equity)).where(
                PaperAccountSnapshotModel.paper_account_id == account.id
            )
        )
        peak = max(
            account.initial_cash, max_previous_equity or Decimal("0"), account.account_equity
        )
        drawdown = account.account_equity / peak - Decimal("1") if peak > 0 else Decimal("0")

        snapshot = PaperAccountSnapshotModel(
            id=str(uuid4()),
            paper_account_id=account.id,
            paper_session_id=model.id,
            session_date=target,
            cash=account.cash,
            market_value=account.market_value,
            equity=account.account_equity,
            gross_exposure=account.market_value,
            daily_pnl=daily_pnl,
            cumulative_pnl=cumulative_pnl,
            drawdown=drawdown,
            created_at=now,
        )
        session.add(snapshot)
        session.flush()
        return snapshot, stale_ids

    def _remaining_cost_basis(self, session: Session, position_id: str) -> Decimal:
        lots = session.scalars(
            select(PaperPositionLotModel).where(
                PaperPositionLotModel.paper_position_id == position_id
            )
        ).all()
        return sum(
            (Decimal(lot.remaining_quantity) * lot.cost_price for lot in lots), Decimal("0")
        )

    def _position_lots(self, session: Session, account_id: str) -> tuple[PositionLot, ...]:
        lots = session.scalars(
            select(PaperPositionLotModel).where(
                PaperPositionLotModel.paper_account_id == account_id
            )
        ).all()
        return tuple(
            PositionLot(
                lot.instrument_id,
                lot.acquired_date,
                lot.quantity,
                lot.remaining_quantity,
                lot.cost_price,
                lot.sellable_from_date,
            )
            for lot in lots
        )

    def _close_phase(
        self,
        session: Session,
        model: PaperSessionModel,
        account: PaperAccountModel,
        target: date,
        strategy_next: date | None,
        bars_by_instrument: dict[str, dict[str, object]],
        last_valid_close: dict[str, Decimal],
        closes_history: dict[str, list[Decimal]],
        strategy: StrategyLike | None,
        instrument_map: dict[str, InstrumentSpec],
        fee_policy: FeePolicy,
        session_index: int,
    ) -> tuple[list[str], int, int, bool]:
        intents: list[PaperOrderIntentModel] = []
        existing = session.scalars(
            select(PaperOrderIntentModel)
            .where(PaperOrderIntentModel.paper_session_id == model.id)
            .order_by(PaperOrderIntentModel.created_at, PaperOrderIntentModel.id)
        ).all()
        for intent in existing:
            decision = session.scalar(
                select(PaperRiskDecisionModel).where(
                    PaperRiskDecisionModel.order_intent_id == intent.id
                )
            )
            if decision is None:
                intents.append(intent)

        no_future = strategy_next is None
        if strategy is not None:
            strategy_intents = strategy.on_close(
                signal_date=target,
                execution_date=strategy_next,
                bars=bars_by_instrument,
                cash=account.cash,
                equity=account.account_equity,
                lots=self._position_lots(session, account.id),
                closes_history=closes_history,
                session_index=session_index,
                fee_policy=fee_policy,
            )
            for order_intent in strategy_intents:
                intents.append(self._persist_strategy_intent(session, model, order_intent, target))

        created_order_ids: list[str] = []
        approved = 0
        rejected = 0
        freeze_handled = account.status == _FROZEN
        for intent in intents:
            reference_price = last_valid_close.get(intent.instrument_id, Decimal("0"))
            instrument = self._spec_for(intent.instrument_id, instrument_map)
            decision = self.risk_service.evaluate_intent_in_transaction(
                session=session,
                intent_id=intent.id,
                reference_price=reference_price,
                security_type=instrument.security_type,
                estimated_fee=Decimal("0"),
            )
            if decision.decision == "APPROVE":
                order = self._create_order(
                    session, model, intent, decision, target, PaperOrderStatus.SUBMITTED
                )
                created_order_ids.append(order.id)
                approved += 1
            else:
                order = self._create_order(
                    session, model, intent, decision, target, PaperOrderStatus.RISK_REJECTED
                )
                created_order_ids.append(order.id)
                rejected += 1
            if account.status == _FROZEN and not freeze_handled:
                freeze_handled = True
                self._cancel_pending_orders(session, model)
        return created_order_ids, approved, rejected, no_future

    def _persist_strategy_intent(
        self,
        session: Session,
        model: PaperSessionModel,
        order_intent: OrderIntent,
        target: date,
    ) -> PaperOrderIntentModel:
        now = datetime.now(UTC)
        intent = PaperOrderIntentModel(
            id=str(uuid4()),
            paper_session_id=model.id,
            source_type=IntentSourceType.STRATEGY.value,
            source_id=None,
            instrument_id=order_intent.instrument_id,
            side=order_intent.side.value,
            quantity=order_intent.quantity,
            order_type=order_intent.order_type.value,
            limit_price=None,
            signal_session_date=target,
            intended_execution_session=order_intent.intended_execution_date,
            strategy_version_id=model.strategy_version_id,
            reason=order_intent.strategy_reason,
            metadata_json=json.dumps(dict(order_intent.strategy_metadata), default=str),
            idempotency_key=f"strategy-{target.isoformat()}-{order_intent.client_order_id}",
            created_at=now,
        )
        session.add(intent)
        session.flush()
        session.add(
            PaperAuditEventModel(
                id=str(uuid4()),
                paper_account_id=model.paper_account_id,
                paper_session_id=model.id,
                event_type=AuditEventType.INTENT_CREATED.value,
                payload_json=json.dumps({"intent_id": intent.id}),
                created_at=now,
            )
        )
        return intent

    def _create_order(
        self,
        session: Session,
        model: PaperSessionModel,
        intent: PaperOrderIntentModel,
        decision: PaperRiskDecisionModel,
        target: date,
        status: PaperOrderStatus,
    ) -> PaperOrderModel:
        now = datetime.now(UTC)
        submitted = status == PaperOrderStatus.SUBMITTED
        order = PaperOrderModel(
            id=str(uuid4()),
            client_order_id=f"paper-{uuid4()}",
            paper_session_id=model.id,
            order_intent_id=intent.id,
            risk_decision_id=decision.id,
            instrument_id=intent.instrument_id,
            side=intent.side,
            requested_quantity=intent.quantity,
            accepted_quantity=0,
            filled_quantity=0,
            order_type=intent.order_type,
            limit_price=intent.limit_price,
            status=status.value,
            submitted_session_date=target if submitted else None,
            execution_session_date=intent.intended_execution_session,
            reject_reason=None if submitted else self._first_reason(decision.reason_codes_json),
            created_at=now,
            updated_at=now,
        )
        session.add(order)
        session.flush()
        session.add(
            PaperAuditEventModel(
                id=str(uuid4()),
                paper_account_id=model.paper_account_id,
                paper_session_id=model.id,
                event_type=AuditEventType.ORDER_CREATED.value,
                payload_json=json.dumps({"order_id": order.id, "intent_id": intent.id}),
                created_at=now,
            )
        )
        if submitted:
            session.add(
                PaperAuditEventModel(
                    id=str(uuid4()),
                    paper_account_id=model.paper_account_id,
                    paper_session_id=model.id,
                    event_type=AuditEventType.RISK_APPROVED.value,
                    payload_json=json.dumps({"order_id": order.id, "decision_id": decision.id}),
                    created_at=now,
                )
            )
            session.add(
                PaperAuditEventModel(
                    id=str(uuid4()),
                    paper_account_id=model.paper_account_id,
                    paper_session_id=model.id,
                    event_type=AuditEventType.ORDER_SUBMITTED.value,
                    payload_json=json.dumps({"order_id": order.id}),
                    created_at=now,
                )
            )
        else:
            session.add(
                PaperAuditEventModel(
                    id=str(uuid4()),
                    paper_account_id=model.paper_account_id,
                    paper_session_id=model.id,
                    event_type=AuditEventType.RISK_REJECTED.value,
                    payload_json=json.dumps(
                        {"order_id": order.id, "decision_id": decision.id}
                    ),
                    created_at=now,
                )
            )
        return order

    @staticmethod
    def _first_reason(reason_codes_json: str) -> str | None:
        reasons = cast(list[str], json.loads(reason_codes_json))
        return reasons[0] if reasons else None

    def _cancel_pending_orders(self, session: Session, model: PaperSessionModel) -> None:
        now = datetime.now(UTC)
        orders = session.scalars(
            select(PaperOrderModel).where(
                PaperOrderModel.paper_session_id == model.id,
                PaperOrderModel.status.in_(
                    (PaperOrderStatus.APPROVED.value, PaperOrderStatus.SUBMITTED.value)
                ),
            )
        ).all()
        for order in orders:
            order.status = PaperOrderStatus.CANCELLED.value
            order.updated_at = now
            session.add(
                PaperAuditEventModel(
                    id=str(uuid4()),
                    paper_account_id=model.paper_account_id,
                    paper_session_id=model.id,
                    event_type=AuditEventType.ORDER_CANCELLED.value,
                    payload_json=json.dumps({"order_id": order.id, "reason": "ACCOUNT_FROZEN"}),
                    created_at=now,
                )
            )

    def _replay(
        self,
        session: Session,
        advance: PaperSessionAdvanceModel,
        model: PaperSessionModel,
        account: PaperAccountModel,
    ) -> PaperAdvanceResult:
        target = advance.resulting_session_date
        snapshot_model = session.scalar(
            select(PaperAccountSnapshotModel).where(
                PaperAccountSnapshotModel.paper_session_id == model.id,
                PaperAccountSnapshotModel.session_date == target,
            )
        )
        fills = tuple(
            session.scalars(
                select(PaperFillModel.id).where(
                    PaperFillModel.paper_session_id == model.id,
                    PaperFillModel.trade_date == target,
                )
            )
        )
        executed_orders = tuple(
            session.scalars(
                select(PaperOrderModel.id).where(
                    PaperOrderModel.paper_session_id == model.id,
                    PaperOrderModel.execution_session_date == target,
                    PaperOrderModel.status.in_(
                        (
                            PaperOrderStatus.FILLED.value,
                            PaperOrderStatus.PARTIALLY_FILLED.value,
                            PaperOrderStatus.EXPIRED.value,
                            PaperOrderStatus.REJECTED.value,
                        )
                    ),
                )
            )
        )
        return PaperAdvanceResult(
            paper_session_id=model.id,
            previous_session_date=None,
            resulting_session_date=target,
            session_version=model.version,
            executed_orders=executed_orders,
            fills=fills,
            risk_approved_count=0,
            risk_rejected_count=0,
            created_order_ids=(),
            cash=account.cash,
            market_value=account.market_value,
            account_equity=account.account_equity,
            snapshot_id=snapshot_model.id if snapshot_model is not None else None,
            idempotent_replay=True,
            no_future_session=False,
        )

    def _mark_failed(
        self,
        request: AdvanceSessionRequest,
        target: date | None,
        error_code: str,
    ) -> None:
        now = datetime.now(UTC)
        with Session(self.engine) as session:
            model = session.get(PaperSessionModel, request.paper_session_id)
            if model is None:
                return
            model.status = PaperSessionStatus.FAILED.value
            model.version += 1
            model.updated_at = now
            advance = session.scalar(
                select(PaperSessionAdvanceModel).where(
                    PaperSessionAdvanceModel.paper_session_id == model.id,
                    PaperSessionAdvanceModel.idempotency_key == request.idempotency_key,
                )
            )
            if advance is None:
                advance = PaperSessionAdvanceModel(
                    id=str(uuid4()),
                    paper_session_id=model.id,
                    idempotency_key=request.idempotency_key,
                    expected_session_date=target or date(1970, 1, 1),
                    status=AdvanceStatus.FAILED.value,
                    error_code=error_code,
                    created_at=now,
                    completed_at=now,
                )
                session.add(advance)
            else:
                advance.status = AdvanceStatus.FAILED.value
                advance.error_code = error_code
                advance.completed_at = now
            session.add(
                PaperAuditEventModel(
                    id=str(uuid4()),
                    paper_account_id=model.paper_account_id,
                    paper_session_id=model.id,
                    event_type=AuditEventType.SESSION_FAILED.value,
                    payload_json=json.dumps(
                        {"error_code": error_code, "idempotency_key": request.idempotency_key}
                    ),
                    created_at=now,
                )
            )
            session.commit()

    @staticmethod
    def _view(model: PaperSessionModel) -> SessionView:
        return SessionView(
            paper_session_id=model.id,
            name=model.name,
            paper_account_id=model.paper_account_id,
            status=model.status,
            current_session_date=model.current_session_date,
            version=model.version,
            replay_start_date=model.replay_start_date,
            replay_end_date=model.replay_end_date,
        )
