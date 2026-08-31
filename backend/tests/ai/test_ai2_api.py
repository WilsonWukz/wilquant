from __future__ import annotations

import json
from collections.abc import AsyncIterator
from decimal import Decimal
from pathlib import Path

import pytest
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from alembic import command
from quant_lab.ai.contracts import CanonicalEvidenceItem
from quant_lab.ai.fingerprints import fingerprint_payload
from quant_lab.core.config import Settings
from quant_lab.db.sqlite import create_sqlite_engine
from quant_lab.main import create_app

pytestmark = pytest.mark.anyio


def _seed_ai2_records(engine) -> None:
    value_fingerprint = fingerprint_payload(
        {"value": Decimal("12.30"), "semantic_type": "MONEY", "unit": "CNY"}
    )
    items = [
        {
            "ref_id": "ev-" + "7" * 64,
            "source_type": "PAPER_ACCOUNT_SNAPSHOT",
            "source_id": "paper-snapshot-1",
            "source_version_id": "snapshot-v1",
            "field_path": "cash",
            "classification": "FACT",
            "semantic_type": "MONEY",
            "value": "12.3",
            "unit": "CNY",
            "subject": "PAPER_ACCOUNT:1",
            "source_fingerprint": "8" * 64,
            "value_fingerprint": value_fingerprint,
            "effective_at": "2026-08-30T08:00:00Z",
            "known_at": "2026-08-30T08:01:00Z",
            "observed_at": "2026-08-30T08:01:00Z",
            "market_timestamp": "2026-08-30T08:00:00Z",
            "freshness_class": "IMMUTABLE_HISTORICAL",
            "known_delay_seconds": None,
            "market": "CN_A_SHARE",
            "asset_type": "EQUITY",
            "instrument_id": None,
            "currency": "CNY",
            "context": {"analysis_scope": "PAPER_ACCOUNT_SNAPSHOT", "market": "CN_A_SHARE"},
            "resolver_policy_version": "1",
            "integrity_status": "VERIFIED",
        }
    ]
    temporal_context = {
        "market_data_cutoff": "2026-08-30T23:59:59Z",
        "knowledge_cutoff": "2026-08-30T23:59:59Z",
        "market": "CN_A_SHARE",
        "timezone": "Asia/Shanghai",
        "asset_type": "EQUITY",
        "analysis_mode": "HISTORICAL_REPLAY",
    }
    evidence_context = {
        "market": "CN_A_SHARE",
        "exchange": "SSE",
        "instrument_id": "SSE:600000",
        "currency": "CNY",
        "asset_type": "EQUITY",
        "timezone": "Asia/Shanghai",
        "market_rules_version": None,
    }
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO ai_prompt_template_versions "
                "(id,template_name,stage,schema_version,content,content_sha256,"
                "variable_contract_json,variable_contract_sha256,validator_policy_version,"
                "fingerprint,status,created_by,created_at) VALUES "
                "('prompt','p','DIAGNOSIS','1','safe',:a,'{}',:b,'v1',:c,'PUBLISHED',"
                "'USER',CURRENT_TIMESTAMP)"
            ),
            {"a": "a" * 64, "b": "b" * 64, "c": "c" * 64},
        )
        connection.execute(
            text(
                "INSERT INTO ai_model_config_versions "
                "(id,provider_kind,provider_id,base_url_identity,model_identifier,"
                "endpoint_profile_id,capabilities_json,parameters_json,fingerprint,"
                "created_by,created_at) VALUES "
                "('model','FAKE','fake','local','fake','fake','{}','{}',:f,'USER',"
                "CURRENT_TIMESTAMP)"
            ),
            {"f": "d" * 64},
        )
        connection.execute(
            text(
                "INSERT INTO ai_research_cases "
                "(id,purpose,market,exchange,symbol,instrument_id,asset_type,currency,"
                "timeframe,as_of_utc,market_local_trade_date,bindings_json,fingerprint,"
                "created_by,created_at) VALUES "
                "('case','TEST','CN_A_SHARE','SSE','600000','SSE:600000','EQUITY','CNY',"
                "'1D',CURRENT_TIMESTAMP,'2026-08-30','{}',:f,'USER',CURRENT_TIMESTAMP)"
            ),
            {"f": "e" * 64},
        )
        connection.execute(
            text(
                "INSERT INTO ai_analysis_runs "
                "(id,case_id,stage,status,prompt_template_version_id,model_config_version_id,"
                "case_fingerprint,prompt_template_fingerprint,resolved_prompt_fingerprint,"
                "model_config_fingerprint,validator_policy_version,validator_policy_fingerprint,"
                "created_at) VALUES "
                "('run','case','DIAGNOSIS','CREATED','prompt','model',:a,:b,:c,:d,'v1',:e,"
                "CURRENT_TIMESTAMP)"
            ),
            {
                "a": "e" * 64,
                "b": "c" * 64,
                "c": "f" * 64,
                "d": "d" * 64,
                "e": "1" * 64,
            },
        )
        connection.execute(
            text(
                "INSERT INTO ai_analysis_attempts "
                "(id,run_id,attempt_number,status,input_fingerprint,started_at) "
                "VALUES ('attempt','run',1,'STARTED',:f,CURRENT_TIMESTAMP)"
            ),
            {"f": "2" * 64},
        )
        connection.execute(
            text(
                "INSERT INTO ai_evidence_packs "
                "(id,case_id,temporal_context_json,evidence_context_json,requirements_json,"
                "items_json,policy_version,fingerprint,created_at) VALUES "
                "('pack','case',:temporal,:context,'{}',:items,'ai-evidence-v2',:f,"
                "CURRENT_TIMESTAMP)"
            ),
            {
                "temporal": json.dumps(temporal_context),
                "context": json.dumps(evidence_context),
                "items": json.dumps(items),
                "f": "3" * 64,
            },
        )
        connection.execute(
            text(
                "INSERT INTO ai_validation_results "
                "(id,run_id,attempt_id,evidence_pack_id,disposition,findings_json,"
                "accepted_assertions_json,observations_json,candidate_fingerprint,"
                "policy_version,fingerprint,created_at) VALUES "
                "('validation','run','attempt','pack','REJECTED',:findings,'[]','[]',:candidate,"
                "'ai-validation-v1',:fingerprint,CURRENT_TIMESTAMP)"
            ),
            {
                "findings": json.dumps(
                    [
                        {
                            "layer": "SCHEMA",
                            "code": "SCHEMA_INVALID_ENUM",
                            "severity": "ERROR",
                            "message_safe": "SCHEMA_INVALID_ENUM",
                            "retryable": True,
                            "claim_id": "c1",
                            "evidence_ref": None,
                            "field_path": "claims[2].predicate",
                        }
                    ]
                ),
                "candidate": "4" * 64,
                "fingerprint": "5" * 64,
            },
        )
        connection.execute(
            text(
                "INSERT INTO ai_retrieval_snapshots "
                "(id,query_json,policy_version,candidates_json,exclusions_json,fingerprint,"
                "created_at) VALUES "
                "('snapshot','{}','ai-retrieval-v1','[]','[]',:f,CURRENT_TIMESTAMP)"
            ),
            {"f": "6" * 64},
        )


@pytest.fixture
async def ai2_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[AsyncClient]:
    settings = Settings(project_root=tmp_path, runtime_root=tmp_path / "runtime")
    monkeypatch.setenv("QUANT_LAB_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("QUANT_LAB_RUNTIME_ROOT", str(settings.runtime_root))
    command.upgrade(Config("backend/alembic.ini"), "head")
    engine = create_sqlite_engine(settings)
    _seed_ai2_records(engine)
    engine.dispose()
    app = create_app(settings)
    transport = ASGITransport(app=app)
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=transport, base_url="http://testserver") as client,
    ):
        yield client


@pytest.mark.parametrize(
    ("path", "identity_field", "identity"),
    (
        ("/api/v1/ai/evidence-packs/pack", "case_id", "case"),
        ("/api/v1/ai/validation-results/validation", "run_id", "run"),
        ("/api/v1/ai/retrieval-snapshots/snapshot", "policy_version", "ai-retrieval-v1"),
    ),
)
async def test_ai2_provenance_endpoints_are_read_only(
    ai2_client: AsyncClient, path: str, identity_field: str, identity: str
) -> None:
    response = await ai2_client.get(path)

    assert response.status_code == 200
    assert response.json()[identity_field] == identity
    assert (await ai2_client.post(path, json={})).status_code == 405
    serialized = response.text.lower()
    assert "api_key" not in serialized
    assert "authorization" not in serialized


async def test_restart_preserves_full_evidence_and_schema_contract(
    ai2_client: AsyncClient,
) -> None:
    pack = (await ai2_client.get("/api/v1/ai/evidence-packs/pack")).json()
    validation = (await ai2_client.get("/api/v1/ai/validation-results/validation")).json()
    retrieval = (await ai2_client.get("/api/v1/ai/retrieval-snapshots/snapshot")).json()

    item = pack["items"][0]
    restored_item = CanonicalEvidenceItem.model_validate(item)
    assert item["semantic_type"] == "MONEY"
    assert item["value_fingerprint"] == fingerprint_payload(
        {"value": Decimal("12.30"), "semantic_type": "MONEY", "unit": "CNY"}
    )
    assert item["freshness_class"] == "IMMUTABLE_HISTORICAL"
    assert item["context"] == {
        "analysis_scope": "PAPER_ACCOUNT_SNAPSHOT",
        "market": "CN_A_SHARE",
    }
    assert item["resolver_policy_version"] == "1"
    assert restored_item.value_fingerprint == item["value_fingerprint"]
    assert validation["findings"][0]["code"] == "SCHEMA_INVALID_ENUM"
    assert validation["findings"][0]["field_path"] == "claims[2].predicate"
    assert retrieval["policy_version"] == "ai-retrieval-v1"


@pytest.mark.parametrize(
    "path",
    (
        "/api/v1/ai/evidence-packs/missing",
        "/api/v1/ai/validation-results/missing",
        "/api/v1/ai/retrieval-snapshots/missing",
    ),
)
async def test_ai2_missing_provenance_is_safe_404(ai2_client: AsyncClient, path: str) -> None:
    response = await ai2_client.get(path)

    assert response.status_code == 404
    assert set(response.json()) == {"error_code", "message"}


async def test_openapi_has_no_ai2_mutation_or_provider_route() -> None:
    paths = create_app().openapi()["paths"]
    ai2_paths = {
        "/api/v1/ai/evidence-packs/{pack_id}",
        "/api/v1/ai/validation-results/{result_id}",
        "/api/v1/ai/retrieval-snapshots/{snapshot_id}",
    }

    assert ai2_paths <= set(paths)
    assert all(set(paths[path]) == {"get"} for path in ai2_paths)
