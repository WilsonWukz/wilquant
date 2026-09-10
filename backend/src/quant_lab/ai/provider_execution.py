from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Literal, Protocol
from uuid import uuid4

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from quant_lab.ai.configuration import contains_forbidden_secret_material
from quant_lab.ai.fingerprints import fingerprint_payload
from quant_lab.ai.persistence import (
    AIAnalysisAttemptModel,
    AIAnalysisRunModel,
    AIAnalysisTraceEventModel,
    AIEvidencePackModel,
    AIModelConfigVersionModel,
    AIPromptTemplateVersionModel,
    AIProviderCallBindingModel,
    AIUsageLedgerModel,
)
from quant_lab.ai.provider_artifacts import ProviderArtifactStore, sanitize_provider_content
from quant_lab.ai.provider_budget import ProviderBudgetPolicy
from quant_lab.ai.provider_configuration import ProviderModelParameters
from quant_lab.ai.repository import AIRepository
from quant_lab.ai_provider_protocol import (
    CallPolicy,
    EndpointProfile,
    ProviderCallRequest,
    ProviderCallResult,
    ProviderFailure,
    ProviderMessage,
    ProviderUsage,
    canonical_fingerprint,
)


class ProviderHostClient(Protocol):
    def complete(
        self, request: ProviderCallRequest, policy: CallPolicy | None = None
    ) -> ProviderCallResult: ...


@dataclass(frozen=True)
class AuthorizedProviderContext:
    """Core-only projection of an already authorized gate, never a public API DTO."""

    attempt_id: str
    evidence_pack_id: str
    evidence_pack_fingerprint: str
    gate_decision: Literal["PROCEED", "REJECT", "WAIT_FOR_EVIDENCE", "ABSTAIN"]
    gate_fingerprint: str


def _charged(session: Session, run_id: str) -> tuple[int, Decimal]:
    bindings = session.scalars(
        select(AIProviderCallBindingModel).where(AIProviderCallBindingModel.run_id == run_id)
    ).all()
    charged = Decimal(0)
    for binding in bindings:
        attempt = session.get(AIAnalysisAttemptModel, binding.attempt_id)
        usages = session.scalars(
            select(AIUsageLedgerModel).where(AIUsageLedgerModel.attempt_id == binding.attempt_id)
        ).all()
        known = [u.estimated_cost for u in usages if u.estimated_cost is not None]
        if attempt is not None and attempt.status == "COMPLETED" and len(known) == 1:
            charged += known[0]
        else:
            charged += max([binding.reserved_cost or Decimal(0), *known])
    return len(bindings), charged


class AIProviderExecutionService:
    def __init__(
        self, repository: AIRepository, client: ProviderHostClient, artifact_root: Path
    ) -> None:
        self.repository = repository
        self.client = client
        self.artifacts = ProviderArtifactStore(artifact_root)

    def charged_budget(self, run_id: str) -> Decimal:
        with Session(self.repository.engine) as session:
            return _charged(session, run_id)[1]

    def _reserve(
        self, context: AuthorizedProviderContext, messages: list[ProviderMessage]
    ) -> tuple[ProviderCallRequest, ProviderBudgetPolicy, CallPolicy]:
        with Session(self.repository.engine) as session:
            session.execute(text("BEGIN IMMEDIATE"))
            attempt = session.get(AIAnalysisAttemptModel, context.attempt_id)
            if attempt is None or attempt.status != "STARTED":
                raise ValueError("AI_ATTEMPT_NOT_DISPATCHABLE")
            if session.get(AIProviderCallBindingModel, attempt.id) is not None:
                raise ValueError("DUPLICATE_PROVIDER_REQUEST")
            run = session.get(AIAnalysisRunModel, attempt.run_id)
            if run is None or run.status not in {"RUNNING", "VALIDATING"}:
                raise ValueError("AI_RUN_NOT_DISPATCHABLE")
            model = session.get(AIModelConfigVersionModel, run.model_config_version_id)
            prompt = session.get(AIPromptTemplateVersionModel, run.prompt_template_version_id)
            pack = session.get(AIEvidencePackModel, context.evidence_pack_id)
            if (
                model is None
                or prompt is None
                or pack is None
                or model.fingerprint != run.model_config_fingerprint
                or prompt.fingerprint != run.prompt_template_fingerprint
                or pack.case_id != run.case_id
                or pack.fingerprint != context.evidence_pack_fingerprint
                or context.gate_decision != "PROCEED"
                or len(context.gate_fingerprint) != 64
            ):
                raise ValueError("AI_PROVIDER_AUTHORIZATION_INVALID")
            serialized_messages = [message.model_dump(mode="json") for message in messages]
            if fingerprint_payload(serialized_messages) != run.resolved_prompt_fingerprint:
                raise ValueError("AI_PROMPT_FINGERPRINT_MISMATCH")
            if contains_forbidden_secret_material(serialized_messages):
                raise ValueError("AI_PROMPT_SECRET_FORBIDDEN")
            parameters = json.loads(model.parameters_json)
            ProviderModelParameters.model_validate(parameters)
            profile = EndpointProfile.model_validate(parameters["provider_profile"])
            budget = ProviderBudgetPolicy.model_validate(parameters.get("budget", {}))
            policy = CallPolicy.model_validate(parameters.get("call_policy", {}))
            if (
                profile.model != model.model_identifier
                or profile.profile_id != model.endpoint_profile_id
                or profile.base_url != model.base_url_identity
                or profile.capabilities.model_dump(mode="json")
                != json.loads(model.capabilities_json)
            ):
                raise ValueError("AI_PROVIDER_CONFIG_MISMATCH")
            request = ProviderCallRequest(
                request_id=attempt.id,
                timestamp_utc=datetime.now(UTC),
                profile_id=profile.profile_id,
                endpoint_fingerprint=profile.fingerprint,
                model=profile.model,
                messages=messages,
                credential_ref=profile.credential_ref,
                max_output_tokens=parameters.get("max_output_tokens", 256),
                temperature=parameters.get("temperature"),
                reasoning_enabled=parameters.get("reasoning_enabled", False),
                reasoning_effort=parameters.get("reasoning_effort"),
                response_format=parameters.get("response_format", "TEXT"),
            )
            request_bytes = request.model_dump_json().encode("utf-8")
            # Reserve the configured entire input allowance, not a chars/4 estimate.
            minimum_bound = sum(len(m.content.encode("utf-8")) + 256 for m in messages) + 256
            if (
                len(request_bytes) > policy.max_request_bytes
                or minimum_bound > budget.max_input_tokens
                or request.max_output_tokens > policy.max_output_tokens
                or len(messages) > policy.max_messages
                or any(len(m.content) > policy.max_chars_per_message for m in messages)
            ):
                raise ValueError("AI_BUDGET_EXCEEDED")
            calls, charged = _charged(session, run.id)
            reserve, warning = budget.preflight(
                calls, charged, budget.max_input_tokens, request.max_output_tokens
            )
            binding = {
                "host_request_id": attempt.id,
                "protocol_version": request.protocol_version,
                "request_fingerprint": canonical_fingerprint(request.model_dump(mode="json")),
                "endpoint_fingerprint": profile.fingerprint,
                "model_config_fingerprint": model.fingerprint,
                "prompt_fingerprint": prompt.fingerprint,
                "resolved_prompt_fingerprint": run.resolved_prompt_fingerprint,
                "evidence_pack_id": pack.id,
                "evidence_pack_fingerprint": pack.fingerprint,
                "gate_fingerprint": context.gate_fingerprint,
                "gate_decision": "PROCEED",
                "budget": budget.model_dump(mode="json"),
                "call_policy": policy.model_dump(),
                "soft_warning": warning,
                "input_token_bound": budget.max_input_tokens,
                "max_output_tokens": request.max_output_tokens,
            }
            session.add(
                AIProviderCallBindingModel(
                    attempt_id=attempt.id,
                    run_id=run.id,
                    binding_json=json.dumps(binding, sort_keys=True),
                    reserved_cost=reserve,
                    currency=budget.currency,
                    created_at=datetime.now(UTC),
                )
            )
            session.commit()
            return request, budget, policy

    def execute(
        self, context: AuthorizedProviderContext, messages: list[ProviderMessage]
    ) -> AIAnalysisAttemptModel:
        request, budget, policy = self._reserve(context, messages)
        result: ProviderCallResult | None = None
        failure: ProviderFailure | None = None
        artifacts: list[dict[str, object]] = []
        try:
            result = self.client.complete(request, policy=policy)
            if (
                result.request_id != request.request_id
                or result.endpoint_fingerprint != request.endpoint_fingerprint
                or result.model_requested != request.model
            ):
                raise ProviderFailure("PROVIDER_INVALID_RESPONSE")
            if (
                len(result.model_dump_json().encode()) > policy.max_response_bytes
                or len((result.reasoning_content or "").encode()) > policy.max_reasoning_bytes
                or len((result.raw_response or "").encode()) > policy.max_raw_artifact_bytes
            ):
                raise ProviderFailure("PROVIDER_RESPONSE_TOO_LARGE")
            candidate = {"content": sanitize_provider_content(result.content)}
            artifacts.append(
                ProviderArtifactStore(
                    self.artifacts.root, max_bytes=policy.max_response_bytes
                ).write("candidate", candidate)
            )
            if result.raw_response is not None:
                # Parse structured raw before stripping nested reasoning; never persist opaque raw.
                try:
                    raw = json.loads(result.raw_response)
                except ValueError:
                    raise ProviderFailure("PROVIDER_INVALID_RESPONSE") from None
                artifacts.append(
                    ProviderArtifactStore(
                        self.artifacts.root, max_bytes=policy.max_raw_artifact_bytes
                    ).write("raw", raw)
                )
        except ProviderFailure as error:
            failure = error
        except (OSError, ValueError, TypeError):
            failure = ProviderFailure("PROVIDER_RESULT_UNKNOWN", outcome_unknown=True)
        return self._finalize(request, budget, result, failure, artifacts)

    def _finalize(
        self,
        request: ProviderCallRequest,
        budget: ProviderBudgetPolicy,
        result: ProviderCallResult | None,
        failure: ProviderFailure | None,
        artifacts: list[dict[str, object]],
    ) -> AIAnalysisAttemptModel:
        with Session(self.repository.engine, expire_on_commit=False) as session:
            session.execute(text("BEGIN IMMEDIATE"))
            attempt = session.get(AIAnalysisAttemptModel, request.request_id)
            if attempt is None or attempt.status != "STARTED":
                raise ValueError("AI_ATTEMPT_TERMINAL")
            unknown = failure is not None and failure.outcome_unknown
            attempt.status = "ABANDONED" if unknown else "FAILED" if failure else "COMPLETED"
            attempt.failure_code = (
                "PROVIDER_RESULT_UNKNOWN" if unknown else failure.code if failure else None
            )
            attempt.completed_at = datetime.now(UTC)
            usage = result.usage if result is not None and failure is None else ProviderUsage()
            cost = budget.settlement(
                usage.prompt_tokens, usage.cached_prompt_tokens, usage.completion_tokens
            )
            if result is not None and failure is None:
                attempt.provider_request_id = result.provider_response_id
                attempt.output_fingerprint = fingerprint_payload(
                    {"content": sanitize_provider_content(result.content)}
                )
                attempt.latency_ms = int(result.latency_ms)
                attempt.finish_reason = result.finish_reason
            session.add(
                AIUsageLedgerModel(
                    id=str(uuid4()),
                    run_id=attempt.run_id,
                    attempt_id=attempt.id,
                    prompt_tokens=usage.prompt_tokens,
                    cached_prompt_tokens=usage.cached_prompt_tokens,
                    completion_tokens=usage.completion_tokens,
                    total_tokens=usage.total_tokens,
                    reported_cost=None,
                    estimated_cost=cost,
                    currency=budget.currency,
                    is_estimate=True,
                    occurred_at=datetime.now(UTC),
                )
            )
            sequence = (
                session.scalar(
                    select(func.max(AIAnalysisTraceEventModel.sequence)).where(
                        AIAnalysisTraceEventModel.run_id == attempt.run_id
                    )
                )
                or 0
            ) + 1
            payload = {
                "attempt_id": attempt.id,
                "status": attempt.status,
                "failure_code": attempt.failure_code,
                "artifacts": artifacts,
                "usage": usage.model_dump(),
                "candidate_only": True,
                "cost_unknown": cost is None,
            }
            session.add(
                AIAnalysisTraceEventModel(
                    id=str(uuid4()),
                    run_id=attempt.run_id,
                    sequence=sequence,
                    event_type="PROVIDER_ATTEMPT_COMPLETED"
                    if failure is None
                    else "PROVIDER_ATTEMPT_FAILED",
                    payload_json=json.dumps(payload),
                    payload_fingerprint=fingerprint_payload(payload),
                    occurred_at=datetime.now(UTC),
                )
            )
            session.commit()
            session.expunge(attempt)
            return attempt
