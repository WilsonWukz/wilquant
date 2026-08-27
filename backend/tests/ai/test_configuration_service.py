from __future__ import annotations

import pytest
from sqlalchemy import create_engine

from quant_lab.ai import persistence  # noqa: F401
from quant_lab.ai.configuration import (
    AIModelConfigVersionService,
    AIProvenanceError,
    PromptTemplateVersionService,
)
from quant_lab.ai.repository import AIRepository
from quant_lab.db.sqlite import Base


@pytest.fixture
def services():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    repository = AIRepository(engine)
    return PromptTemplateVersionService(repository), AIModelConfigVersionService(repository)


def test_prompt_template_publication_is_idempotent_by_canonical_content(services) -> None:
    prompts, _ = services
    first = prompts.publish(
        template_name="diagnosis",
        stage="DIAGNOSIS",
        schema_version="diagnosis@1",
        content="仅分析冻结证据",
        variable_contract={"required": ["case", "evidence"]},
        validator_policy_version="validators@1",
        actor="USER",
    )
    same = prompts.publish(
        template_name="diagnosis",
        stage="DIAGNOSIS",
        schema_version="diagnosis@1",
        content="仅分析冻结证据",
        variable_contract={"required": ["case", "evidence"]},
        validator_policy_version="validators@1",
        actor="USER",
    )
    changed = prompts.publish(
        template_name="diagnosis",
        stage="DIAGNOSIS",
        schema_version="diagnosis@1",
        content="仅分析冻结且可引用的证据",
        variable_contract={"required": ["case", "evidence"]},
        validator_policy_version="validators@1",
        actor="USER",
    )

    assert same.id == first.id
    assert changed.id != first.id
    assert changed.fingerprint != first.fingerprint


def test_model_config_freezes_provider_neutral_profile_and_is_idempotent(services) -> None:
    _, models = services
    values = {
        "provider_kind": "OPENAI_COMPATIBLE",
        "provider_id": "research-primary",
        "base_url_identity": "https://api.example.invalid/v1",
        "model_identifier": "research-model-v1",
        "endpoint_profile_id": "primary",
        "capabilities": {
            "structured_output": True,
            "reasoning_mode": "OPTIONAL",
            "streaming": True,
        },
        "parameters": {"temperature": 0, "tool_configuration": "NONE"},
        "actor": "USER",
    }
    first = models.publish(**values)
    same = models.publish(**values)
    changed = models.publish(**{**values, "model_identifier": "research-model-v2"})

    assert first.id == same.id
    assert first.id != changed.id
    assert first.provider_kind == "OPENAI_COMPATIBLE"
    assert first.provider_id == "research-primary"
    assert "deepseek" not in first.provider_kind.lower()


@pytest.mark.parametrize(
    "payload",
    [
        {"api_key": "forbidden"},
        {"nested": {"authorization": "Bearer forbidden"}},
        {"items": [{"password": "forbidden"}]},
        {"credential": "forbidden"},
        {"client_secret": "forbidden"},
        {"access_token": "forbidden"},
        {"refreshToken": "forbidden"},
        {"nested": {"serviceApiKey": "forbidden"}},
    ],
)
def test_model_config_rejects_nested_secret_fields(services, payload) -> None:
    _, models = services
    with pytest.raises(AIProvenanceError, match="AI_MODEL_CONFIG_SECRET_FORBIDDEN"):
        models.publish(
            provider_kind="FAKE",
            provider_id="fake",
            base_url_identity="local-fake",
            model_identifier="fake-v1",
            endpoint_profile_id="local-fake",
            capabilities={},
            parameters=payload,
            actor="USER",
        )
