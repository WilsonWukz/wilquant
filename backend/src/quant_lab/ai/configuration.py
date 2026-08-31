from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from uuid import uuid4

from quant_lab.ai.fingerprints import fingerprint_payload
from quant_lab.ai.persistence import (
    AIModelConfigVersionModel,
    AIPromptTemplateVersionModel,
)
from quant_lab.ai.repository import AIRepository

FORBIDDEN_SECRET_KEY_NAMES = frozenset(
    {
        "accesstoken",
        "apikey",
        "authorization",
        "bearertoken",
        "credential",
        "credentials",
        "idtoken",
        "password",
        "refreshtoken",
        "secret",
        "sessiontoken",
        "token",
    }
)
FORBIDDEN_SECRET_KEY_SUFFIXES = ("apikey", "authorization", "credential", "password", "secret")
FORBIDDEN_SECRET_TEXT_PATTERNS = (
    re.compile(r"(?i)\b(?:sk|pk)-[a-z0-9_-]{20,}\b"),
    re.compile(r"(?i)\bauthorization\s*:\s*bearer\s+\S{12,}"),
    re.compile(r"(?i)\b(?:api[_-]?key|access[_-]?token)\s*[:=]\s*\S{12,}"),
)


class AIProvenanceError(Exception):
    """Stable, client-safe AI provenance failure."""

    def __init__(self, category: str, safe_message: str) -> None:
        super().__init__(category)
        self.category = category
        self.safe_message = safe_message


def _canonical_json_text(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _contains_forbidden_secret_key(value: object) -> bool:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            normalized = "".join(character for character in str(key).lower() if character.isalnum())
            if normalized in FORBIDDEN_SECRET_KEY_NAMES or normalized.endswith(
                FORBIDDEN_SECRET_KEY_SUFFIXES
            ):
                return True
            if _contains_forbidden_secret_key(nested):
                return True
        return False
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return any(_contains_forbidden_secret_key(item) for item in value)
    return False


def contains_forbidden_secret_material(value: object) -> bool:
    if _contains_forbidden_secret_key(value):
        return True
    if isinstance(value, str):
        return any(pattern.search(value) is not None for pattern in FORBIDDEN_SECRET_TEXT_PATTERNS)
    if isinstance(value, Mapping):
        return any(contains_forbidden_secret_material(item) for item in value.values())
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return any(contains_forbidden_secret_material(item) for item in value)
    return False


class PromptTemplateVersionService:
    def __init__(self, repository: AIRepository) -> None:
        self.repository = repository

    def publish(
        self,
        *,
        template_name: str,
        stage: str,
        schema_version: str,
        content: str,
        variable_contract: Mapping[str, object],
        validator_policy_version: str,
        actor: str,
    ) -> AIPromptTemplateVersionModel:
        content_sha256 = hashlib.sha256(content.encode("utf-8")).hexdigest()
        contract = dict(variable_contract)
        variable_contract_sha256 = fingerprint_payload(contract)
        payload = {
            "template_name": template_name,
            "stage": stage,
            "schema_version": schema_version,
            "content_sha256": content_sha256,
            "variable_contract_sha256": variable_contract_sha256,
            "validator_policy_version": validator_policy_version,
        }
        fingerprint = fingerprint_payload(payload)
        existing = self.repository.find_prompt_template_by_fingerprint(fingerprint)
        if existing is not None:
            return existing
        return self.repository.add_prompt_template(
            AIPromptTemplateVersionModel(
                id=str(uuid4()),
                template_name=template_name,
                stage=stage,
                schema_version=schema_version,
                content=content,
                content_sha256=content_sha256,
                variable_contract_json=_canonical_json_text(contract),
                variable_contract_sha256=variable_contract_sha256,
                validator_policy_version=validator_policy_version,
                fingerprint=fingerprint,
                status="PUBLISHED",
                created_by=actor,
                created_at=datetime.now(UTC),
            )
        )


class AIModelConfigVersionService:
    def __init__(self, repository: AIRepository) -> None:
        self.repository = repository

    def publish(
        self,
        *,
        provider_kind: str,
        provider_id: str,
        base_url_identity: str,
        model_identifier: str,
        endpoint_profile_id: str,
        capabilities: Mapping[str, object],
        parameters: Mapping[str, object],
        actor: str,
    ) -> AIModelConfigVersionModel:
        frozen_capabilities = dict(capabilities)
        frozen_parameters = dict(parameters)
        if _contains_forbidden_secret_key(frozen_capabilities) or _contains_forbidden_secret_key(
            frozen_parameters
        ):
            raise AIProvenanceError(
                "AI_MODEL_CONFIG_SECRET_FORBIDDEN",
                "模型配置不得包含密钥或认证信息",
            )
        payload = {
            "provider_kind": provider_kind,
            "provider_id": provider_id,
            "base_url_identity": base_url_identity,
            "model_identifier": model_identifier,
            "endpoint_profile_id": endpoint_profile_id,
            "capabilities": frozen_capabilities,
            "parameters": frozen_parameters,
        }
        fingerprint = fingerprint_payload(payload)
        existing = self.repository.find_model_config_by_fingerprint(fingerprint)
        if existing is not None:
            return existing
        return self.repository.add_model_config(
            AIModelConfigVersionModel(
                id=str(uuid4()),
                provider_kind=provider_kind,
                provider_id=provider_id,
                base_url_identity=base_url_identity,
                model_identifier=model_identifier,
                endpoint_profile_id=endpoint_profile_id,
                capabilities_json=_canonical_json_text(frozen_capabilities),
                parameters_json=_canonical_json_text(frozen_parameters),
                fingerprint=fingerprint,
                created_by=actor,
                created_at=datetime.now(UTC),
            )
        )
