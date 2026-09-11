from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from quant_lab.ai.analysis_artifacts import AnalysisArtifactStore
from quant_lab.ai.analysis_context import CONTEXT_POLICY_VERSION, AnalysisContextBuilder
from quant_lab.ai.analysis_contracts import (
    ANALYSIS_VALIDATION_POLICY_VERSION,
    STAGE1_CONTRACT_VERSION,
    STAGE2_CONTRACT_VERSION,
    ResearchAnalysisRequest,
)
from quant_lab.ai.analysis_freeze import ContextFreezeRepository
from quant_lab.ai.analysis_persistence import AIAnalysisOrchestrationModel
from quant_lab.ai.analysis_prompts import publish_analysis_prompts
from quant_lab.ai.analysis_repository import AnalysisRepository
from quant_lab.ai.configuration import PromptTemplateVersionService
from quant_lab.ai.fingerprints import fingerprint_payload
from quant_lab.ai.persistence import AIAnalysisRunModel
from quant_lab.ai.provider_configuration import ProviderModelParameters
from quant_lab.ai.provider_execution import ProviderHostClient
from quant_lab.ai.repository import AIRepository
from quant_lab.ai.resolvers import EvidenceResolverRegistry


class ResearchAnalysisService:
    def __init__(
        self,
        repository: AIRepository,
        registry: EvidenceResolverRegistry,
        client: ProviderHostClient,
        artifact_root: Path,
    ) -> None:
        self.repository, self.registry, self.client = repository, registry, client
        self.store = AnalysisArtifactStore(artifact_root)
        self.analyses = AnalysisRepository(repository.engine)

    def create(self, request: ResearchAnalysisRequest, key: str) -> AIAnalysisOrchestrationModel:
        fingerprint = fingerprint_payload(request.model_dump(mode="python"))
        existing = self.analyses.find_create(key, fingerprint)
        if existing:
            return existing
        request_artifact = self.store.write("request", request.model_dump(mode="json"))
        freezes = ContextFreezeRepository(self.repository.engine)
        owner = freezes.claim(key, fingerprint, request_artifact)
        if owner is None:
            existing = self.analyses.find_create(key, fingerprint)
            if existing is None:
                raise ValueError("ANALYSIS_CONTEXT_INTEGRITY")
            return existing
        try:
            return self._freeze(request, key, fingerprint, request_artifact, owner, freezes)
        except Exception:
            freezes.fail(key, owner)
            raise

    def _freeze(
        self,
        request: ResearchAnalysisRequest,
        key: str,
        fingerprint: str,
        request_artifact: dict[str, object],
        owner: str,
        freezes: ContextFreezeRepository,
    ) -> AIAnalysisOrchestrationModel:
        inputs = AIRepository(self.repository.engine, serialize_immutable_creation=True)
        templates = publish_analysis_prompts(PromptTemplateVersionService(inputs))
        if (
            request.stage1_prompt_template_version_id,
            request.stage2_prompt_template_version_id,
        ) != tuple(t.id for t in templates):
            raise ValueError("ANALYSIS_PROMPT_NOT_APPROVED")
        model = self.repository.get_model_config(request.model_config_version_id)
        if model is None:
            raise ValueError("AI_MODEL_CONFIG_NOT_FOUND")
        ProviderModelParameters.model_validate_json(model.parameters_json)
        prepared = AnalysisContextBuilder(inputs, self.registry).build(
            request,
            persist_observations=lambda value: freezes.observe(
                key, owner, self.store.write("context", value)
            ),
        )
        context_artifact = self.store.write("context", {"case_memory": list(prepared.case_memory)})
        context: dict[str, object] = {
            "policy_version": CONTEXT_POLICY_VERSION,
            "evidence_pack_id": prepared.pack.id,
            "evidence_pack_fingerprint": prepared.pack.fingerprint,
            "retrieval_snapshot_id": prepared.retrieval.id if prepared.retrieval else None,
            "retrieval_snapshot_fingerprint": prepared.retrieval.fingerprint
            if prepared.retrieval
            else None,
            "context_artifact": context_artifact,
            "preflight_gate": prepared.gate.model_dump(mode="json"),
            "stage1_contract": STAGE1_CONTRACT_VERSION,
            "stage2_contract": STAGE2_CONTRACT_VERSION,
            "template_ids": [t.id for t in templates],
            "template_fingerprints": [t.fingerprint for t in templates],
            "max_validation_retries": 2,
            "submitted_request_fingerprint": fingerprint,
            "knowledge_cutoff_mode": request.knowledge_cutoff_mode,
            "resolved_knowledge_cutoff": prepared.resolved_knowledge_cutoff.isoformat(),
            "market_data_cutoff": request.market_data_cutoff.isoformat(),
        }
        context["resolved_analysis_input_fingerprint"] = fingerprint_payload(context)
        case = self.repository.get_research_case(prepared.pack.case_id)
        if case is None:
            raise ValueError("ANALYSIS_CASE_NOT_FOUND")
        run = AIAnalysisRunModel(
            id=str(uuid4()),
            case_id=prepared.pack.case_id,
            stage="TWO_STAGE_RESEARCH",
            status="CREATED",
            prompt_template_version_id=templates[0].id,
            model_config_version_id=model.id,
            case_fingerprint=case.fingerprint,
            prompt_template_fingerprint=templates[0].fingerprint,
            resolved_prompt_fingerprint=fingerprint_payload(
                {"request": fingerprint, "context": context}
            ),
            model_config_fingerprint=model.fingerprint,
            validator_policy_version=ANALYSIS_VALIDATION_POLICY_VERSION,
            validator_policy_fingerprint=fingerprint_payload(context),
            input_envelope_fingerprint=prepared.pack.fingerprint,
            created_at=datetime.now(UTC),
        )
        return self.analyses.attach(
            run.id, key, fingerprint, request_artifact, context, run=run, freeze_owner=owner
        )

    def execute(
        self, run_id: str, key: str, intent: str = "INITIAL"
    ) -> AIAnalysisOrchestrationModel:
        from quant_lab.ai.analysis_execution import TwoStageResearchExecution

        epoch, fresh = self.analyses.claim(
            run_id, key, fingerprint_payload({"intent": intent}), intent
        )
        if not fresh or epoch is None:
            return self.analyses.get(run_id)
        execution = TwoStageResearchExecution(
            self.repository, self.client, self.store, self.analyses
        )
        execution.run(run_id, epoch.id)
        return self.analyses.get(run_id)

    def cancel(self, run_id: str) -> AIAnalysisOrchestrationModel:
        self.analyses.cancel(run_id)
        return self.analyses.get(run_id)

    def recover(self) -> None:
        self.analyses.recover()
