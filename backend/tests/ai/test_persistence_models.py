from __future__ import annotations

from sqlalchemy import create_engine, inspect

from quant_lab.ai import persistence  # noqa: F401
from quant_lab.db.sqlite import Base

EXPECTED_TABLES = {
    "ai_prompt_template_versions",
    "ai_model_config_versions",
    "ai_research_cases",
    "ai_evidence_refs",
    "ai_analysis_runs",
    "ai_analysis_attempts",
    "ai_analysis_trace_events",
    "ai_usage_ledger",
}


def test_ai_provenance_models_create_expected_tables() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    inspector = inspect(engine)
    assert EXPECTED_TABLES.issubset(set(inspector.get_table_names()))


def test_fingerprint_columns_are_required_sha256_strings() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    inspector = inspect(engine)

    for table_name in EXPECTED_TABLES:
        for column in inspector.get_columns(table_name):
            if "fingerprint" in column["name"] or column["name"].endswith("_sha256"):
                if (table_name, column["name"]) == (
                    "ai_analysis_attempts",
                    "validation_feedback_fingerprint",
                ):
                    # No feedback exists for an initial/legacy Attempt.
                    assert column["nullable"] is True
                    assert getattr(column["type"], "length", None) == 64
                    continue
                if column["name"] in {
                    "input_envelope_fingerprint",
                    "raw_response_artifact_sha256",
                    "normalized_output_fingerprint",
                    "output_fingerprint",
                }:
                    continue
                assert column["nullable"] is False, (table_name, column["name"])
                assert getattr(column["type"], "length", None) == 64


def test_schema_contains_provider_profile_identity_but_no_secrets() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    inspector = inspect(engine)

    model_columns = {column["name"] for column in inspector.get_columns("ai_model_config_versions")}
    assert {
        "provider_kind",
        "provider_id",
        "base_url_identity",
        "model_identifier",
        "endpoint_profile_id",
        "capabilities_json",
    }.issubset(model_columns)

    all_columns = {
        column["name"]
        for table_name in EXPECTED_TABLES
        for column in inspector.get_columns(table_name)
    }
    forbidden_fragments = ("api_key", "secret", "password", "authorization", "credential")
    assert not any(
        fragment in name.lower() for name in all_columns for fragment in forbidden_fragments
    )
