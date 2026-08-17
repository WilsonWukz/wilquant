from __future__ import annotations

from decimal import Decimal

from quant_lab.paper.enums import RiskPolicyStatus
from quant_lab.paper.errors import PaperError
from quant_lab.paper.models import (
    PaperRiskPolicyModel,
    PaperRiskPolicyVersionModel,
)
from quant_lab.paper.repository import PaperRepository


class PaperRiskPolicyService:
    """Versioned risk policy service.

    A paper account has at most one ACTIVE policy at a time (enforced here,
    not by a DB partial-unique constraint). Policy changes create a new
    immutable version; existing RiskDecisions keep pointing at their old
    version.
    """

    def __init__(self, repository: PaperRepository) -> None:
        self.repository = repository

    def create_policy(self, *, paper_account_id: str, name: str) -> PaperRiskPolicyModel:
        if self.get_active_policy(paper_account_id=paper_account_id) is not None:
            raise PaperError("RISK_POLICY_ALREADY_ACTIVE", "账户已存在ACTIVE风控策略")
        return self.repository.create_risk_policy(paper_account_id=paper_account_id, name=name)

    def create_version(
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
        self._validate_ratios(
            cash_buffer_ratio=cash_buffer_ratio,
            max_single_position_weight=max_single_position_weight,
            max_total_exposure=max_total_exposure,
            max_daily_loss=max_daily_loss,
            max_drawdown=max_drawdown,
        )
        return self.repository.create_risk_policy_version(
            risk_policy_id=risk_policy_id,
            max_single_order_notional=max_single_order_notional,
            max_single_position_weight=max_single_position_weight,
            max_total_exposure=max_total_exposure,
            cash_buffer_ratio=cash_buffer_ratio,
            max_daily_loss=max_daily_loss,
            max_drawdown=max_drawdown,
            max_open_orders=max_open_orders,
            allowed_security_types=allowed_security_types,
        )

    def get_active_policy(self, *, paper_account_id: str) -> PaperRiskPolicyModel | None:
        for policy in self.repository.list_risk_policies(paper_account_id):
            if policy.status == RiskPolicyStatus.ACTIVE.value:
                return policy
        return None

    def get_latest_version(self, *, risk_policy_id: str) -> PaperRiskPolicyVersionModel:
        return self.repository.get_latest_policy_version(risk_policy_id)

    @staticmethod
    def _validate_ratios(
        *,
        cash_buffer_ratio: Decimal,
        max_single_position_weight: Decimal,
        max_total_exposure: Decimal,
        max_daily_loss: Decimal,
        max_drawdown: Decimal,
    ) -> None:
        if not Decimal("0") <= cash_buffer_ratio < Decimal("1"):
            raise PaperError("RISK_POLICY_INVALID", "cash_buffer_ratio 必须在 [0,1)")
        if not Decimal("0") < max_single_position_weight <= Decimal("1"):
            raise PaperError("RISK_POLICY_INVALID", "max_single_position_weight 必须在 (0,1]")
        if not Decimal("0") < max_total_exposure <= Decimal("1"):
            raise PaperError("RISK_POLICY_INVALID", "max_total_exposure 必须在 (0,1]")
        if not Decimal("0") <= max_daily_loss <= Decimal("1"):
            raise PaperError("RISK_POLICY_INVALID", "max_daily_loss 必须在 [0,1]")
        if not Decimal("0") <= max_drawdown <= Decimal("1"):
            raise PaperError("RISK_POLICY_INVALID", "max_drawdown 必须在 [0,1]")
