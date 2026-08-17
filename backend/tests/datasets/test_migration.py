from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import Engine, inspect, text

from alembic import command
from quant_lab.core.config import Settings
from quant_lab.db.sqlite import create_sqlite_engine

REVISION_0003 = "20260720_0003"
REVISION_0004 = "20260720_0004"
REVISION_HEAD = "20260722_0010"

PREVIEW_COLUMNS = {
    "source_file_size",
    "field_mapping_json",
    "provider_version",
    "normalization_version",
    "quality_rules_version",
    "preview_fingerprint_version",
    "preview_fingerprint",
    "preview_completed_at",
}
ISSUE_V2_COLUMNS = {"issue_fingerprint_version", "normalized_value"}
PUBLICATION_TABLES = {
    "datasets",
    "dataset_versions",
    "dataset_files",
    "publication_audits",
}
PUBLISHED_TRIGGERS = {
    "trg_dataset_versions_published_no_update",
    "trg_dataset_versions_published_no_delete",
    "trg_dataset_files_published_no_insert",
    "trg_dataset_files_published_no_update",
    "trg_dataset_files_published_no_delete",
}


def _migration_context(tmp_path: Path, monkeypatch) -> tuple[Config, Engine]:
    monkeypatch.setenv("QUANT_LAB_PROJECT_ROOT", str(tmp_path))
    settings = Settings(project_root=tmp_path)
    return Config("backend/alembic.ini"), create_sqlite_engine(settings)


def _column_names(engine: Engine, table_name: str) -> set[str]:
    return {column["name"] for column in inspect(engine).get_columns(table_name)}


def _unique_column_sets(engine: Engine, table_name: str) -> set[tuple[str, ...]]:
    inspector = inspect(engine)
    constraints = {
        tuple(constraint["column_names"])
        for constraint in inspector.get_unique_constraints(table_name)
    }
    indexes = {
        tuple(index["column_names"])
        for index in inspector.get_indexes(table_name)
        if index["unique"]
    }
    return constraints | indexes


def _assert_publication_schema(engine: Engine) -> None:
    inspector = inspect(engine)
    assert _column_names(engine, "import_batches") >= PREVIEW_COLUMNS
    assert _column_names(engine, "data_quality_issues") >= ISSUE_V2_COLUMNS
    assert set(inspector.get_table_names()) >= PUBLICATION_TABLES
    assert not any("bar" in table for table in inspector.get_table_names())

    assert ("dataset_key",) in _unique_column_sets(engine, "datasets")
    assert ("dataset_id", "version") in _unique_column_sets(engine, "dataset_versions")
    assert ("publication_fingerprint",) in _unique_column_sets(engine, "dataset_versions")
    assert ("dataset_version_id", "relative_path") in _unique_column_sets(
        engine, "dataset_files"
    )
    assert ("batch_id", "issue_fingerprint") in _unique_column_sets(
        engine, "data_quality_issues"
    )

    indexes = {
        index["name"]
        for table_name in PUBLICATION_TABLES
        for index in inspector.get_indexes(table_name)
    }
    assert {
        "ix_datasets_is_active",
        "ix_dataset_versions_dataset_status",
        "ix_dataset_versions_source_batch_id",
        "ix_dataset_files_dataset_version_id",
        "ix_publication_audits_batch_created_at",
    } <= indexes

    for table_name in ("dataset_versions", "dataset_files", "publication_audits"):
        foreign_keys = inspector.get_foreign_keys(table_name)
        assert foreign_keys
        assert all(
            foreign_key.get("options", {}).get("ondelete") == "RESTRICT"
            for foreign_key in foreign_keys
        )

    with engine.connect() as connection:
        triggers = {
            row.name: row.sql
            for row in connection.execute(
                text(
                    "SELECT name, sql FROM sqlite_master "
                    "WHERE type = 'trigger' ORDER BY name"
                )
            )
        }
    assert set(triggers) >= PUBLISHED_TRIGGERS
    assert "OLD.status = 'PUBLISHED'" in triggers[
        "trg_dataset_versions_published_no_update"
    ]
    assert "OLD.status = 'PUBLISHED'" in triggers[
        "trg_dataset_versions_published_no_delete"
    ]
    assert "OLD.status = 'PUBLISHED'" not in triggers[
        "trg_dataset_files_published_no_update"
    ]
    assert "status = 'PUBLISHED'" in triggers["trg_dataset_files_published_no_insert"]
    assert "status = 'PUBLISHED'" in triggers["trg_dataset_files_published_no_update"]
    assert "status = 'PUBLISHED'" in triggers["trg_dataset_files_published_no_delete"]


def test_empty_database_upgrades_to_0004_head(tmp_path: Path, monkeypatch) -> None:
    config, engine = _migration_context(tmp_path, monkeypatch)
    command.upgrade(config, "head")

    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one() == REVISION_HEAD
    _assert_publication_schema(engine)
    engine.dispose()


def test_0003_upgrades_to_0004_and_deduplicates_issue_v2_deterministically(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config, engine = _migration_context(tmp_path, monkeypatch)
    command.upgrade(config, REVISION_0003)
    now = datetime.now(UTC).isoformat()

    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO data_sources "
                "(source_id, identifier, name, source_type, is_local, version, "
                "original_file, created_at) VALUES "
                "('source-legacy', 'local_csv', 'legacy.csv', 'LOCAL_CSV', 1, '1', "
                "'legacy.csv', :now)"
            ),
            {"now": now},
        )
        connection.execute(
            text(
                "INSERT INTO import_batches "
                "(batch_id, data_source_id, provider_name, source_name, source_file, "
                "source_file_hash, requested_at, status, row_count, accepted_count, "
                "rejected_count, warning_count, schema_version) VALUES "
                "('batch-legacy', 'source-legacy', 'local_csv', 'legacy.csv', "
                "'uploads/legacy.csv', :source_hash, :now, 'PREVIEW_READY', 1, 0, 1, 0, '1')"
            ),
            {"source_hash": "c" * 64, "now": now},
        )
        for issue_id, message in (
            ("issue-a", "最高价错误"),
            ("issue-b", "High price error"),
        ):
            connection.execute(
                text(
                    "INSERT INTO data_quality_issues "
                    "(issue_id, batch_id, row_number, symbol, field_name, severity, "
                    "issue_code, message, raw_value, issue_fingerprint, created_at) VALUES "
                    "(:issue_id, 'batch-legacy', 2, '600000', 'high', 'ERROR', "
                    "'HIGH_BELOW_LOW', :message, '9', :fingerprint, :now)"
                ),
                {
                    "issue_id": issue_id,
                    "message": message,
                    "fingerprint": issue_id.removeprefix("issue-") * 64,
                    "now": now,
                },
            )

    command.upgrade(config, "head")

    _assert_publication_schema(engine)
    with engine.connect() as connection:
        issues = connection.execute(
            text(
                "SELECT issue_id, issue_fingerprint_version, normalized_value "
                "FROM data_quality_issues ORDER BY issue_id"
            )
        ).mappings().all()
    assert issues == [
        {
            "issue_id": "issue-a",
            "issue_fingerprint_version": "quality-issue-sha256@2",
            "normalized_value": None,
        }
    ]
    engine.dispose()


def test_repeated_upgrade_to_head_is_idempotent(tmp_path: Path, monkeypatch) -> None:
    config, engine = _migration_context(tmp_path, monkeypatch)
    command.upgrade(config, "head")
    command.upgrade(config, "head")
    _assert_publication_schema(engine)
    engine.dispose()


def test_0004_downgrades_to_valid_0003_and_upgrades_again(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config, engine = _migration_context(tmp_path, monkeypatch)
    command.upgrade(config, "head")
    command.downgrade(config, REVISION_0003)

    inspector = inspect(engine)
    assert PUBLICATION_TABLES.isdisjoint(inspector.get_table_names())
    assert PREVIEW_COLUMNS.isdisjoint(_column_names(engine, "import_batches"))
    assert ISSUE_V2_COLUMNS.isdisjoint(_column_names(engine, "data_quality_issues"))
    assert ("batch_id", "issue_fingerprint") in _unique_column_sets(
        engine, "data_quality_issues"
    )
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one() == REVISION_0003

    command.upgrade(config, "head")
    _assert_publication_schema(engine)
    engine.dispose()


def test_downgrade_rejects_v1_issue_identity_collision_without_changing_0004(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config, engine = _migration_context(tmp_path, monkeypatch)
    command.upgrade(config, "head")
    now = datetime.now(UTC).isoformat()

    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO data_sources "
                "(source_id, identifier, name, source_type, is_local, version, "
                "original_file, created_at) VALUES "
                "('source-collision', 'local_csv', 'collision.csv', 'LOCAL_CSV', 1, '1', "
                "'collision.csv', :now)"
            ),
            {"now": now},
        )
        connection.execute(
            text(
                "INSERT INTO import_batches "
                "(batch_id, data_source_id, provider_name, source_name, source_file, "
                "source_file_hash, requested_at, status, row_count, accepted_count, "
                "rejected_count, warning_count, schema_version) VALUES "
                "('batch-collision', 'source-collision', 'local_csv', 'collision.csv', "
                "'uploads/collision.csv', :source_hash, :now, 'PREVIEW_READY', 2, 0, 2, 0, '1')"
            ),
            {"source_hash": "d" * 64, "now": now},
        )
        for issue_id, fingerprint, normalized_value in (
            ("issue-normalized-1", "1" * 64, '"1"'),
            ("issue-normalized-2", "2" * 64, '"2"'),
        ):
            connection.execute(
                text(
                    "INSERT INTO data_quality_issues "
                    "(issue_id, batch_id, row_number, symbol, field_name, severity, "
                    "issue_code, message, raw_value, issue_fingerprint, "
                    "issue_fingerprint_version, normalized_value, created_at) VALUES "
                    "(:issue_id, 'batch-collision', 2, '600000', 'high', 'ERROR', "
                    "'HIGH_BELOW_LOW', 'same message', '9', :fingerprint, "
                    "'quality-issue-sha256@2', :normalized_value, :now)"
                ),
                {
                    "issue_id": issue_id,
                    "fingerprint": fingerprint,
                    "normalized_value": normalized_value,
                    "now": now,
                },
            )

    with pytest.raises(
        RuntimeError,
        match="DOWNGRADE_0004_ISSUE_FINGERPRINT_V1_COLLISION",
    ):
        command.downgrade(config, REVISION_0003)

    _assert_publication_schema(engine)
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one() == REVISION_0004
        assert connection.execute(
            text(
                "SELECT count(*) FROM data_quality_issues "
                "WHERE batch_id = 'batch-collision'"
            )
        ).scalar_one() == 2
    engine.dispose()
