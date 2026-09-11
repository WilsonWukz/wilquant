"""Read-only PAPER provenance checks, separate from historical evidence fingerprints."""

from __future__ import annotations

import json

from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from quant_lab.ai.resolvers import PaperRelationshipError
from quant_lab.paper.models import (
    PaperAccountModel,
    PaperAccountSnapshotModel,
    PaperOrderIntentModel,
    PaperRiskDecisionModel,
    PaperRiskPolicyModel,
    PaperRiskPolicyVersionModel,
    PaperSessionModel,
)


def _context_identity(payload: str, field: str) -> str:
    try:
        context = json.loads(payload)
    except (TypeError, ValueError) as error:
        raise PaperRelationshipError() from error
    if not isinstance(context, dict) or not isinstance(context.get(field), str):
        raise PaperRelationshipError()
    return context[field]


def validate_paper_relationships(
    engine: Engine,
    paper_session_id: str,
    paper_account_snapshot_ids: tuple[str, ...],
    risk_decision_ids: tuple[str, ...],
) -> None:
    """Require every selection to belong to the exact target session and account.

    Relationships come from persisted domain identities, never user-supplied
    evidence fields. No PAPER service is invoked and no domain state is mutated.
    """
    with Session(engine) as session:
        paper = session.get(PaperSessionModel, paper_session_id)
        if paper is None or session.get(PaperAccountModel, paper.paper_account_id) is None:
            raise PaperRelationshipError()
        for snapshot_id in paper_account_snapshot_ids:
            snapshot = session.get(PaperAccountSnapshotModel, snapshot_id)
            if (
                snapshot is None
                or snapshot.paper_session_id != paper.id
                or snapshot.paper_account_id != paper.paper_account_id
            ):
                raise PaperRelationshipError()
        for decision_id in risk_decision_ids:
            decision = session.get(PaperRiskDecisionModel, decision_id)
            if decision is None:
                raise PaperRelationshipError()
            intent = session.get(PaperOrderIntentModel, decision.order_intent_id)
            version = session.get(PaperRiskPolicyVersionModel, decision.risk_policy_version_id)
            policy = session.get(PaperRiskPolicyModel, decision.risk_policy_id)
            if (
                intent is None
                or intent.paper_session_id != paper.id
                or version is None
                or policy is None
                or version.risk_policy_id != policy.id
                or decision.risk_policy_version != version.version
                or policy.paper_account_id != paper.paper_account_id
                or _context_identity(decision.account_snapshot_json, "account_id")
                != paper.paper_account_id
                or _context_identity(decision.market_context_json, "instrument_id")
                != intent.instrument_id
            ):
                raise PaperRelationshipError()
