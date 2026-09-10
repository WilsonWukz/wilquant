"""Explicitly authorized, tiny external smoke with isolated durable Core provenance."""

from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from alembic.config import Config

from alembic import command
from quant_lab.ai.cases import ResearchCaseInput, ResearchCaseService
from quant_lab.ai.configuration import AIModelConfigVersionService, PromptTemplateVersionService
from quant_lab.ai.contracts import AnalysisRequirements, EvidenceContext, TemporalContext
from quant_lab.ai.fingerprints import fingerprint_payload
from quant_lab.ai.packs import EvidencePackService
from quant_lab.ai.provenance import AIProvenanceService
from quant_lab.ai.provider_budget import ProviderBudgetPolicy
from quant_lab.ai.provider_execution import AIProviderExecutionService, AuthorizedProviderContext
from quant_lab.ai.repository import AIRepository
from quant_lab.ai_provider_client import AIProviderHostClient
from quant_lab.ai_provider_protocol import EndpointProfile, ProviderMessage
from quant_lab.core.config import Settings
from quant_lab.db.sqlite import create_sqlite_engine


def smoke_context(
    repository: AIRepository, profile: EndpointProfile
) -> tuple[AuthorizedProviderContext, list[ProviderMessage]]:
    """Synthetic protocol fixture only; never queries portfolio or research sources."""
    now = datetime.now(UTC)
    marker = fingerprint_payload({"synthetic": "PROVIDER_PROTOCOL_SMOKE_NOT_MARKET_EVIDENCE"})
    case = ResearchCaseService(repository).freeze(
        ResearchCaseInput(
            purpose="PROVIDER_PROTOCOL_SMOKE",
            market="CN_A_SHARE",
            exchange="SYNTHETIC",
            symbol="SMOKE",
            instrument_id="SYNTHETIC:SMOKE",
            asset_type="EQUITY",
            currency="CNY",
            timeframe="NONE",
            as_of_utc=now,
            market_local_trade_date=now.date(),
            bindings={
                "market_data_fingerprint": marker,
                "calendar_fingerprint": marker,
                "market_rules_fingerprint": marker,
            },
        ),
        actor="USER",
    )
    prompt = PromptTemplateVersionService(repository).publish(
        template_name="provider-smoke",
        stage="DIAGNOSIS",
        schema_version="provider-smoke-v1",
        content="Return JSON.",
        variable_contract={},
        validator_policy_version="ai-smoke-no-acceptance-v1",
        actor="USER",
    )
    model = AIModelConfigVersionService(repository).publish(
        provider_kind="OPENAI_COMPATIBLE",
        provider_id=profile.profile_id,
        base_url_identity=profile.base_url,
        model_identifier=profile.model,
        endpoint_profile_id=profile.profile_id,
        capabilities=profile.capabilities.model_dump(mode="json"),
        parameters={
            "provider_profile": profile.model_dump(mode="json"),
            "max_output_tokens": 32,
            "budget": ProviderBudgetPolicy(
                max_calls=1, max_input_tokens=2048, max_output_tokens=32
            ).model_dump(mode="json"),
            "response_format": "JSON_OBJECT"
            if profile.capabilities.supports_json_object
            else "TEXT",
        },
        actor="USER",
    )
    pack = EvidencePackService(repository).freeze(
        case_id=case.id,
        temporal_context=TemporalContext(
            market_data_cutoff=now,
            knowledge_cutoff=now,
            market="CN_A_SHARE",
            timezone="UTC",
            asset_type="EQUITY",
            analysis_mode="CURRENT_RESEARCH",
        ),
        evidence_context=EvidenceContext(
            market="CN_A_SHARE",
            instrument_id="SYNTHETIC:SMOKE",
            asset_type="EQUITY",
            timezone="UTC",
        ),
        requirements=AnalysisRequirements(),
        items=[],
    )
    messages = [
        ProviderMessage(role="system", content="Return JSON."),
        ProviderMessage(role="user", content='Return {"status":"ok"} as JSON.'),
    ]
    service = AIProvenanceService(repository)
    run = service.create_run(
        case_id=case.id,
        stage="DIAGNOSIS",
        prompt_template_version_id=prompt.id,
        model_config_version_id=model.id,
        resolved_prompt_fingerprint=fingerprint_payload([m.model_dump() for m in messages]),
        validator_policy_version="ai-smoke-no-acceptance-v1",
        validator_policy_fingerprint=marker,
    )
    service.start_run(run.id, pack.fingerprint)
    attempt = service.start_attempt(run.id, pack.fingerprint)
    return AuthorizedProviderContext(
        attempt_id=attempt.id,
        evidence_pack_id=pack.id,
        evidence_pack_fingerprint=pack.fingerprint,
        gate_decision="PROCEED",
        gate_fingerprint=fingerprint_payload({"manual_protocol_smoke_confirmed": True}),
    ), messages


def main() -> None:
    parser = argparse.ArgumentParser(description="Tiny manual smoke; may incur provider cost")
    parser.add_argument("--confirm-external-call", action="store_true", required=True)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--token-file", type=Path, required=True)
    parser.add_argument("--audit-root", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8011)
    args = parser.parse_args()
    try:
        profile = EndpointProfile.model_validate_json(args.profile.read_bytes())
        audit = args.audit_root.resolve() / ("smoke-" + str(uuid4()))
        audit.mkdir(parents=True, exist_ok=False)
        # This standalone process targets a new audit database, never the main runtime.
        os.environ["QUANT_LAB_PROJECT_ROOT"] = str(audit)
        os.environ["QUANT_LAB_RUNTIME_ROOT"] = str(audit)
        # Absolute inherited settings (including .env) must not redirect this audit.
        # Alembic and the repository both construct Settings from this same override.
        os.environ["QUANT_LAB_SQLITE_PATH"] = str(audit / "data" / "quant_lab.db")
        config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
        command.upgrade(config, "head")
        engine = create_sqlite_engine(Settings())
        try:
            repository = AIRepository(engine)
            context, messages = smoke_context(repository, profile)
            client = AIProviderHostClient(f"http://127.0.0.1:{args.port}", args.token_file)
            result = AIProviderExecutionService(repository, client, audit).execute(
                context, messages
            )
            service = AIProvenanceService(repository)
            usage = service.list_usage(result.run_id)[0]
            service.cancel_run(result.run_id)  # Infrastructure smoke is not an accepted analysis.
            print(
                json.dumps(
                    {
                        "provider_type": "OPENAI_COMPATIBLE",
                        "model": profile.model,
                        "attempt_status": result.status,
                        "failure_code": result.failure_code,
                        "latency_ms": result.latency_ms,
                        "finish_reason": result.finish_reason,
                        "prompt_tokens": usage.prompt_tokens,
                        "completion_tokens": usage.completion_tokens,
                        "total_tokens": usage.total_tokens,
                        "estimated_cost": "UNKNOWN",
                        "audit_root": str(audit),
                    },
                    ensure_ascii=False,
                )
            )
            if result.status != "COMPLETED":
                raise SystemExit(1)
        finally:
            engine.dispose()
    except (OSError, ValueError, KeyError):
        parser.exit(1, "AI_PROVIDER_SMOKE_FAILED\n")


if __name__ == "__main__":
    main()
