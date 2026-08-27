from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from quant_lab.ai.configuration import AIProvenanceError
from quant_lab.ai.domain import (
    AIAnalysisAttemptStatus,
    AIAnalysisRunStatus,
    AITraceEventType,
)
from quant_lab.ai.fingerprints import fingerprint_payload
from quant_lab.ai.persistence import (
    AIAnalysisAttemptModel,
    AIAnalysisRunModel,
    AIAnalysisTraceEventModel,
    AIUsageLedgerModel,
)
from quant_lab.ai.repository import AIRepository
from quant_lab.market_data.fingerprints import canonical_json_bytes

TERMINAL_RUN_STATUSES = frozenset(
    {
        AIAnalysisRunStatus.COMPLETED.value,
        AIAnalysisRunStatus.FAILED.value,
        AIAnalysisRunStatus.CANCELLED.value,
        AIAnalysisRunStatus.REJECTED.value,
    }
)


@dataclass(frozen=True, slots=True)
class AIUsageInput:
    prompt_tokens: int
    cached_prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    reported_cost: Decimal | None
    estimated_cost: Decimal | None
    currency: str
    is_estimate: bool


class AIProvenanceService:
    def __init__(self, repository: AIRepository) -> None:
        self.repository = repository

    def create_run(
        self,
        *,
        case_id: str,
        stage: str,
        prompt_template_version_id: str,
        model_config_version_id: str,
        resolved_prompt_fingerprint: str,
        validator_policy_version: str,
        validator_policy_fingerprint: str,
        parent_run_id: str | None = None,
    ) -> AIAnalysisRunModel:
        case = self.repository.get_research_case(case_id)
        if case is None:
            raise AIProvenanceError("AI_CASE_NOT_FOUND", "研究案例不存在")
        prompt = self.repository.get_prompt_template(prompt_template_version_id)
        if prompt is None:
            raise AIProvenanceError("AI_PROMPT_VERSION_NOT_FOUND", "Prompt 版本不存在")
        model = self.repository.get_model_config(model_config_version_id)
        if model is None:
            raise AIProvenanceError("AI_MODEL_CONFIG_NOT_FOUND", "模型配置版本不存在")
        if parent_run_id is not None and self.repository.get_run(parent_run_id) is None:
            raise AIProvenanceError("AI_PARENT_RUN_NOT_FOUND", "父分析运行不存在")
        return self.repository.add_run(
            AIAnalysisRunModel(
                id=str(uuid4()),
                case_id=case_id,
                stage=stage,
                status=AIAnalysisRunStatus.CREATED.value,
                parent_run_id=parent_run_id,
                prompt_template_version_id=prompt_template_version_id,
                model_config_version_id=model_config_version_id,
                case_fingerprint=case.fingerprint,
                prompt_template_fingerprint=prompt.fingerprint,
                resolved_prompt_fingerprint=resolved_prompt_fingerprint,
                model_config_fingerprint=model.fingerprint,
                validator_policy_version=validator_policy_version,
                validator_policy_fingerprint=validator_policy_fingerprint,
                created_at=datetime.now(UTC),
            )
        )

    def get_run(self, run_id: str) -> AIAnalysisRunModel:
        run = self.repository.get_run(run_id)
        if run is None:
            raise AIProvenanceError("AI_RUN_NOT_FOUND", "AI 分析运行不存在")
        return run

    def start_run(self, run_id: str, input_envelope_fingerprint: str) -> AIAnalysisRunModel:
        run = self.get_run(run_id)
        self._require_status(run, {AIAnalysisRunStatus.CREATED.value})
        return self._update_run(
            run_id,
            status=AIAnalysisRunStatus.RUNNING.value,
            input_envelope_fingerprint=input_envelope_fingerprint,
            started_at=datetime.now(UTC),
        )

    def start_attempt(self, run_id: str, input_fingerprint: str) -> AIAnalysisAttemptModel:
        run = self.get_run(run_id)
        self._require_status(
            run,
            {AIAnalysisRunStatus.RUNNING.value, AIAnalysisRunStatus.VALIDATING.value},
        )
        return self.repository.add_attempt(
            AIAnalysisAttemptModel(
                id=str(uuid4()),
                run_id=run_id,
                attempt_number=self.repository.next_attempt_number(run_id),
                status=AIAnalysisAttemptStatus.STARTED.value,
                input_fingerprint=input_fingerprint,
                started_at=datetime.now(UTC),
            )
        )

    def get_attempt(self, attempt_id: str) -> AIAnalysisAttemptModel:
        attempt = self.repository.get_attempt(attempt_id)
        if attempt is None:
            raise AIProvenanceError("AI_ATTEMPT_NOT_FOUND", "AI 分析尝试不存在")
        return attempt

    def complete_attempt(
        self,
        attempt_id: str,
        provider_request_id: str,
        output_fingerprint: str,
        latency_ms: int,
        finish_reason: str,
    ) -> AIAnalysisAttemptModel:
        attempt = self.get_attempt(attempt_id)
        self._require_attempt_started(attempt)
        if latency_ms < 0:
            raise AIProvenanceError("AI_ATTEMPT_LATENCY_INVALID", "模型尝试耗时不能为负数")
        return self._update_attempt(
            attempt_id,
            status=AIAnalysisAttemptStatus.COMPLETED.value,
            provider_request_id=provider_request_id,
            output_fingerprint=output_fingerprint,
            latency_ms=latency_ms,
            finish_reason=finish_reason,
            completed_at=datetime.now(UTC),
        )

    def fail_attempt(self, attempt_id: str, failure_code: str) -> AIAnalysisAttemptModel:
        attempt = self.get_attempt(attempt_id)
        self._require_attempt_started(attempt)
        return self._update_attempt(
            attempt_id,
            status=AIAnalysisAttemptStatus.FAILED.value,
            failure_code=failure_code,
            completed_at=datetime.now(UTC),
        )

    def append_trace(
        self, run_id: str, event_type: AITraceEventType | str, payload: object
    ) -> AIAnalysisTraceEventModel:
        self.get_run(run_id)
        payload_fingerprint = fingerprint_payload(payload)
        return self.repository.add_trace(
            AIAnalysisTraceEventModel(
                id=str(uuid4()),
                run_id=run_id,
                sequence=self.repository.next_trace_sequence(run_id),
                event_type=str(event_type),
                payload_json=canonical_json_bytes(payload).decode("utf-8"),
                payload_fingerprint=payload_fingerprint,
                occurred_at=datetime.now(UTC),
            )
        )

    def list_trace(self, run_id: str) -> tuple[AIAnalysisTraceEventModel, ...]:
        self.get_run(run_id)
        return self.repository.list_trace(run_id)

    def append_usage(self, attempt_id: str, value: AIUsageInput) -> AIUsageLedgerModel:
        attempt = self.get_attempt(attempt_id)
        if min(
            value.prompt_tokens,
            value.cached_prompt_tokens,
            value.completion_tokens,
            value.total_tokens,
        ) < 0 or value.cached_prompt_tokens > value.prompt_tokens:
            raise AIProvenanceError("AI_USAGE_TOKEN_INVALID", "AI token 用量无效")
        if value.total_tokens != value.prompt_tokens + value.completion_tokens:
            raise AIProvenanceError("AI_USAGE_TOTAL_MISMATCH", "AI token 总量与分项不一致")
        if any(
            cost is not None and cost < 0
            for cost in (value.reported_cost, value.estimated_cost)
        ):
            raise AIProvenanceError("AI_USAGE_COST_INVALID", "AI 成本不能为负数")
        return self.repository.add_usage(
            AIUsageLedgerModel(
                id=str(uuid4()),
                run_id=attempt.run_id,
                attempt_id=attempt_id,
                prompt_tokens=value.prompt_tokens,
                cached_prompt_tokens=value.cached_prompt_tokens,
                completion_tokens=value.completion_tokens,
                total_tokens=value.total_tokens,
                reported_cost=value.reported_cost,
                estimated_cost=value.estimated_cost,
                currency=value.currency,
                is_estimate=value.is_estimate,
                occurred_at=datetime.now(UTC),
            )
        )

    def list_usage(self, run_id: str) -> tuple[AIUsageLedgerModel, ...]:
        self.get_run(run_id)
        return self.repository.list_usage(run_id)

    def complete_run(
        self,
        run_id: str,
        raw_response_artifact_sha256: str,
        normalized_output_fingerprint: str,
    ) -> AIAnalysisRunModel:
        run = self.get_run(run_id)
        self._require_status(
            run,
            {AIAnalysisRunStatus.RUNNING.value, AIAnalysisRunStatus.VALIDATING.value},
        )
        return self._update_run(
            run_id,
            status=AIAnalysisRunStatus.COMPLETED.value,
            raw_response_artifact_sha256=raw_response_artifact_sha256,
            normalized_output_fingerprint=normalized_output_fingerprint,
            completed_at=datetime.now(UTC),
        )

    def fail_run(
        self, run_id: str, failure_code: str, safe_failure_message: str
    ) -> AIAnalysisRunModel:
        run = self.get_run(run_id)
        self._require_status(
            run,
            {AIAnalysisRunStatus.RUNNING.value, AIAnalysisRunStatus.VALIDATING.value},
        )
        return self._update_run(
            run_id,
            status=AIAnalysisRunStatus.FAILED.value,
            failure_code=failure_code,
            safe_failure_message=safe_failure_message,
            completed_at=datetime.now(UTC),
        )

    def cancel_run(self, run_id: str) -> AIAnalysisRunModel:
        run = self.get_run(run_id)
        if run.status in TERMINAL_RUN_STATUSES:
            raise AIProvenanceError("AI_RUN_TERMINAL", "终态 AI 分析运行不可修改")
        return self._update_run(
            run_id,
            status=AIAnalysisRunStatus.CANCELLED.value,
            completed_at=datetime.now(UTC),
        )

    def recover_incomplete_runs(self, now_utc: datetime) -> tuple[str, ...]:
        recovered: list[str] = []
        for run in self.repository.list_incomplete_runs():
            for attempt in self.repository.list_started_attempts(run.id):
                self._update_attempt(
                    attempt.id,
                    status=AIAnalysisAttemptStatus.ABANDONED.value,
                    failure_code="AI_ATTEMPT_RECOVERED_INCOMPLETE",
                    completed_at=now_utc,
                )
            self._update_run(
                run.id,
                status=AIAnalysisRunStatus.FAILED.value,
                failure_code="AI_RUN_RECOVERED_INCOMPLETE",
                safe_failure_message="应用重启后发现未完成的 AI 分析运行",
                completed_at=now_utc,
            )
            self.append_trace(
                run.id,
                AITraceEventType.RUN_FAILED,
                {"failure_code": "AI_RUN_RECOVERED_INCOMPLETE"},
            )
            recovered.append(run.id)
        return tuple(recovered)

    def _require_status(self, run: AIAnalysisRunModel, allowed: set[str]) -> None:
        if run.status in TERMINAL_RUN_STATUSES:
            raise AIProvenanceError("AI_RUN_TERMINAL", "终态 AI 分析运行不可修改")
        if run.status not in allowed:
            raise AIProvenanceError("AI_RUN_TRANSITION_INVALID", "AI 分析运行状态转换无效")

    def _require_attempt_started(self, attempt: AIAnalysisAttemptModel) -> None:
        if attempt.status != AIAnalysisAttemptStatus.STARTED.value:
            raise AIProvenanceError("AI_ATTEMPT_TERMINAL", "终态 AI 分析尝试不可修改")

    def _update_run(self, run_id: str, **values: object) -> AIAnalysisRunModel:
        updated = self.repository.update_run(run_id, values)
        if updated is None:
            raise AIProvenanceError("AI_RUN_NOT_FOUND", "AI 分析运行不存在")
        return updated

    def _update_attempt(self, attempt_id: str, **values: object) -> AIAnalysisAttemptModel:
        updated = self.repository.update_attempt(attempt_id, values)
        if updated is None:
            raise AIProvenanceError("AI_ATTEMPT_NOT_FOUND", "AI 分析尝试不存在")
        return updated
