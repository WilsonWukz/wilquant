from __future__ import annotations

from quant_lab.ai.domain import (
    AIAnalysisAttemptStatus,
    AIAnalysisRunStatus,
    AIAnalysisStage,
    AITraceEventType,
)


def test_persisted_enum_values_are_stable() -> None:
    assert [member.value for member in AIAnalysisStage] == [
        "DIAGNOSIS",
        "RECOMMENDATION",
        "CONVERSATION",
    ]
    assert [member.value for member in AIAnalysisRunStatus] == [
        "CREATED",
        "RUNNING",
        "VALIDATING",
        "COMPLETED",
        "FAILED",
        "CANCELLED",
        "REJECTED",
    ]
    assert [member.value for member in AIAnalysisAttemptStatus] == [
        "STARTED",
        "COMPLETED",
        "FAILED",
        "ABANDONED",
    ]
    assert [member.value for member in AITraceEventType] == [
        "CASE_FROZEN",
        "PROMPT_RESOLVED",
        "PROVIDER_ATTEMPT_STARTED",
        "PROVIDER_ATTEMPT_FAILED",
        "PROVIDER_ATTEMPT_COMPLETED",
        "RUN_FAILED",
        "RUN_CANCELLED",
        "RUN_COMPLETED",
    ]


def test_ai_domain_has_no_execution_authority_vocabulary() -> None:
    names = {
        member.name
        for enum_type in (
            AIAnalysisStage,
            AIAnalysisRunStatus,
            AIAnalysisAttemptStatus,
            AITraceEventType,
        )
        for member in enum_type
    }
    forbidden = {"ORDER", "FILL", "LIVE", "CAPITAL", "RISK_DECISION"}
    assert names.isdisjoint(forbidden)
