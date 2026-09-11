from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, cast
from uuid import uuid4

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from quant_lab.ai.analysis_artifacts import AnalysisArtifactStore
from quant_lab.ai.analysis_contracts import (
    ResearchAnalysisRequest,
    ResearchDiagnosis,
    ResearchRecommendation,
    StageContract,
)
from quant_lab.ai.analysis_persistence import AIAnalysisStageBindingModel as StageBinding
from quant_lab.ai.analysis_prompts import (
    ValidationFeedback,
    ValidationFeedbackBuilder,
    render_analysis_prompt,
)
from quant_lab.ai.analysis_repository import AnalysisRepository, _trace
from quant_lab.ai.contracts import (
    AcceptedAssertion,
    AssertionObservation,
    EvidencePack,
    FindingSeverity,
    GateResult,
    ValidationLayer,
    ValidationResult,
)
from quant_lab.ai.fingerprints import fingerprint_payload
from quant_lab.ai.gates import ResearchGate
from quant_lab.ai.packs import _pack_from_model
from quant_lab.ai.persistence import AIAnalysisAttemptModel as Attempt
from quant_lab.ai.persistence import AIAnalysisRunModel as Run
from quant_lab.ai.persistence import AIValidationResultModel
from quant_lab.ai.provider_configuration import ProviderModelParameters
from quant_lab.ai.provider_execution import (
    AIProviderExecutionService,
    AuthorizedProviderContext,
    ProviderHostClient,
    _charged,
)
from quant_lab.ai.repository import AIRepository
from quant_lab.ai.validation import ValidationResultRecorder, ValidationService, _finding
from quant_lab.ai_provider_protocol import ProviderFailure


def _result(row: AIValidationResultModel) -> ValidationResult:
    return ValidationResult.model_validate(
        {
            "disposition": row.disposition,
            "findings": json.loads(row.findings_json),
            "accepted_assertions": json.loads(row.accepted_assertions_json),
            "observations": json.loads(row.observations_json),
            "candidate_fingerprint": row.candidate_fingerprint,
            "policy_version": row.policy_version,
        }
    )


class TwoStageResearchExecution:
    def __init__(
        self,
        repository: AIRepository,
        client: ProviderHostClient,
        store: AnalysisArtifactStore,
        analyses: AnalysisRepository,
    ) -> None:
        self.repository, self.client, self.store, self.analyses = (
            repository,
            client,
            store,
            analyses,
        )
        self.provider = AIProviderExecutionService(repository, client, store.root)
        self.host_checked = False

    def _stop(self, run_id: str, epoch: str, outcome: str, lifecycle: str = "FAILED") -> None:
        row = self.analyses.get(run_id)
        if row.active_epoch_id != epoch:
            return
        self.analyses.checkpoint(
            run_id, epoch, progress="TERMINAL", outcome=outcome, lifecycle=lifecycle
        )

    def run(self, run_id: str, epoch: str) -> None:
        try:
            row = self.analyses.get(run_id)
            request = ResearchAnalysisRequest.model_validate(
                self.store.read(json.loads(row.request_artifact_json))
            )
            if fingerprint_payload(request.model_dump(mode="python")) != row.request_fingerprint:
                raise ValueError("ANALYSIS_REQUEST_INTEGRITY")
            context = json.loads(row.context_json)
            resolved_inputs = {
                k: v for k, v in context.items() if k != "resolved_analysis_input_fingerprint"
            }
            if (
                fingerprint_payload(resolved_inputs)
                != context["resolved_analysis_input_fingerprint"]
            ):
                raise ValueError("ANALYSIS_CONTEXT_INTEGRITY")
            run = self.repository.get_run(run_id)
            if run is None or run.validator_policy_fingerprint != fingerprint_payload(context):
                raise ValueError("ANALYSIS_CONTEXT_INTEGRITY")
            model = self.repository.get_evidence_pack(context["evidence_pack_id"])
            if model is None or model.fingerprint != context["evidence_pack_fingerprint"]:
                raise ValueError("ANALYSIS_EVIDENCE_INTEGRITY")
            pack = _pack_from_model(model)
            if (
                pack.temporal_context.knowledge_cutoff
                != datetime.fromisoformat(context["resolved_knowledge_cutoff"])
                or pack.temporal_context.market_data_cutoff != request.market_data_cutoff
            ):
                raise ValueError("ANALYSIS_CONTEXT_INTEGRITY")
            memory = self.store.read(context["context_artifact"])["case_memory"]
            gate = GateResult.model_validate(context["preflight_gate"])
            if gate.decision != "PROCEED":
                outcome = {
                    "WAIT_FOR_EVIDENCE": "WAIT_FOR_EVIDENCE",
                    "ABSTAIN": "ABSTAINED",
                    "REJECT": "REJECTED",
                }[gate.decision]
                self.analyses.checkpoint(
                    run_id,
                    epoch,
                    progress="TERMINAL",
                    outcome=outcome,
                    lifecycle="REJECTED" if gate.decision == "REJECT" else "COMPLETED",
                    gate=gate.model_dump(mode="json"),
                )
                return
            diagnosis_ref = (
                json.loads(row.diagnosis_json)
                if row.diagnosis_json
                else self._stage(run_id, epoch, 1, request, pack, context, memory, None)
            )
            if diagnosis_ref is None:
                return
            row = self.analyses.get(run_id)
            if row.active_epoch_id != epoch:
                return
            diagnosis = self.store.read(diagnosis_ref["artifact"])
            if row.gate_json:
                gate = GateResult.model_validate_json(row.gate_json)
            else:
                findings = []
                if diagnosis.get("abstention"):
                    findings.append(
                        _finding(
                            ValidationLayer.SEMANTIC, "FUNDAMENTALLY_UNANSWERABLE", retryable=False
                        )
                    )
                if not diagnosis.get("claims") and not diagnosis.get("observations"):
                    findings.append(
                        _finding(ValidationLayer.SEMANTIC, "INSUFFICIENT_EVIDENCE", retryable=False)
                    )
                gate = ResearchGate().decide(
                    findings=findings,
                    evidence_context=pack.evidence_context,
                    requirements=pack.requirements,
                )
                self.analyses.checkpoint(
                    run_id, epoch, progress="STAGE_GATE_DECIDED", gate=gate.model_dump(mode="json")
                )
            if gate.decision != "PROCEED":
                outcome = {
                    "WAIT_FOR_EVIDENCE": "WAIT_FOR_EVIDENCE",
                    "ABSTAIN": "ABSTAINED",
                    "REJECT": "REJECTED",
                }[gate.decision]
                self._stop(
                    run_id, epoch, outcome, "REJECTED" if gate.decision == "REJECT" else "COMPLETED"
                )
                return
            recommended = self._stage(
                run_id,
                epoch,
                2,
                request,
                pack,
                context,
                memory,
                {
                    "diagnosis_id": diagnosis_ref["fingerprint"],
                    "fingerprint": diagnosis_ref["fingerprint"],
                    "diagnosis": diagnosis,
                },
            )
            if recommended is not None:
                self._stop(run_id, epoch, "PROCEEDED", "COMPLETED")
        except OSError:
            # Local artifact failure is not evidence of an upstream cancellation.
            # Any possibly dispatched STARTED attempt retains unknown accounting.
            self._stop(run_id, epoch, "REJECTED", "REJECTED")
        except ValueError as error:
            code = str(error)
            if self.analyses.get(run_id).active_epoch_id != epoch:
                return
            outcome = (
                "BUDGET_BLOCKED"
                if code.startswith("AI_BUDGET")
                else "PROVIDER_FAILED"
                if code.startswith("AI_HOST")
                else "REJECTED"
            )
            self._stop(run_id, epoch, outcome, "REJECTED" if outcome == "REJECTED" else "FAILED")

    def _ensure_host(self, run_id: str) -> None:
        if self.host_checked:
            return
        availability = getattr(self.client, "availability", None)
        if availability is None:
            raise ValueError("AI_HOST_AVAILABILITY_UNAVAILABLE")
        try:
            ready = availability()
        except ProviderFailure:
            raise ValueError("AI_HOST_AVAILABILITY_UNAVAILABLE") from None
        if not all(
            getattr(ready, field, False) is True
            for field in (
                "host_ready",
                "profile_valid",
                "credential_store_accessible",
                "credential_available",
            )
        ):
            raise ValueError("AI_HOST_CREDENTIAL_UNAVAILABLE")
        run = self.repository.get_run(run_id)
        config = self.repository.get_model_config(run.model_config_version_id) if run else None
        if config is None:
            raise ValueError("AI_MODEL_CONFIG_NOT_FOUND")
        profile = ProviderModelParameters.model_validate_json(
            config.parameters_json
        ).provider_profile
        if (
            ready.profile_id != profile.profile_id
            or ready.endpoint_fingerprint != profile.fingerprint
            or ready.protocol_version != "1"
        ):
            raise ValueError("AI_HOST_PROFILE_MISMATCH")
        self.host_checked = True

    def _new_attempt(
        self,
        run_id: str,
        epoch: str,
        stage: str,
        binding: dict[str, object],
        parent: Attempt | None,
        reasons: tuple[str, ...],
        feedback: tuple[ValidationFeedback, ...],
    ) -> Attempt:
        self._ensure_host(run_id)
        with Session(self.repository.engine, expire_on_commit=False) as session:
            session.execute(text("BEGIN IMMEDIATE"))
            run = session.get(Run, run_id)
            from quant_lab.ai.analysis_persistence import AIAnalysisOrchestrationModel

            row = session.get(AIAnalysisOrchestrationModel, run_id)
            if (
                run is None
                or row is None
                or row.active_epoch_id != epoch
                or run.status not in {"RUNNING", "VALIDATING"}
            ):
                raise ValueError("ANALYSIS_EXECUTION_NOT_OWNED")
            model = self.repository.get_model_config(run.model_config_version_id)
            if model is None:
                raise ValueError("AI_MODEL_CONFIG_NOT_FOUND")
            parameters = ProviderModelParameters.model_validate_json(model.parameters_json)
            calls, charged = _charged(session, run_id)
            parameters.budget.preflight(
                calls, charged, parameters.budget.max_input_tokens, parameters.max_output_tokens
            )
            number = (
                session.scalar(
                    select(func.max(Attempt.attempt_number)).where(Attempt.run_id == run_id)
                )
                or 0
            ) + 1
            attempt = Attempt(
                id=str(uuid4()),
                run_id=run_id,
                attempt_number=number,
                status="STARTED",
                stage=stage,
                parent_attempt_id=parent.id if parent else None,
                retry_reason_codes_json=json.dumps(reasons),
                validation_feedback_fingerprint=fingerprint_payload(
                    [f.model_dump() for f in feedback]
                )
                if feedback
                else None,
                input_fingerprint=fingerprint_payload(binding),
                started_at=datetime.now(UTC),
            )
            session.add(attempt)
            session.flush()
            session.add(
                StageBinding(
                    attempt_id=attempt.id,
                    run_id=run_id,
                    epoch_id=epoch,
                    binding_json=json.dumps(binding, sort_keys=True),
                    fingerprint=fingerprint_payload(binding),
                    created_at=datetime.now(UTC),
                )
            )
            _trace(
                session,
                run_id,
                "STAGE1_ATTEMPT" if stage == "STAGE_1_DIAGNOSIS" else "STAGE2_ATTEMPT",
                {
                    "attempt_id": attempt.id,
                    "binding_fingerprint": fingerprint_payload(binding),
                    "parent_attempt_id": attempt.parent_attempt_id,
                },
            )
            session.commit()
            session.expunge(attempt)
            return attempt

    def _candidate(self, run_id: str, attempt_id: str) -> str:
        for event in reversed(self.repository.list_trace(run_id)):
            payload = json.loads(event.payload_json)
            if payload.get("attempt_id") == attempt_id:
                for artifact in payload.get("artifacts", []):
                    if artifact.get("kind") == "candidate":
                        content = self.store.read(artifact)["content"]
                        if not isinstance(content, str):
                            raise ValueError("ANALYSIS_CANDIDATE_ARTIFACT_INVALID")
                        return content
        raise ValueError("ANALYSIS_CANDIDATE_ARTIFACT_MISSING")

    def _accept(
        self,
        run_id: str,
        epoch: str,
        number: int,
        attempt_id: str,
        validation_id: str,
        candidate: str,
    ) -> dict[str, Any]:
        contract = ResearchDiagnosis if number == 1 else ResearchRecommendation
        artifact = self.store.write(
            "accepted", contract.model_validate_json(candidate).model_dump(mode="json")
        )
        accepted = {
            "artifact": artifact,
            "fingerprint": artifact["sha256"],
            "validation_result_id": validation_id,
            "attempt_id": attempt_id,
        }
        self.analyses.checkpoint(
            run_id,
            epoch,
            progress="STAGE1_ACCEPTED" if number == 1 else "STAGE2_ACCEPTED",
            diagnosis=accepted if number == 1 else None,
            recommendation=accepted if number == 2 else None,
        )
        return accepted

    @staticmethod
    def _nonretryable(result: ValidationResult) -> bool:
        return any(
            not f.retryable
            or f.layer
            in {ValidationLayer.GROUNDING, ValidationLayer.TEMPORAL, ValidationLayer.IMMUTABLE_FACT}
            for f in result.findings
            if f.severity == FindingSeverity.ERROR
        )

    def _stage(
        self,
        run_id: str,
        epoch: str,
        number: int,
        request: ResearchAnalysisRequest,
        pack: EvidencePack,
        context: dict[str, Any],
        memory: list[dict[str, object]],
        diagnosis: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        stage = "STAGE_1_DIAGNOSIS" if number == 1 else "STAGE_2_RECOMMENDATION"
        stage_attempts = [a for a in self.repository.list_attempts(run_id) if a.stage == stage]
        parent = stage_attempts[-1] if stage_attempts else None
        records = self.repository.list_validation_results(run_id)
        prior: list[AcceptedAssertion | AssertionObservation] = []
        feedback: tuple[ValidationFeedback, ...] = ()
        reasons: tuple[str, ...] = ()
        validation_count = 0
        stage_ids = {a.id for a in stage_attempts}
        for record in records:
            result = _result(record)
            prior.extend(result.accepted_assertions)
            prior.extend(result.observations)
            if record.attempt_id in stage_ids:
                validation_count += 1
                if not result.accepted:
                    feedback = ValidationFeedbackBuilder().build(result)
                    reasons = result.error_codes
        last_record = next(
            (r for r in records if parent is not None and r.attempt_id == parent.id), None
        )
        if last_record is not None and parent is not None:
            last_result = _result(last_record)
            self.analyses.validation_checkpoint(
                run_id, epoch, number, last_record.id, parent.id, last_result.error_codes
            )
            if last_result.accepted:
                return self._accept(
                    run_id,
                    epoch,
                    number,
                    parent.id,
                    last_record.id,
                    self._candidate(run_id, parent.id),
                )
            if self._nonretryable(last_result):
                self._stop(run_id, epoch, "REJECTED", "REJECTED")
                return None
        if parent is not None and parent.status == "FAILED":
            self._stop(run_id, epoch, "PROVIDER_FAILED")
            return None
        if parent is not None and parent.status == "ABANDONED":
            reasons = ("USER_CONFIRMED_PROVIDER_RESULT_UNKNOWN",)
        template_id = (
            request.stage1_prompt_template_version_id
            if number == 1
            else request.stage2_prompt_template_version_id
        )
        template = self.repository.get_prompt_template(template_id)
        if template is None or template.fingerprint != context["template_fingerprints"][number - 1]:
            raise ValueError("ANALYSIS_PROMPT_INTEGRITY")
        self.analyses.checkpoint(
            run_id, epoch, progress="STAGE1_PENDING" if number == 1 else "STAGE2_PENDING"
        )
        while True:
            # A completed invocation with no durable validation is replayed locally, never re-sent.
            unvalidated = (
                parent is not None
                and parent.status == "COMPLETED"
                and not any(r.attempt_id == parent.id for r in records)
            )
            if unvalidated:
                assert parent is not None
                attempt = parent
            else:
                if validation_count >= 3:
                    self._stop(run_id, epoch, "VALIDATION_FAILED")
                    return None
                rendered = render_analysis_prompt(
                    template=template,
                    pack=pack,
                    research_question=request.research_question,
                    analysis_type=request.analysis_type,
                    case_memory=memory,
                    diagnosis=diagnosis,
                    validation_feedback=feedback,
                )
                artifact = self.store.write(
                    "prompt", {"messages": [m.model_dump(mode="json") for m in rendered.messages]}
                )
                run = self.repository.get_run(run_id)
                if run is None:
                    raise ValueError("ANALYSIS_NOT_FOUND")
                binding = {
                    "stage": stage,
                    "prompt_template_version_id": template.id,
                    "prompt_template_fingerprint": template.fingerprint,
                    "stage_contract_version": context[
                        "stage1_contract" if number == 1 else "stage2_contract"
                    ],
                    "base_prompt_fingerprint": rendered.base_prompt_fingerprint,
                    "rendered_prompt_fingerprint": rendered.rendered_prompt_fingerprint,
                    "prompt_artifact": artifact,
                    "evidence_pack_fingerprint": pack.fingerprint,
                    "retrieval_snapshot_fingerprint": context["retrieval_snapshot_fingerprint"],
                    "request_fingerprint": fingerprint_payload(request.model_dump(mode="python")),
                    "resolved_analysis_input_fingerprint": context[
                        "resolved_analysis_input_fingerprint"
                    ],
                    "model_config_fingerprint": run.model_config_fingerprint,
                    "diagnosis_fingerprint": diagnosis["fingerprint"] if diagnosis else None,
                }
                attempt = self._new_attempt(
                    run_id, epoch, stage, binding, parent, reasons, feedback
                )
                try:
                    attempt = self.provider.execute(
                        AuthorizedProviderContext(
                            attempt.id,
                            pack.id,
                            pack.fingerprint,
                            "PROCEED",
                            fingerprint_payload(
                                json.loads(self.analyses.get(run_id).gate_json or "null")
                                if number == 2
                                else context["preflight_gate"]
                            ),
                        ),
                        rendered.messages,
                    )
                except ValueError:
                    if self.analyses.get(run_id).active_epoch_id != epoch:
                        return None
                    raise
            if attempt.status == "ABANDONED":
                self.analyses.checkpoint(
                    run_id,
                    epoch,
                    progress="STAGE1_PENDING" if number == 1 else "STAGE2_PENDING",
                    outcome="PROVIDER_RESULT_UNKNOWN",
                    unknown=True,
                    release=True,
                )
                return None
            if attempt.status != "COMPLETED":
                self._stop(run_id, epoch, "PROVIDER_FAILED")
                return None
            candidate = self._candidate(run_id, attempt.id)
            result = ValidationService().validate(
                candidate,
                pack,
                origin_attempt_id=attempt.id,
                prior_assertions=prior,
                freshness_requirement=request.freshness_requirement,
                reference_now=datetime.now(UTC),
                stage_contract=cast(
                    StageContract, context["stage1_contract" if number == 1 else "stage2_contract"]
                ),
                expected_analysis_type=request.analysis_type,
                expected_diagnosis_ref=str(diagnosis["fingerprint"]) if diagnosis else None,
            )
            validation = ValidationResultRecorder(self.repository).record(
                run_id=run_id, attempt_id=attempt.id, evidence_pack_id=pack.id, result=result
            )
            self.analyses.validation_checkpoint(
                run_id, epoch, number, validation.id, attempt.id, result.error_codes
            )
            records = self.repository.list_validation_results(run_id)
            validation_count += 1
            if result.accepted:
                return self._accept(run_id, epoch, number, attempt.id, validation.id, candidate)
            if self._nonretryable(result):
                self._stop(run_id, epoch, "REJECTED", "REJECTED")
                return None
            prior.extend(result.observations)
            feedback = ValidationFeedbackBuilder().build(result)
            reasons, parent = result.error_codes, attempt
