from __future__ import annotations

from decimal import Decimal

from quant_lab.paper.dto import (
    RISK_REASON_ORDER,
    RiskAccountSnapshot,
    RiskEvaluation,
    RiskMarketContext,
    RiskPolicyView,
    RiskPositionSnapshot,
    RiskReasonCode,
)
from quant_lab.paper.enums import RiskDecisionType


class RiskEngine:
    """Pure, deterministic pre-trade risk evaluation.

    This class performs no I/O: no SQLite, no FastAPI, no HTTP, no filesystem,
    and no MarketDataService access. All inputs are explicit value objects.
    """

    def evaluate(
        self,
        *,
        instrument_id: str,
        side: str,
        quantity: int,
        limit_price: Decimal | None,
        session_status: str,
        account_snapshot: RiskAccountSnapshot,
        position_snapshot: RiskPositionSnapshot | None,
        risk_policy: RiskPolicyView,
        market_context: RiskMarketContext,
        open_order_count: int,
    ) -> RiskEvaluation:
        metrics: dict[str, object] = {
            "estimated_order_notional": None,
            "estimated_post_trade_cash": None,
            "minimum_cash_required": None,
            "projected_position_weight": None,
            "projected_exposure_ratio": None,
            "daily_loss_ratio": str(account_snapshot.daily_loss_ratio),
            "drawdown_ratio": str(account_snapshot.drawdown_ratio),
            "open_order_count": open_order_count,
        }
        if (
            account_snapshot.account_equity <= 0
            or market_context.reference_price <= 0
            or not market_context.reference_price.is_finite()
            or not account_snapshot.account_equity.is_finite()
            or not account_snapshot.cash.is_finite()
            or not market_context.security_type
        ):
            return RiskEvaluation(
                decision=RiskDecisionType.REJECT.value,
                reason_codes=(RiskReasonCode.RISK_CONTEXT_INVALID.value,),
                policy_fingerprint=risk_policy.fingerprint,
                evaluated_metrics=metrics,
                freeze_required=False,
            )

        reasons: list[str] = []
        if account_snapshot.status == "FROZEN":
            reasons.append(RiskReasonCode.ACCOUNT_FROZEN.value)
        if session_status != "RUNNING":
            reasons.append(RiskReasonCode.SESSION_NOT_RUNNING.value)
        if market_context.security_type not in risk_policy.allowed_security_types:
            reasons.append(RiskReasonCode.SECURITY_NOT_ALLOWED.value)

        reference_price = market_context.reference_price
        if limit_price is not None and limit_price.is_finite():
            if side == "BUY":
                reference_price = max(reference_price, limit_price)
            else:
                reference_price = min(reference_price, limit_price)
        estimated_notional = Decimal(quantity) * reference_price
        metrics["estimated_order_notional"] = str(estimated_notional)
        if estimated_notional > risk_policy.max_single_order_notional:
            reasons.append(RiskReasonCode.ORDER_NOTIONAL_LIMIT.value)

        if side == "BUY":
            estimated_post_trade_cash = (
                account_snapshot.cash - estimated_notional - market_context.estimated_fee
            )
            minimum_cash_required = (
                account_snapshot.account_equity * risk_policy.cash_buffer_ratio
            )
            metrics["estimated_post_trade_cash"] = str(estimated_post_trade_cash)
            metrics["minimum_cash_required"] = str(minimum_cash_required)
            if estimated_post_trade_cash < minimum_cash_required:
                reasons.append(RiskReasonCode.CASH_BUFFER_LIMIT.value)

            current_instrument_value = (
                position_snapshot.market_value if position_snapshot is not None else Decimal("0")
            )
            projected_instrument_value = current_instrument_value + estimated_notional
            projected_position_weight = projected_instrument_value / account_snapshot.account_equity
            metrics["projected_position_weight"] = str(projected_position_weight)
            if projected_position_weight > risk_policy.max_single_position_weight:
                reasons.append(RiskReasonCode.POSITION_CONCENTRATION_LIMIT.value)

            projected_gross_exposure = account_snapshot.gross_exposure + estimated_notional
            projected_exposure_ratio = projected_gross_exposure / account_snapshot.account_equity
            metrics["projected_exposure_ratio"] = str(projected_exposure_ratio)
            if projected_exposure_ratio > risk_policy.max_total_exposure:
                reasons.append(RiskReasonCode.TOTAL_EXPOSURE_LIMIT.value)

        if open_order_count >= risk_policy.max_open_orders:
            reasons.append(RiskReasonCode.OPEN_ORDER_LIMIT.value)

        if account_snapshot.daily_loss_ratio >= risk_policy.max_daily_loss:
            reasons.append(RiskReasonCode.DAILY_LOSS_LIMIT.value)
        if account_snapshot.drawdown_ratio >= risk_policy.max_drawdown:
            reasons.append(RiskReasonCode.DRAWDOWN_LIMIT.value)

        ordered_reasons = tuple(code for code in RISK_REASON_ORDER if code in set(reasons))
        freeze_required = (
            RiskReasonCode.DAILY_LOSS_LIMIT.value in ordered_reasons
            or RiskReasonCode.DRAWDOWN_LIMIT.value in ordered_reasons
        )
        decision = (
            RiskDecisionType.APPROVE.value
            if not ordered_reasons
            else RiskDecisionType.REJECT.value
        )
        return RiskEvaluation(
            decision=decision,
            reason_codes=ordered_reasons,
            policy_fingerprint=risk_policy.fingerprint,
            evaluated_metrics=metrics,
            freeze_required=freeze_required,
        )
