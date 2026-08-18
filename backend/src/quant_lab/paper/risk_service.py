from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from quant_lab.paper.dto import (
    RiskAccountSnapshot,
    RiskEvaluation,
    RiskMarketContext,
    RiskPolicyView,
    RiskPositionSnapshot,
    RiskReasonCode,
)
from quant_lab.paper.enums import AuditEventType, PaperAccountStatus, RiskDecisionType
from quant_lab.paper.errors import PaperError
from quant_lab.paper.models import (
    PaperAccountModel,
    PaperAccountSnapshotModel,
    PaperAuditEventModel,
    PaperOrderIntentModel,
    PaperOrderModel,
    PaperPositionModel,
    PaperRiskDecisionModel,
    PaperRiskPolicyModel,
    PaperRiskPolicyVersionModel,
    PaperSessionModel,
)
from quant_lab.paper.repository import PaperRepository
from quant_lab.paper.risk import RiskEngine


class PaperRiskService:
    """Loads state, builds DTOs, invokes the pure RiskEngine, persists decisions.

    Stops at PaperRiskDecision: it never creates PaperOrder. Daily-loss /
    drawdown rejections also atomically freeze the account.

    evaluate_intent owns its transaction for standalone callers (Phase 5B),
    while evaluate_intent_in_transaction participates in a caller-owned
    SQLAlchemy session so the Phase 5D advance pipeline can commit the risk
    decision together with the order, cash, and position state.
    """

    def __init__(self, repository: PaperRepository, engine: RiskEngine) -> None:
        self.repository = repository
        self.engine = engine

    def evaluate_intent(
        self,
        *,
        intent_id: str,
        reference_price: Decimal,
        security_type: str,
        estimated_fee: Decimal,
    ) -> PaperRiskDecisionModel:
        with Session(self.repository.engine) as session:
            decision = self.evaluate_intent_in_transaction(
                session=session,
                intent_id=intent_id,
                reference_price=reference_price,
                security_type=security_type,
                estimated_fee=estimated_fee,
            )
            session.commit()
            session.refresh(decision)
            session.expunge(decision)
            return decision

    def evaluate_intent_in_transaction(
        self,
        *,
        session: Session,
        intent_id: str,
        reference_price: Decimal,
        security_type: str,
        estimated_fee: Decimal,
    ) -> PaperRiskDecisionModel:
        existing = session.scalar(
            select(PaperRiskDecisionModel).where(
                PaperRiskDecisionModel.order_intent_id == intent_id
            )
        )
        if existing is not None:
            return existing

        intent = session.get(PaperOrderIntentModel, intent_id)
        if intent is None:
            raise PaperError("PAPER_INTENT_NOT_FOUND", "订单意图不存在")
        paper_session = session.get(PaperSessionModel, intent.paper_session_id)
        if paper_session is None:
            raise PaperError("PAPER_SESSION_NOT_FOUND", "模拟会话不存在")
        account = session.get(PaperAccountModel, paper_session.paper_account_id)
        if account is None:
            raise PaperError("PAPER_ACCOUNT_NOT_FOUND", "模拟账户不存在")

        policy = self._active_policy(session, account.id)
        version = self._latest_policy_version(session, policy.id)
        latest_snapshot = self._latest_snapshot(session, account.id)

        daily_loss_ratio, drawdown_ratio = _risk_ratios(latest_snapshot)
        account_snapshot = RiskAccountSnapshot(
            account_id=account.id,
            status=account.status,
            cash=account.cash,
            market_value=account.market_value,
            account_equity=account.account_equity,
            gross_exposure=account.market_value,
            daily_loss_ratio=daily_loss_ratio,
            drawdown_ratio=drawdown_ratio,
        )
        position = session.scalar(
            select(PaperPositionModel).where(
                PaperPositionModel.paper_account_id == account.id,
                PaperPositionModel.instrument_id == intent.instrument_id,
            )
        )
        position_snapshot = (
            RiskPositionSnapshot(
                instrument_id=position.instrument_id,
                total_quantity=position.total_quantity,
                sellable_quantity=position.sellable_quantity,
                market_value=position.market_value,
            )
            if position is not None
            else None
        )
        market_context = RiskMarketContext(
            instrument_id=intent.instrument_id,
            security_type=security_type,
            reference_price=reference_price,
            estimated_fee=estimated_fee,
            session_date=paper_session.current_session_date or intent.signal_session_date,
        )
        policy_view = RiskPolicyView(
            policy_id=policy.id,
            version_id=version.id,
            version=version.version,
            fingerprint=version.policy_fingerprint,
            max_single_order_notional=version.max_single_order_notional,
            max_single_position_weight=version.max_single_position_weight,
            max_total_exposure=version.max_total_exposure,
            cash_buffer_ratio=version.cash_buffer_ratio,
            max_daily_loss=version.max_daily_loss,
            max_drawdown=version.max_drawdown,
            max_open_orders=version.max_open_orders,
            allowed_security_types=frozenset(json.loads(version.allowed_security_types_json)),
        )
        open_order_count = self._count_open_orders(session, paper_session.id)

        try:
            evaluation = self.engine.evaluate(
                instrument_id=intent.instrument_id,
                side=intent.side,
                quantity=intent.quantity,
                limit_price=intent.limit_price,
                session_status=paper_session.status,
                account_snapshot=account_snapshot,
                position_snapshot=position_snapshot,
                risk_policy=policy_view,
                market_context=market_context,
                open_order_count=open_order_count,
            )
        except Exception:
            evaluation = RiskEvaluation(
                decision=RiskDecisionType.REJECT.value,
                reason_codes=(RiskReasonCode.RISK_ENGINE_ERROR.value,),
                policy_fingerprint=version.policy_fingerprint,
                evaluated_metrics={},
                freeze_required=False,
            )

        return self._persist(
            session=session,
            intent_id=intent.id,
            account=account,
            policy=policy,
            version=version,
            evaluation=evaluation,
            account_snapshot=account_snapshot,
            position_snapshot=position_snapshot,
            market_context=market_context,
        )

    def freeze_account(self, *, account_id: str, actor: str) -> PaperAccountModel:
        if actor not in {"USER", "RISK_ENGINE"}:
            raise PaperError("FREEZE_NOT_AUTHORIZED", "无权限冻结账户")
        return self._set_frozen(account_id, True)

    def unfreeze_account(self, *, account_id: str, actor: str) -> PaperAccountModel:
        if actor != "USER":
            raise PaperError("UNFREEZE_NOT_AUTHORIZED", "仅用户可解除冻结")
        return self._set_frozen(account_id, False)

    def _active_policy(self, session: Session, account_id: str) -> PaperRiskPolicyModel:
        policy = session.scalar(
            select(PaperRiskPolicyModel).where(
                PaperRiskPolicyModel.paper_account_id == account_id,
                PaperRiskPolicyModel.status == "ACTIVE",
            )
        )
        if policy is None:
            raise PaperError("RISK_POLICY_NOT_FOUND", "账户无ACTIVE风控策略")
        return policy

    def _latest_policy_version(
        self, session: Session, risk_policy_id: str
    ) -> PaperRiskPolicyVersionModel:
        version = session.scalar(
            select(PaperRiskPolicyVersionModel)
            .where(PaperRiskPolicyVersionModel.risk_policy_id == risk_policy_id)
            .order_by(PaperRiskPolicyVersionModel.version.desc())
            .limit(1)
        )
        if version is None:
            raise PaperError("RISK_POLICY_VERSION_NOT_FOUND", "风控策略版本不存在")
        return version

    def _latest_snapshot(
        self, session: Session, account_id: str
    ) -> PaperAccountSnapshotModel | None:
        return session.scalar(
            select(PaperAccountSnapshotModel)
            .where(PaperAccountSnapshotModel.paper_account_id == account_id)
            .order_by(PaperAccountSnapshotModel.session_date.desc())
            .limit(1)
        )

    def _count_open_orders(self, session: Session, paper_session_id: str) -> int:
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

    def _persist(
        self,
        *,
        session: Session,
        intent_id: str,
        account: PaperAccountModel,
        policy: PaperRiskPolicyModel,
        version: PaperRiskPolicyVersionModel,
        evaluation: RiskEvaluation,
        account_snapshot: RiskAccountSnapshot,
        position_snapshot: RiskPositionSnapshot | None,
        market_context: RiskMarketContext,
    ) -> PaperRiskDecisionModel:
        now = datetime.now(UTC)
        decision = PaperRiskDecisionModel(
            id=str(uuid4()),
            order_intent_id=intent_id,
            decision=evaluation.decision,
            reason_codes_json=json.dumps(evaluation.reason_codes),
            risk_policy_id=policy.id,
            risk_policy_version_id=version.id,
            risk_policy_version=version.version,
            account_snapshot_json=json.dumps(
                {
                    "account_id": account_snapshot.account_id,
                    "status": account_snapshot.status,
                    "cash": str(account_snapshot.cash),
                    "market_value": str(account_snapshot.market_value),
                    "account_equity": str(account_snapshot.account_equity),
                    "gross_exposure": str(account_snapshot.gross_exposure),
                    "daily_loss_ratio": str(account_snapshot.daily_loss_ratio),
                    "drawdown_ratio": str(account_snapshot.drawdown_ratio),
                },
                default=str,
            ),
            position_snapshot_json=json.dumps(
                (
                    {
                        "instrument_id": position_snapshot.instrument_id,
                        "total_quantity": position_snapshot.total_quantity,
                        "sellable_quantity": position_snapshot.sellable_quantity,
                        "market_value": str(position_snapshot.market_value),
                    }
                    if position_snapshot is not None
                    else {}
                ),
                default=str,
            ),
            market_context_json=json.dumps(
                {
                    "instrument_id": market_context.instrument_id,
                    "security_type": market_context.security_type,
                    "reference_price": str(market_context.reference_price),
                    "estimated_fee": str(market_context.estimated_fee),
                    "session_date": market_context.session_date.isoformat(),
                    "evaluated_metrics": evaluation.evaluated_metrics,
                },
                default=str,
            ),
            evaluated_at=now,
        )
        session.add(decision)
        session.flush()
        if evaluation.freeze_required and account.status != PaperAccountStatus.FROZEN.value:
            account.status = PaperAccountStatus.FROZEN.value
            account.updated_at = now
            session.add(
                PaperAuditEventModel(
                    id=str(uuid4()),
                    paper_account_id=account.id,
                    event_type=AuditEventType.ACCOUNT_FROZEN.value,
                    payload_json=json.dumps(
                        {"reason_codes": evaluation.reason_codes, "actor": "RISK_ENGINE"}
                    ),
                    created_at=now,
                )
            )
        if evaluation.reason_codes == (RiskReasonCode.RISK_ENGINE_ERROR.value,):
            session.add(
                PaperAuditEventModel(
                    id=str(uuid4()),
                    paper_account_id=account.id,
                    event_type="RISK_ENGINE_ERROR",
                    payload_json=json.dumps({"intent_id": intent_id}),
                    created_at=now,
                )
            )
        return decision

    def _set_frozen(self, account_id: str, frozen: bool) -> PaperAccountModel:
        now = datetime.now(UTC)
        target = PaperAccountStatus.FROZEN.value if frozen else PaperAccountStatus.ACTIVE.value
        with Session(self.repository.engine) as session:
            account = session.get(PaperAccountModel, account_id)
            if account is None:
                raise PaperError("PAPER_ACCOUNT_NOT_FOUND", "模拟账户不存在")
            if account.status == target:
                session.expunge(account)
                return account
            account.status = target
            account.updated_at = now
            event = (
                AuditEventType.ACCOUNT_FROZEN.value
                if frozen
                else AuditEventType.ACCOUNT_UNFROZEN.value
            )
            session.add(
                PaperAuditEventModel(
                    id=str(uuid4()),
                    paper_account_id=account_id,
                    event_type=event,
                    payload_json=json.dumps({"actor": "USER"}),
                    created_at=now,
                )
            )
            session.commit()
            session.refresh(account)
            session.expunge(account)
            return account


def _risk_ratios(snapshot: PaperAccountSnapshotModel | None) -> tuple[Decimal, Decimal]:
    if snapshot is None:
        return Decimal("0"), Decimal("0")
    daily_pnl = snapshot.daily_pnl
    equity = snapshot.equity
    previous_equity = equity - daily_pnl
    daily_loss_ratio = Decimal("0")
    if previous_equity > 0:
        daily_loss_ratio = max(Decimal("0"), -daily_pnl / previous_equity)
    drawdown_ratio = max(Decimal("0"), -snapshot.drawdown)
    return daily_loss_ratio, drawdown_ratio
