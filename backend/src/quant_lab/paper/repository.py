from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import func, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from quant_lab.market_data.fingerprints import canonical_json_bytes
from quant_lab.paper.enums import (
    AuditEventType,
    LedgerEntryType,
    PaperAccountStatus,
    PaperOrderStatus,
    PaperSessionStatus,
    RiskPolicyStatus,
)
from quant_lab.paper.errors import PaperError
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
    PaperRiskPolicyModel,
    PaperRiskPolicyVersionModel,
    PaperSessionAdvanceModel,
    PaperSessionModel,
)
from quant_lab.paper.state import validate_order_transition


class PaperRepository:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    # --- account ---
    def create_account(
        self, *, name: str, initial_cash: Decimal, base_currency: str = "CNY"
    ) -> PaperAccountModel:
        if initial_cash <= 0:
            raise PaperError("INITIAL_CASH_INVALID", "初始资金必须大于0")
        now = datetime.now(UTC)
        with Session(self.engine) as session:
            model = PaperAccountModel(
                id=str(uuid4()),
                name=name,
                status=PaperAccountStatus.ACTIVE.value,
                base_currency=base_currency,
                initial_cash=initial_cash,
                cash=initial_cash,
                market_value=Decimal("0"),
                account_equity=initial_cash,
                created_at=now,
                updated_at=now,
            )
            session.add(model)
            session.flush()
            session.add(
                PaperLedgerEntryModel(
                    id=str(uuid4()),
                    paper_account_id=model.id,
                    entry_type=LedgerEntryType.INITIAL_DEPOSIT.value,
                    cash_delta=initial_cash,
                    cash_after=initial_cash,
                    created_at=now,
                )
            )
            session.add(
                PaperAuditEventModel(
                    id=str(uuid4()),
                    paper_account_id=model.id,
                    event_type=AuditEventType.ACCOUNT_CREATED.value,
                    payload_json=json.dumps({"name": name, "initial_cash": str(initial_cash)}),
                    created_at=now,
                )
            )
            session.commit()
            session.refresh(model)
            session.expunge(model)
            return model

    def get_account(self, account_id: str) -> PaperAccountModel:
        with Session(self.engine) as session:
            model = session.get(PaperAccountModel, account_id)
            if model is None:
                raise PaperError("PAPER_ACCOUNT_NOT_FOUND", "模拟账户不存在")
            session.expunge(model)
            return model

    def list_accounts(self) -> tuple[PaperAccountModel, ...]:
        with Session(self.engine) as session:
            values = tuple(
                session.scalars(select(PaperAccountModel).order_by(PaperAccountModel.created_at))
            )
            for value in values:
                session.expunge(value)
            return values

    # --- session ---
    def create_session(
        self,
        *,
        name: str,
        paper_account_id: str,
        market_data_profile_id: str,
        market_data_snapshot_json: str,
        market_data_snapshot_fingerprint: str,
        strategy_version_id: str | None = None,
    ) -> PaperSessionModel:
        self.get_account(paper_account_id)
        if strategy_version_id is not None:
            with Session(self.engine) as session:
                exists = session.execute(
                    text("SELECT 1 FROM strategy_versions WHERE id = :id"),
                    {"id": strategy_version_id},
                ).first()
                if exists is None:
                    raise PaperError("STRATEGY_VERSION_NOT_FOUND", "策略版本不存在")
        now = datetime.now(UTC)
        with Session(self.engine) as session:
            model = PaperSessionModel(
                id=str(uuid4()),
                name=name,
                paper_account_id=paper_account_id,
                market_data_profile_id=market_data_profile_id,
                market_data_snapshot_json=market_data_snapshot_json,
                market_data_snapshot_fingerprint=market_data_snapshot_fingerprint,
                strategy_version_id=strategy_version_id,
                status=PaperSessionStatus.CREATED.value,
                version=1,
                created_at=now,
                updated_at=now,
            )
            session.add(model)
            session.commit()
            session.refresh(model)
            session.expunge(model)
            return model

    def get_session(self, session_id: str) -> PaperSessionModel:
        with Session(self.engine) as session:
            model = session.get(PaperSessionModel, session_id)
            if model is None:
                raise PaperError("PAPER_SESSION_NOT_FOUND", "模拟会话不存在")
            session.expunge(model)
            return model

    def list_sessions(self, paper_account_id: str | None = None) -> tuple[PaperSessionModel, ...]:
        with Session(self.engine) as session:
            statement = select(PaperSessionModel).order_by(PaperSessionModel.created_at)
            if paper_account_id is not None:
                statement = statement.where(PaperSessionModel.paper_account_id == paper_account_id)
            values = tuple(session.scalars(statement))
            for value in values:
                session.expunge(value)
            return values

    # --- intent ---
    def create_intent(
        self,
        *,
        paper_session_id: str,
        source_type: str,
        source_id: str | None,
        instrument_id: str,
        side: str,
        quantity: int,
        order_type: str,
        limit_price: Decimal | None,
        signal_session_date: date,
        intended_execution_session: date,
        strategy_version_id: str | None,
        reason: str | None,
        metadata_json: str,
        idempotency_key: str,
    ) -> PaperOrderIntentModel:
        now = datetime.now(UTC)
        with Session(self.engine) as session:
            existing = session.scalar(
                select(PaperOrderIntentModel).where(
                    PaperOrderIntentModel.paper_session_id == paper_session_id,
                    PaperOrderIntentModel.idempotency_key == idempotency_key,
                )
            )
            if existing is not None:
                session.expunge(existing)
                return existing
            model = PaperOrderIntentModel(
                id=str(uuid4()),
                paper_session_id=paper_session_id,
                source_type=source_type,
                source_id=source_id,
                instrument_id=instrument_id,
                side=side,
                quantity=quantity,
                order_type=order_type,
                limit_price=limit_price,
                signal_session_date=signal_session_date,
                intended_execution_session=intended_execution_session,
                strategy_version_id=strategy_version_id,
                reason=reason,
                metadata_json=metadata_json,
                idempotency_key=idempotency_key,
                created_at=now,
            )
            session.add(model)
            session.commit()
            session.refresh(model)
            session.expunge(model)
            return model

    def get_intent(self, intent_id: str) -> PaperOrderIntentModel:
        with Session(self.engine) as session:
            model = session.get(PaperOrderIntentModel, intent_id)
            if model is None:
                raise PaperError("PAPER_INTENT_NOT_FOUND", "订单意图不存在")
            session.expunge(model)
            return model

    # --- risk policy ---
    def create_risk_policy(self, *, paper_account_id: str, name: str) -> PaperRiskPolicyModel:
        self.get_account(paper_account_id)
        now = datetime.now(UTC)
        with Session(self.engine) as session:
            model = PaperRiskPolicyModel(
                id=str(uuid4()),
                paper_account_id=paper_account_id,
                name=name,
                status=RiskPolicyStatus.ACTIVE.value,
                created_at=now,
            )
            session.add(model)
            session.commit()
            session.refresh(model)
            session.expunge(model)
            return model

    def create_risk_policy_version(
        self,
        *,
        risk_policy_id: str,
        max_single_order_notional: Decimal,
        max_single_position_weight: Decimal,
        max_total_exposure: Decimal,
        cash_buffer_ratio: Decimal,
        max_daily_loss: Decimal,
        max_drawdown: Decimal,
        max_open_orders: int,
        allowed_security_types: list[str],
    ) -> PaperRiskPolicyVersionModel:
        payload = {
            "max_single_order_notional": str(max_single_order_notional),
            "max_single_position_weight": str(max_single_position_weight),
            "max_total_exposure": str(max_total_exposure),
            "cash_buffer_ratio": str(cash_buffer_ratio),
            "max_daily_loss": str(max_daily_loss),
            "max_drawdown": str(max_drawdown),
            "max_open_orders": max_open_orders,
            "allowed_security_types": sorted(allowed_security_types),
        }
        fingerprint = hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
        now = datetime.now(UTC)
        with Session(self.engine) as session:
            policy = session.get(PaperRiskPolicyModel, risk_policy_id)
            if policy is None:
                raise PaperError("RISK_POLICY_NOT_FOUND", "风控策略不存在")
            version = (
                session.scalar(
                    select(func.max(PaperRiskPolicyVersionModel.version)).where(
                        PaperRiskPolicyVersionModel.risk_policy_id == risk_policy_id
                    )
                )
                or 0
            )
            model = PaperRiskPolicyVersionModel(
                id=str(uuid4()),
                risk_policy_id=risk_policy_id,
                version=int(version) + 1,
                max_single_order_notional=max_single_order_notional,
                max_single_position_weight=max_single_position_weight,
                max_total_exposure=max_total_exposure,
                cash_buffer_ratio=cash_buffer_ratio,
                max_daily_loss=max_daily_loss,
                max_drawdown=max_drawdown,
                max_open_orders=max_open_orders,
                allowed_security_types_json=json.dumps(
                    sorted(allowed_security_types), ensure_ascii=False
                ),
                policy_fingerprint=fingerprint,
                created_at=now,
            )
            session.add(model)
            session.commit()
            session.refresh(model)
            session.expunge(model)
            return model

    def get_policy_version(self, version_id: str) -> PaperRiskPolicyVersionModel:
        with Session(self.engine) as session:
            model = session.get(PaperRiskPolicyVersionModel, version_id)
            if model is None:
                raise PaperError("RISK_POLICY_VERSION_NOT_FOUND", "风控策略版本不存在")
            session.expunge(model)
            return model

    # --- risk decision ---
    def create_risk_decision(
        self,
        *,
        order_intent_id: str,
        decision: str,
        reason_codes: list[str],
        risk_policy_id: str,
        risk_policy_version_id: str,
        risk_policy_version: int,
        account_snapshot_json: str,
        position_snapshot_json: str,
        market_context_json: str,
    ) -> PaperRiskDecisionModel:
        now = datetime.now(UTC)
        with Session(self.engine) as session:
            model = PaperRiskDecisionModel(
                id=str(uuid4()),
                order_intent_id=order_intent_id,
                decision=decision,
                reason_codes_json=json.dumps(reason_codes),
                risk_policy_id=risk_policy_id,
                risk_policy_version_id=risk_policy_version_id,
                risk_policy_version=risk_policy_version,
                account_snapshot_json=account_snapshot_json,
                position_snapshot_json=position_snapshot_json,
                market_context_json=market_context_json,
                evaluated_at=now,
            )
            session.add(model)
            session.commit()
            session.refresh(model)
            session.expunge(model)
            return model

    # --- order ---
    def create_order(
        self,
        *,
        client_order_id: str,
        paper_session_id: str,
        order_intent_id: str,
        risk_decision_id: str,
        instrument_id: str,
        side: str,
        requested_quantity: int,
        order_type: str,
        limit_price: Decimal | None,
        status: str,
    ) -> PaperOrderModel:
        now = datetime.now(UTC)
        with Session(self.engine) as session:
            model = PaperOrderModel(
                id=str(uuid4()),
                client_order_id=client_order_id,
                paper_session_id=paper_session_id,
                order_intent_id=order_intent_id,
                risk_decision_id=risk_decision_id,
                instrument_id=instrument_id,
                side=side,
                requested_quantity=requested_quantity,
                accepted_quantity=0,
                filled_quantity=0,
                order_type=order_type,
                limit_price=limit_price,
                status=status,
                created_at=now,
                updated_at=now,
            )
            session.add(model)
            session.commit()
            session.refresh(model)
            session.expunge(model)
            return model

    def get_order(self, order_id: str) -> PaperOrderModel:
        with Session(self.engine) as session:
            model = session.get(PaperOrderModel, order_id)
            if model is None:
                raise PaperError("PAPER_ORDER_NOT_FOUND", "模拟订单不存在")
            session.expunge(model)
            return model

    def list_orders(self, paper_session_id: str) -> tuple[PaperOrderModel, ...]:
        with Session(self.engine) as session:
            values = tuple(
                session.scalars(
                    select(PaperOrderModel)
                    .where(PaperOrderModel.paper_session_id == paper_session_id)
                    .order_by(PaperOrderModel.created_at)
                )
            )
            for value in values:
                session.expunge(value)
            return values

    def transition_order(self, order_id: str, target_status: str) -> PaperOrderModel:
        now = datetime.now(UTC)
        with Session(self.engine) as session:
            model = session.get(PaperOrderModel, order_id)
            if model is None:
                raise PaperError("PAPER_ORDER_NOT_FOUND", "模拟订单不存在")
            validate_order_transition(
                PaperOrderStatus(model.status), PaperOrderStatus(target_status)
            )
            model.status = target_status
            model.updated_at = now
            session.commit()
            session.refresh(model)
            session.expunge(model)
            return model

    # --- fill ---
    def create_fill(
        self,
        *,
        paper_order_id: str,
        paper_session_id: str,
        instrument_id: str,
        side: str,
        quantity: int,
        raw_price: Decimal,
        slippage: Decimal,
        fill_price: Decimal,
        commission: Decimal,
        stamp_tax: Decimal,
        transfer_fee: Decimal,
        total_fee: Decimal,
        trade_date: date,
    ) -> PaperFillModel:
        now = datetime.now(UTC)
        with Session(self.engine) as session:
            model = PaperFillModel(
                id=str(uuid4()),
                paper_order_id=paper_order_id,
                paper_session_id=paper_session_id,
                instrument_id=instrument_id,
                side=side,
                quantity=quantity,
                raw_price=raw_price,
                slippage=slippage,
                fill_price=fill_price,
                commission=commission,
                stamp_tax=stamp_tax,
                transfer_fee=transfer_fee,
                total_fee=total_fee,
                trade_date=trade_date,
                created_at=now,
            )
            session.add(model)
            session.commit()
            session.refresh(model)
            session.expunge(model)
            return model

    def list_fills(self, paper_session_id: str) -> tuple[PaperFillModel, ...]:
        with Session(self.engine) as session:
            values = tuple(
                session.scalars(
                    select(PaperFillModel)
                    .where(PaperFillModel.paper_session_id == paper_session_id)
                    .order_by(PaperFillModel.created_at)
                )
            )
            for value in values:
                session.expunge(value)
            return values

    # --- position ---
    def upsert_position(
        self,
        *,
        paper_account_id: str,
        instrument_id: str,
        total_quantity: int,
        sellable_quantity: int,
        average_cost: Decimal,
        market_value: Decimal,
        unrealized_pnl: Decimal,
        realized_pnl: Decimal,
    ) -> PaperPositionModel:
        now = datetime.now(UTC)
        with Session(self.engine) as session:
            model = session.scalar(
                select(PaperPositionModel).where(
                    PaperPositionModel.paper_account_id == paper_account_id,
                    PaperPositionModel.instrument_id == instrument_id,
                )
            )
            if model is None:
                model = PaperPositionModel(
                    id=str(uuid4()),
                    paper_account_id=paper_account_id,
                    instrument_id=instrument_id,
                    total_quantity=total_quantity,
                    sellable_quantity=sellable_quantity,
                    average_cost=average_cost,
                    market_value=market_value,
                    unrealized_pnl=unrealized_pnl,
                    realized_pnl=realized_pnl,
                    updated_at=now,
                )
                session.add(model)
            else:
                model.total_quantity = total_quantity
                model.sellable_quantity = sellable_quantity
                model.average_cost = average_cost
                model.market_value = market_value
                model.unrealized_pnl = unrealized_pnl
                model.realized_pnl = realized_pnl
                model.updated_at = now
            session.commit()
            session.refresh(model)
            session.expunge(model)
            return model

    def create_position_lot(
        self,
        *,
        paper_account_id: str,
        paper_position_id: str,
        instrument_id: str,
        acquired_date: date,
        quantity: int,
        cost_price: Decimal,
        sellable_from_date: date,
    ) -> PaperPositionLotModel:
        now = datetime.now(UTC)
        with Session(self.engine) as session:
            model = PaperPositionLotModel(
                id=str(uuid4()),
                paper_account_id=paper_account_id,
                paper_position_id=paper_position_id,
                instrument_id=instrument_id,
                acquired_date=acquired_date,
                quantity=quantity,
                remaining_quantity=quantity,
                cost_price=cost_price,
                sellable_from_date=sellable_from_date,
                created_at=now,
                updated_at=now,
            )
            session.add(model)
            session.commit()
            session.refresh(model)
            session.expunge(model)
            return model

    def list_position_lots(
        self, paper_account_id: str
    ) -> tuple[PaperPositionLotModel, ...]:
        with Session(self.engine) as session:
            values = tuple(
                session.scalars(
                    select(PaperPositionLotModel)
                    .where(PaperPositionLotModel.paper_account_id == paper_account_id)
                    .order_by(PaperPositionLotModel.acquired_date)
                )
            )
            for value in values:
                session.expunge(value)
            return values

    # --- snapshot ---
    def create_snapshot(
        self,
        *,
        paper_account_id: str,
        paper_session_id: str,
        session_date: date,
        cash: Decimal,
        market_value: Decimal,
        equity: Decimal,
        gross_exposure: Decimal,
        daily_pnl: Decimal,
        cumulative_pnl: Decimal,
        drawdown: Decimal,
    ) -> PaperAccountSnapshotModel:
        now = datetime.now(UTC)
        with Session(self.engine) as session:
            model = PaperAccountSnapshotModel(
                id=str(uuid4()),
                paper_account_id=paper_account_id,
                paper_session_id=paper_session_id,
                session_date=session_date,
                cash=cash,
                market_value=market_value,
                equity=equity,
                gross_exposure=gross_exposure,
                daily_pnl=daily_pnl,
                cumulative_pnl=cumulative_pnl,
                drawdown=drawdown,
                created_at=now,
            )
            session.add(model)
            session.commit()
            session.refresh(model)
            session.expunge(model)
            return model

    def list_snapshots(self, paper_session_id: str) -> tuple[PaperAccountSnapshotModel, ...]:
        with Session(self.engine) as session:
            values = tuple(
                session.scalars(
                    select(PaperAccountSnapshotModel)
                    .where(PaperAccountSnapshotModel.paper_session_id == paper_session_id)
                    .order_by(PaperAccountSnapshotModel.session_date)
                )
            )
            for value in values:
                session.expunge(value)
            return values

    # --- ledger / audit ---
    def append_ledger(
        self,
        *,
        paper_account_id: str,
        entry_type: str,
        cash_delta: Decimal,
        cash_after: Decimal,
        paper_session_id: str | None = None,
        paper_fill_id: str | None = None,
        description: str | None = None,
    ) -> PaperLedgerEntryModel:
        now = datetime.now(UTC)
        with Session(self.engine) as session:
            model = PaperLedgerEntryModel(
                id=str(uuid4()),
                paper_account_id=paper_account_id,
                paper_session_id=paper_session_id,
                paper_fill_id=paper_fill_id,
                entry_type=entry_type,
                cash_delta=cash_delta,
                cash_after=cash_after,
                description=description,
                created_at=now,
            )
            session.add(model)
            session.commit()
            session.refresh(model)
            session.expunge(model)
            return model

    def append_audit(
        self,
        *,
        paper_account_id: str,
        event_type: str,
        payload: dict[str, object],
        paper_session_id: str | None = None,
    ) -> PaperAuditEventModel:
        now = datetime.now(UTC)
        with Session(self.engine) as session:
            model = PaperAuditEventModel(
                id=str(uuid4()),
                paper_account_id=paper_account_id,
                paper_session_id=paper_session_id,
                event_type=event_type,
                payload_json=json.dumps(payload, default=str),
                created_at=now,
            )
            session.add(model)
            session.commit()
            session.refresh(model)
            session.expunge(model)
            return model

    # --- advance ---
    def create_or_get_advance(
        self,
        *,
        paper_session_id: str,
        idempotency_key: str,
        expected_session_date: date,
    ) -> PaperSessionAdvanceModel:
        now = datetime.now(UTC)
        with Session(self.engine) as session:
            existing = session.scalar(
                select(PaperSessionAdvanceModel).where(
                    PaperSessionAdvanceModel.paper_session_id == paper_session_id,
                    PaperSessionAdvanceModel.idempotency_key == idempotency_key,
                )
            )
            if existing is not None:
                session.expunge(existing)
                return existing
            model = PaperSessionAdvanceModel(
                id=str(uuid4()),
                paper_session_id=paper_session_id,
                idempotency_key=idempotency_key,
                expected_session_date=expected_session_date,
                status="PENDING",
                created_at=now,
            )
            session.add(model)
            session.commit()
            session.refresh(model)
            session.expunge(model)
            return model

    # --- policy / decision queries ---
    def get_risk_policy(self, policy_id: str) -> PaperRiskPolicyModel:
        with Session(self.engine) as session:
            model = session.get(PaperRiskPolicyModel, policy_id)
            if model is None:
                raise PaperError("RISK_POLICY_NOT_FOUND", "风控策略不存在")
            session.expunge(model)
            return model

    def list_risk_policies(
        self, paper_account_id: str
    ) -> tuple[PaperRiskPolicyModel, ...]:
        with Session(self.engine) as session:
            values = tuple(
                session.scalars(
                    select(PaperRiskPolicyModel).where(
                        PaperRiskPolicyModel.paper_account_id == paper_account_id
                    )
                )
            )
            for value in values:
                session.expunge(value)
            return values

    def get_latest_policy_version(
        self, risk_policy_id: str
    ) -> PaperRiskPolicyVersionModel:
        with Session(self.engine) as session:
            model = session.scalar(
                select(PaperRiskPolicyVersionModel)
                .where(PaperRiskPolicyVersionModel.risk_policy_id == risk_policy_id)
                .order_by(PaperRiskPolicyVersionModel.version.desc())
                .limit(1)
            )
            if model is None:
                raise PaperError("RISK_POLICY_VERSION_NOT_FOUND", "风控策略版本不存在")
            session.expunge(model)
            return model

    def get_risk_decision_by_intent(self, order_intent_id: str) -> PaperRiskDecisionModel | None:
        with Session(self.engine) as session:
            model = session.scalar(
                select(PaperRiskDecisionModel).where(
                    PaperRiskDecisionModel.order_intent_id == order_intent_id
                )
            )
            if model is not None:
                session.expunge(model)
            return model

    def update_account_status(self, account_id: str, status: str) -> PaperAccountModel:
        now = datetime.now(UTC)
        with Session(self.engine) as session:
            model = session.get(PaperAccountModel, account_id)
            if model is None:
                raise PaperError("PAPER_ACCOUNT_NOT_FOUND", "模拟账户不存在")
            model.status = status
            model.updated_at = now
            session.commit()
            session.refresh(model)
            session.expunge(model)
            return model

    def count_open_orders(self, paper_session_id: str) -> int:
        with Session(self.engine) as session:
            return int(
                session.scalar(
                    select(func.count()).where(
                        PaperOrderModel.paper_session_id == paper_session_id,
                        PaperOrderModel.status.in_(
                            ("CREATED", "APPROVED", "SUBMITTED", "PARTIALLY_FILLED")
                        ),
                    )
                )
                or 0
            )

    def get_latest_snapshot(
        self, paper_account_id: str
    ) -> PaperAccountSnapshotModel | None:
        with Session(self.engine) as session:
            model = session.scalar(
                select(PaperAccountSnapshotModel)
                .where(PaperAccountSnapshotModel.paper_account_id == paper_account_id)
                .order_by(PaperAccountSnapshotModel.session_date.desc())
                .limit(1)
            )
            if model is not None:
                session.expunge(model)
            return model
