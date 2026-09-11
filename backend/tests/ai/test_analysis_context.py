from datetime import UTC, datetime
from importlib.util import find_spec

from quant_lab.ai.analysis_contracts import ResearchAnalysisRequest
from quant_lab.ai.repository import AIRepository

from .test_ai2_concrete_resolvers import domain_registry as domain_registry


def request(**changes):
    values = dict(
        analysis_type="STRATEGY_REVIEW",
        market="CN_A_SHARE",
        asset_type="EQUITY",
        market_data_cutoff=datetime(2026, 9, 11, tzinfo=UTC),
        knowledge_cutoff=datetime(2026, 9, 11, tzinfo=UTC),
        freshness_requirement="HISTORICAL_OK",
        analysis_mode="CURRENT_RESEARCH",
        research_question="复核策略表现",
        model_config_version_id="model",
        stage1_prompt_template_version_id="prompt1",
        stage2_prompt_template_version_id="prompt2",
        backtest_run_ids=["run1"],
        strategy_version_ids=["sv1"],
        requested_case_count=0,
    )
    values.update(changes)
    return ResearchAnalysisRequest.model_validate(values)


def test_context_builder_exists():
    assert find_spec("quant_lab.ai.analysis_context") is not None


def test_context_uses_real_evidence_resolvers_and_freezes_once(domain_registry):
    from quant_lab.ai.analysis_context import AnalysisContextBuilder

    engine = domain_registry.get("DATASET_VERSION")._loader.__self__.engine
    builder = AnalysisContextBuilder(AIRepository(engine), domain_registry)
    context = builder.build(request())
    assert context.pack.items
    assert any(
        item.field_path == "metrics.sharpe" and str(item.value) == "1.25"
        for item in context.pack.items
    )
    assert context.gate.decision == "PROCEED"
    assert context.pack.evidence_context.market_rules_version is None


def test_market_diagnosis_without_deterministic_metrics_waits(domain_registry):
    from quant_lab.ai.analysis_context import AnalysisContextBuilder

    engine = domain_registry.get("DATASET_VERSION")._loader.__self__.engine
    context = AnalysisContextBuilder(AIRepository(engine), domain_registry).build(
        request(
            analysis_type="MARKET_DIAGNOSIS",
            backtest_run_ids=[],
            strategy_version_ids=[],
            dataset_version_ids=["dv1"],
        )
    )
    assert context.gate.decision == "WAIT_FOR_EVIDENCE"


def test_future_evidence_fails_closed_before_provider(domain_registry):
    from quant_lab.ai.analysis_context import AnalysisContextBuilder

    engine = domain_registry.get("DATASET_VERSION")._loader.__self__.engine
    context = AnalysisContextBuilder(AIRepository(engine), domain_registry).build(
        request(knowledge_cutoff=datetime(2020, 1, 1, tzinfo=UTC))
    )
    assert context.gate.decision == "REJECT"
    assert "FUTURE_KNOWLEDGE" in context.gate.reason_codes


def test_paper_context_rejects_unrelated_target_before_freeze(domain_registry):
    import pytest

    from quant_lab.ai.analysis_context import AnalysisContextBuilder

    engine = domain_registry.get("DATASET_VERSION")._loader.__self__.engine
    with pytest.raises(ValueError, match="ANALYSIS_PAPER_SOURCE_RELATIONSHIP_INVALID"):
        AnalysisContextBuilder(AIRepository(engine), domain_registry).build(
            request(
                analysis_type="PAPER_REVIEW",
                paper_session_id="missing",
                paper_account_snapshot_ids=["pas1"],
                strategy_version_ids=[],
                backtest_run_ids=[],
            )
        )


def test_case_memory_backtracks_formal_evidence_and_never_promotes_prose(domain_registry):
    from sqlalchemy import text

    from quant_lab.ai.analysis_context import AnalysisContextBuilder
    from quant_lab.ai.retrieval import ResearchCaseDocumentService

    engine = domain_registry.get("DATASET_VERSION")._loader.__self__.engine
    repo = AIRepository(engine)
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE VIRTUAL TABLE ai_research_case_fts USING fts5("
                "document_id UNINDEXED,case_id UNINDEXED,title,summary,"
                "diagnosis,factors,labels_tags)"
            )
        )
    builder = AnalysisContextBuilder(repo, domain_registry)
    earlier = builder.build(request())
    ResearchCaseDocumentService(repo).create(
        case_id=earlier.pack.case_id,
        title="策略复核",
        summary="未经证实: 夏普比率99",
        diagnosis="仅为历史分析记忆",
        success_factors=[],
        failure_factors=[],
        regime_labels=[],
        safe_tags=[],
        universe=[],
        strategy_family=None,
        market_rules_version=None,
    )
    # The historical case becomes eligible only after its server-generated known_at.
    repo.rebuild_research_case_fts()
    current = builder.build(request(requested_case_count=5, knowledge_cutoff=datetime.now(UTC)))
    assert current.retrieval and len(current.case_memory) == 1
    memory = current.case_memory[0]
    assert memory["classification"] == "CASE_MEMORY_UNTRUSTED"
    assert memory["evidence_refs"]
    assert set(memory["evidence_refs"]) <= {i.ref for i in current.pack.items}
    assert not any(str(i.value) == "99" for i in current.pack.items)
