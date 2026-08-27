from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine

from quant_lab.ai import persistence  # noqa: F401
from quant_lab.ai.cases import ResearchCaseInput, ResearchCaseService
from quant_lab.ai.configuration import (
    AIModelConfigVersionService,
    AIProvenanceError,
    PromptTemplateVersionService,
)
from quant_lab.ai.domain import AIAnalysisRunStatus, AITraceEventType
from quant_lab.ai.provenance import AIProvenanceService, AIUsageInput
from quant_lab.ai.repository import AIRepository
from quant_lab.db.sqlite import Base


@pytest.fixture
def provenance() -> AIProvenanceService:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    repository = AIRepository(engine)
    prompt = PromptTemplateVersionService(repository).publish(
        template_name="diagnosis",
        stage="DIAGNOSIS",
        schema_version="diagnosis@1",
        content="test",
        variable_contract={"required": ["case"]},
        validator_policy_version="validators@1",
        actor="USER",
    )
    model = AIModelConfigVersionService(repository).publish(
        provider_kind="FAKE",
        provider_id="fake",
        base_url_identity="local-fake",
        model_identifier="fake-v1",
        endpoint_profile_id="fake",
        capabilities={},
        parameters={"tool_configuration": "NONE"},
        actor="USER",
    )
    case = ResearchCaseService(repository).freeze(
        ResearchCaseInput(
            purpose="TEST",
            market="CN_A_SHARE",
            exchange="SSE",
            symbol="600000",
            instrument_id="600000.XSHG",
            asset_type="EQUITY",
            currency="CNY",
            timeframe="1D",
            as_of_utc=datetime(2026, 8, 27, 8, tzinfo=UTC),
            market_local_trade_date=date(2026, 8, 27),
            bindings={
                "market_data_fingerprint": "a" * 64,
                "calendar_fingerprint": "b" * 64,
                "market_rules_fingerprint": "c" * 64,
            },
        ),
        actor="USER",
    )
    service = AIProvenanceService(repository)
    service.test_case_id = case.id  # type: ignore[attr-defined]
    service.test_prompt_id = prompt.id  # type: ignore[attr-defined]
    service.test_model_id = model.id  # type: ignore[attr-defined]
    return service


def _create_run(service: AIProvenanceService):
    return service.create_run(
        case_id=service.test_case_id,  # type: ignore[attr-defined]
        stage="DIAGNOSIS",
        prompt_template_version_id=service.test_prompt_id,  # type: ignore[attr-defined]
        model_config_version_id=service.test_model_id,  # type: ignore[attr-defined]
        resolved_prompt_fingerprint="d" * 64,
        validator_policy_version="validators@1",
        validator_policy_fingerprint="e" * 64,
    )


def test_run_lifecycle_and_terminal_state_are_enforced(provenance) -> None:
    run = _create_run(provenance)
    assert run.status == AIAnalysisRunStatus.CREATED

    running = provenance.start_run(run.id, "f" * 64)
    assert running.status == AIAnalysisRunStatus.RUNNING
    completed = provenance.complete_run(run.id, "1" * 64, "2" * 64)
    assert completed.status == AIAnalysisRunStatus.COMPLETED

    with pytest.raises(AIProvenanceError, match="AI_RUN_TERMINAL"):
        provenance.cancel_run(run.id)


def test_attempt_trace_and_usage_are_monotonic_and_append_only(provenance) -> None:
    run = _create_run(provenance)
    provenance.start_run(run.id, "f" * 64)
    first = provenance.start_attempt(run.id, "1" * 64)
    second = provenance.start_attempt(run.id, "2" * 64)
    assert (first.attempt_number, second.attempt_number) == (1, 2)

    completed = provenance.complete_attempt(
        first.id,
        provider_request_id="fake-request",
        output_fingerprint="3" * 64,
        latency_ms=10,
        finish_reason="stop",
    )
    assert completed.status == "COMPLETED"
    usage = provenance.append_usage(
        first.id,
        AIUsageInput(
            prompt_tokens=10,
            cached_prompt_tokens=2,
            completion_tokens=5,
            total_tokens=15,
            reported_cost=Decimal("0.001"),
            estimated_cost=None,
            currency="USD",
            is_estimate=False,
        ),
    )
    assert usage.run_id == run.id
    assert usage.total_tokens == 15

    trace_one = provenance.append_trace(run.id, AITraceEventType.PROMPT_RESOLVED, {"ok": True})
    trace_two = provenance.append_trace(
        run.id, AITraceEventType.PROVIDER_ATTEMPT_COMPLETED, {"attempt": 1}
    )
    assert (trace_one.sequence, trace_two.sequence) == (1, 2)


def test_usage_rejects_negative_or_inconsistent_tokens(provenance) -> None:
    run = _create_run(provenance)
    provenance.start_run(run.id, "f" * 64)
    attempt = provenance.start_attempt(run.id, "1" * 64)
    provenance.fail_attempt(attempt.id, "FAKE_FAILURE")

    with pytest.raises(AIProvenanceError, match="AI_USAGE_TOKEN_INVALID"):
        provenance.append_usage(
            attempt.id,
            AIUsageInput(-1, 0, 1, 0, None, None, "USD", True),
        )
    with pytest.raises(AIProvenanceError, match="AI_USAGE_TOTAL_MISMATCH"):
        provenance.append_usage(
            attempt.id,
            AIUsageInput(10, 0, 5, 99, None, None, "USD", True),
        )


def test_usage_rejects_negative_cost(provenance) -> None:
    run = _create_run(provenance)
    provenance.start_run(run.id, "f" * 64)
    attempt = provenance.start_attempt(run.id, "1" * 64)
    provenance.fail_attempt(attempt.id, "FAKE_FAILURE")

    with pytest.raises(AIProvenanceError, match="AI_USAGE_COST_INVALID"):
        provenance.append_usage(
            attempt.id,
            AIUsageInput(10, 0, 5, 15, Decimal("-0.01"), None, "USD", False),
        )


def test_recovery_abandons_started_attempt_and_fails_run(provenance) -> None:
    run = _create_run(provenance)
    provenance.start_run(run.id, "f" * 64)
    attempt = provenance.start_attempt(run.id, "1" * 64)

    recovered = provenance.recover_incomplete_runs(datetime(2026, 8, 27, 9, tzinfo=UTC))

    assert recovered == (run.id,)
    assert provenance.get_attempt(attempt.id).status == "ABANDONED"
    failed = provenance.get_run(run.id)
    assert failed.status == "FAILED"
    assert failed.failure_code == "AI_RUN_RECOVERED_INCOMPLETE"
    assert provenance.list_trace(run.id)[-1].event_type == AITraceEventType.RUN_FAILED
