import pytest
from sqlalchemy import event
from sqlalchemy.orm import Session

from quant_lab.ai.resolvers import EvidenceResolverError, EvidenceResolverRegistry
from quant_lab.paper.models import (
    PaperAccountModel,
    PaperAccountSnapshotModel,
    PaperOrderIntentModel,
    PaperRiskDecisionModel,
    PaperRiskPolicyModel,
    PaperRiskPolicyVersionModel,
    PaperSessionModel,
)

from .test_ai2_concrete_resolvers import domain_registry as domain_registry


@pytest.fixture
def paper_registry(domain_registry):
    engine = domain_registry.get("PAPER_SESSION")._loader.__self__.engine
    with Session(engine) as session:
        for model, identity, new_id, changes in (
            (PaperAccountModel, "pa1", "pa2", {}),
            (PaperSessionModel, "ps1", "ps2", {"paper_account_id": "pa2"}),
            (PaperSessionModel, "ps1", "ps3", {}),
            (PaperRiskPolicyModel, "rp1", "rp2", {"paper_account_id": "pa2"}),
        ):
            original = session.get(model, identity)
            values = {
                column.name: getattr(original, column.name) for column in model.__table__.columns
            }
            session.add(model(**(values | {"id": new_id} | changes)))
        decision = session.get(PaperRiskDecisionModel, "rd1")
        decision.account_snapshot_json = '{"account_id":"pa1","cash":"90000"}'
        decision.market_context_json = (
            '{"instrument_id":"SSE:600000","evaluated_metrics":{"estimated_notional":"1000"}}'
        )
        session.commit()
    return domain_registry


def validate(registry, **changes):
    # Assert the supported API exists before invoking it: RED identifies missing capability.
    assert hasattr(registry, "validate_paper_relationships")
    return registry.validate_paper_relationships(
        **(
            dict(
                paper_session_id="ps1",
                paper_account_snapshot_ids=("pas1",),
                risk_decision_ids=("rd1",),
            )
            | changes
        )
    )


def test_paper_relationship_validator_is_read_only_and_preserves_evidence(paper_registry):
    engine = paper_registry.get("PAPER_SESSION")._loader.__self__.engine
    before = paper_registry.resolve_source("RISK_DECISION", "rd1")
    statements = []

    def record(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement.lstrip().upper())

    event.listen(engine, "before_cursor_execute", record)
    try:
        assert validate(paper_registry) is None
    finally:
        event.remove(engine, "before_cursor_execute", record)
    assert statements and all(statement.startswith("SELECT") for statement in statements)
    assert paper_registry.resolve_source("RISK_DECISION", "rd1") == before


@pytest.mark.parametrize("target", ["ps2", "ps3"])
def test_rejects_snapshot_from_another_session_even_if_same_account(paper_registry, target):
    with pytest.raises(EvidenceResolverError, match="ANALYSIS_PAPER_SOURCE_RELATIONSHIP_INVALID"):
        validate(paper_registry, paper_session_id=target, risk_decision_ids=())


@pytest.mark.parametrize("target", ["ps2", "ps3"])
def test_rejects_decision_from_another_session_even_if_same_account(paper_registry, target):
    with pytest.raises(EvidenceResolverError, match="ANALYSIS_PAPER_SOURCE_RELATIONSHIP_INVALID"):
        validate(paper_registry, paper_session_id=target, paper_account_snapshot_ids=())


@pytest.mark.parametrize(
    ("model", "identity", "field", "value"),
    [
        (PaperAccountSnapshotModel, "pas1", "paper_account_id", "pa2"),
        (PaperOrderIntentModel, "intent1", "paper_session_id", "missing"),
        (PaperRiskPolicyModel, "rp1", "paper_account_id", "pa2"),
        (PaperRiskPolicyVersionModel, "rpv1", "risk_policy_id", "rp2"),
        (PaperRiskDecisionModel, "rd1", "risk_policy_id", "rp2"),
        (PaperRiskDecisionModel, "rd1", "risk_policy_version", 9),
        (PaperRiskDecisionModel, "rd1", "risk_policy_version_id", "missing"),
        (PaperRiskDecisionModel, "rd1", "account_snapshot_json", '{"account_id":"pa2"}'),
        (PaperRiskDecisionModel, "rd1", "account_snapshot_json", "{}"),
        (PaperRiskDecisionModel, "rd1", "account_snapshot_json", "not-json"),
        (PaperRiskDecisionModel, "rd1", "account_snapshot_json", "[]"),
        (PaperRiskDecisionModel, "rd1", "market_context_json", '{"instrument_id":"SSE:600001"}'),
        (PaperRiskDecisionModel, "rd1", "market_context_json", "{}"),
    ],
)
def test_rejects_inconsistent_persisted_relationships(
    paper_registry, model, identity, field, value
):
    engine = paper_registry.get("PAPER_SESSION")._loader.__self__.engine
    with Session(engine) as session:
        setattr(session.get(model, identity), field, value)
        session.commit()
    with pytest.raises(EvidenceResolverError, match="ANALYSIS_PAPER_SOURCE_RELATIONSHIP_INVALID"):
        validate(paper_registry)


@pytest.mark.parametrize(
    "changes",
    [
        {"paper_session_id": "missing"},
        {"paper_account_snapshot_ids": ("pas1", "missing")},
        {"risk_decision_ids": ("rd1", "missing")},
    ],
)
def test_missing_selection_fails_closed(paper_registry, changes):
    with pytest.raises(EvidenceResolverError, match="ANALYSIS_PAPER_SOURCE_RELATIONSHIP_INVALID"):
        validate(paper_registry, **changes)


def test_registry_without_trusted_relationship_loader_fails_closed():
    with pytest.raises(EvidenceResolverError, match="ANALYSIS_PAPER_SOURCE_RELATIONSHIP_INVALID"):
        validate(EvidenceResolverRegistry())
