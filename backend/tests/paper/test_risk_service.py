from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
import sqlalchemy as sa
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from quant_lab.paper.dto import RiskReasonCode
from quant_lab.paper.enums import (
    IntentSourceType,
    PaperAccountStatus,
    PaperSessionStatus,
)
from quant_lab.paper.errors import PaperError
from quant_lab.paper.models import (
    PaperAuditEventModel,
    PaperSessionModel,
)
from quant_lab.paper.policy_service import PaperRiskPolicyService
from quant_lab.paper.repository import PaperRepository
from quant_lab.paper.risk import RiskEngine
from quant_lab.paper.risk_service import PaperRiskService


def _running_session(repository: PaperRepository, engine, account_id: str) -> str:
    session = repository.create_session(
        name="sess",
        paper_account_id=account_id,
        market_data_profile_id="p",
        market_data_snapshot_json="{}",
        market_data_snapshot_fingerprint="f" * 64,
    )
    with Session(engine) as s:
        model = s.get(PaperSessionModel, session.id)
        model.status = PaperSessionStatus.RUNNING.value
        s.commit()
    return session.id


def _intent(repository: PaperRepository, session_id: str, *, idempotency_key: str = "k1") -> str:
    model = repository.create_intent(
        paper_session_id=session_id,
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
        idempotency_key=idempotency_key,
    )
    return model.id


def _policy_with_version(policy_service: PaperRiskPolicyService, account_id: str, **overrides):
    policy = policy_service.create_policy(paper_account_id=account_id, name="p")
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
    fields.update(overrides)
    version = policy_service.create_version(risk_policy_id=policy.id, **fields)
    return policy, version


def _service(repository: PaperRepository) -> PaperRiskService:
    return PaperRiskService(repository, RiskEngine())


def test_approve_decision_persisted(repository, engine):
    account = repository.create_account(name="a", initial_cash=Decimal("100000"))
    session_id = _running_session(repository, engine, account.id)
    intent_id = _intent(repository, session_id)
    service = _service(repository)
    policy_service = PaperRiskPolicyService(repository)
    _policy_with_version(policy_service, account.id)
    decision = service.evaluate_intent(
        intent_id=intent_id,
        reference_price=Decimal("10"),
        security_type="EQUITY",
        estimated_fee=Decimal("0"),
    )
    assert decision.decision == "APPROVE"
    assert decision.reason_codes_json == "[]"


def test_reject_decision_persisted(repository, engine):
    account = repository.create_account(name="a", initial_cash=Decimal("100000"))
    session_id = _running_session(repository, engine, account.id)
    intent_id = _intent(repository, session_id)
    service = _service(repository)
    policy_service = PaperRiskPolicyService(repository)
    _policy_with_version(policy_service, account.id, max_single_order_notional=Decimal("10"))
    decision = service.evaluate_intent(
        intent_id=intent_id,
        reference_price=Decimal("10"),
        security_type="EQUITY",
        estimated_fee=Decimal("0"),
    )
    assert decision.decision == "REJECT"
    assert RiskReasonCode.ORDER_NOTIONAL_LIMIT.value in decision.reason_codes_json


def test_duplicate_evaluation_idempotent(repository, engine):
    account = repository.create_account(name="a", initial_cash=Decimal("100000"))
    session_id = _running_session(repository, engine, account.id)
    intent_id = _intent(repository, session_id)
    service = _service(repository)
    policy_service = PaperRiskPolicyService(repository)
    _policy_with_version(policy_service, account.id)
    first = service.evaluate_intent(
        intent_id=intent_id,
        reference_price=Decimal("10"),
        security_type="EQUITY",
        estimated_fee=Decimal("0"),
    )
    second = service.evaluate_intent(
        intent_id=intent_id,
        reference_price=Decimal("10"),
        security_type="EQUITY",
        estimated_fee=Decimal("0"),
    )
    assert second.id == first.id


def test_daily_loss_reject_freezes_atomically(repository, engine):
    account = repository.create_account(name="a", initial_cash=Decimal("100000"))
    session_id = _running_session(repository, engine, account.id)
    repository.create_snapshot(
        paper_account_id=account.id,
        paper_session_id=session_id,
        session_date=date(2026, 1, 5),
        cash=Decimal("94000"),
        market_value=Decimal("0"),
        equity=Decimal("94000"),
        gross_exposure=Decimal("0"),
        daily_pnl=Decimal("-6000"),
        cumulative_pnl=Decimal("-6000"),
        drawdown=Decimal("0"),
    )
    intent_id = _intent(repository, session_id)
    service = _service(repository)
    policy_service = PaperRiskPolicyService(repository)
    _policy_with_version(policy_service, account.id)
    decision = service.evaluate_intent(
        intent_id=intent_id,
        reference_price=Decimal("10"),
        security_type="EQUITY",
        estimated_fee=Decimal("0"),
    )
    assert decision.decision == "REJECT"
    assert RiskReasonCode.DAILY_LOSS_LIMIT.value in decision.reason_codes_json
    frozen = repository.get_account(account.id)
    assert frozen.status == PaperAccountStatus.FROZEN.value


def test_freeze_idempotent(repository, engine):
    account = repository.create_account(name="a", initial_cash=Decimal("100000"))
    service = _service(repository)
    first = service.freeze_account(account_id=account.id, actor="USER")
    assert first.status == PaperAccountStatus.FROZEN.value
    second = service.freeze_account(account_id=account.id, actor="USER")
    assert second.status == PaperAccountStatus.FROZEN.value
    with Session(engine) as session:
        audits = session.scalars(
            select(PaperAuditEventModel).where(
                PaperAuditEventModel.paper_account_id == account.id,
                PaperAuditEventModel.event_type == "ACCOUNT_FROZEN",
            )
        ).all()
    assert len(audits) == 1


def test_user_unfreeze_allowed(repository):
    account = repository.create_account(name="a", initial_cash=Decimal("100000"))
    service = _service(repository)
    service.freeze_account(account_id=account.id, actor="RISK_ENGINE")
    unfrozen = service.unfreeze_account(account_id=account.id, actor="USER")
    assert unfrozen.status == PaperAccountStatus.ACTIVE.value


def test_risk_engine_unfreeze_rejected(repository):
    account = repository.create_account(name="a", initial_cash=Decimal("100000"))
    service = _service(repository)
    service.freeze_account(account_id=account.id, actor="RISK_ENGINE")
    with pytest.raises(PaperError, match="UNFREEZE_NOT_AUTHORIZED"):
        service.unfreeze_account(account_id=account.id, actor="RISK_ENGINE")


def test_policy_version_increment_and_fingerprint(repository):
    account = repository.create_account(name="a", initial_cash=Decimal("100000"))
    policy_service = PaperRiskPolicyService(repository)
    policy = policy_service.create_policy(paper_account_id=account.id, name="p")
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
    v1 = policy_service.create_version(risk_policy_id=policy.id, **fields)
    v2 = policy_service.create_version(risk_policy_id=policy.id, **fields)
    assert v1.version == 1
    assert v2.version == 2
    assert v1.policy_fingerprint == v2.policy_fingerprint
    changed = policy_service.create_version(
        risk_policy_id=policy.id, **{**fields, "max_drawdown": Decimal("0.3")}
    )
    assert changed.policy_fingerprint != v1.policy_fingerprint
    latest = policy_service.get_latest_version(risk_policy_id=policy.id)
    assert latest.version == 3


def test_single_active_policy_per_account(repository):
    account = repository.create_account(name="a", initial_cash=Decimal("100000"))
    policy_service = PaperRiskPolicyService(repository)
    policy_service.create_policy(paper_account_id=account.id, name="p")
    with pytest.raises(PaperError, match="RISK_POLICY_ALREADY_ACTIVE"):
        policy_service.create_policy(paper_account_id=account.id, name="p2")


def test_old_policy_version_immutable(repository, engine):
    account = repository.create_account(name="a", initial_cash=Decimal("100000"))
    policy_service = PaperRiskPolicyService(repository)
    _policy, version = _policy_with_version(policy_service, account.id)
    with Session(engine) as session, pytest.raises(sa.exc.IntegrityError):
        session.execute(
            text("UPDATE paper_risk_policy_versions SET max_drawdown = 0.5 WHERE id = :id"),
            {"id": version.id},
        )
