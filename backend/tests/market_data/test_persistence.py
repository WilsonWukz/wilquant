import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import event, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from alembic import command
from quant_lab.core.config import Settings
from quant_lab.db.sqlite import create_sqlite_engine
from quant_lab.market_data.domain import (
    ImportBatchStatus,
    IssueSeverity,
    PreviewRecord,
    QualityIssue,
)
from quant_lab.market_data.errors import ImportDataError
from quant_lab.market_data.persistence import (
    DataQualityIssueModel,
    DataSourceModel,
    ImportBatchModel,
)
from quant_lab.market_data.repository import MarketDataRepository
from quant_lab.market_data.versions import (
    ISSUE_FINGERPRINT_VERSION,
    NORMALIZATION_RULES_VERSION,
    PREVIEW_FINGERPRINT_VERSION,
    QUALITY_RULES_VERSION,
    SCHEMA_VERSION,
)

REQUIRED_MAPPING = {
    field: field
    for field in (
        "symbol",
        "exchange",
        "trade_date",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "amount",
    )
}


def _canonical_mapping(mapping: dict[str, str]) -> str:
    return json.dumps(mapping, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _valid_preview_record(*, issues: tuple[QualityIssue, ...] = ()) -> PreviewRecord:
    return PreviewRecord(
        source_file_size=123,
        field_mapping_json=_canonical_mapping(REQUIRED_MAPPING),
        provider_version="local_csv@1",
        schema_version=SCHEMA_VERSION,
        normalization_version=NORMALIZATION_RULES_VERSION,
        quality_rules_version=QUALITY_RULES_VERSION,
        preview_fingerprint_version=PREVIEW_FINGERPRINT_VERSION,
        row_count=1,
        accepted_count=1,
        rejected_count=0,
        warning_count=0,
        preview_fingerprint="d" * 64,
        preview_completed_at=datetime.now(UTC),
        issues=issues,
    )


@pytest.mark.parametrize(
    "updates",
    [
        {"source_file_size": -1},
        {"row_count": -1},
        {"accepted_count": 0, "rejected_count": 0},
        {"accepted_count": 1, "warning_count": 2},
        {"preview_fingerprint": "not-a-sha256"},
        {"preview_fingerprint": "A" * 64},
        {"provider_version": " "},
        {"schema_version": ""},
        {"normalization_version": ""},
        {"quality_rules_version": ""},
        {"preview_fingerprint_version": ""},
        {"field_mapping_json": "[]"},
        {"field_mapping_json": '{"high": "high", "close": "close"}'},
        {"preview_completed_at": datetime.now()},
    ],
)
def test_preview_record_rejects_invalid_replay_metadata(updates: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        replace(_valid_preview_record(), **updates)


@pytest.mark.parametrize("missing_field", tuple(REQUIRED_MAPPING))
def test_preview_record_rejects_each_missing_required_mapping_field(
    missing_field: str,
) -> None:
    incomplete_mapping = dict(REQUIRED_MAPPING)
    del incomplete_mapping[missing_field]

    with pytest.raises(ValueError, match="required market-bar fields"):
        replace(
            _valid_preview_record(),
            field_mapping_json=_canonical_mapping(incomplete_mapping),
        )


def test_repository_revalidates_required_mapping_before_any_write(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("QUANT_LAB_PROJECT_ROOT", str(tmp_path))
    settings = Settings(project_root=tmp_path)
    command.upgrade(Config("backend/alembic.ini"), "head")
    engine = create_sqlite_engine(settings)
    now = datetime.now(UTC)
    with Session(engine) as session:
        source = DataSourceModel(
            source_id="source-invalid-mapping",
            identifier="local_csv",
            name="invalid-mapping.csv",
            source_type="LOCAL_CSV",
            is_local=True,
            version="1",
            original_file="invalid-mapping.csv",
            created_at=now,
        )
        batch = ImportBatchModel(
            batch_id="batch-invalid-mapping",
            data_source_id=source.source_id,
            provider_name="local_csv",
            source_name="invalid-mapping.csv",
            source_file="invalid-mapping.csv",
            source_file_hash="8" * 64,
            requested_at=now,
            status=ImportBatchStatus.PENDING.value,
            row_count=0,
            accepted_count=0,
            rejected_count=0,
            warning_count=0,
            schema_version="1",
        )
        session.add_all([source, batch])
        session.commit()

    incomplete_mapping = dict(REQUIRED_MAPPING)
    del incomplete_mapping["amount"]
    invalid_preview = _valid_preview_record()
    object.__setattr__(
        invalid_preview,
        "field_mapping_json",
        _canonical_mapping(incomplete_mapping),
    )
    repository = MarketDataRepository(engine)

    with pytest.raises(ValueError, match="required market-bar fields"):
        repository.complete_preview("batch-invalid-mapping", invalid_preview)

    unchanged = repository.get_batch("batch-invalid-mapping")
    assert unchanged.status == ImportBatchStatus.PENDING.value
    assert unchanged.field_mapping_json is None
    assert unchanged.preview_fingerprint is None
    assert repository.list_issues("batch-invalid-mapping") == ()
    engine.dispose()


def test_market_data_migration_creates_metadata_tables_only(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("QUANT_LAB_PROJECT_ROOT", str(tmp_path))
    settings = Settings(project_root=tmp_path)
    config = Config("backend/alembic.ini")

    command.upgrade(config, "head")
    command.upgrade(config, "head")

    engine = create_sqlite_engine(settings)
    tables = set(inspect(engine).get_table_names())
    assert {"instruments", "data_sources", "import_batches", "data_quality_issues"} <= tables
    assert not any("bar" in table for table in tables)
    engine.dispose()


def test_market_data_metadata_can_be_written(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("QUANT_LAB_PROJECT_ROOT", str(tmp_path))
    settings = Settings(project_root=tmp_path)
    command.upgrade(Config("backend/alembic.ini"), "head")
    engine = create_sqlite_engine(settings)
    now = datetime.now(UTC)

    with Session(engine) as session:
        source = DataSourceModel(
            source_id="source-1",
            identifier="local_csv",
            name="bars.csv",
            source_type="LOCAL_CSV",
            is_local=True,
            version="1",
            original_file="bars.csv",
            created_at=now,
        )
        batch = ImportBatchModel(
            batch_id="batch-1",
            data_source_id=source.source_id,
            provider_name="local_csv",
            source_name="bars.csv",
            source_file="abc.csv",
            source_file_hash="a" * 64,
            requested_at=now,
            status=ImportBatchStatus.PENDING.value,
            row_count=0,
            accepted_count=0,
            rejected_count=0,
            warning_count=0,
            schema_version="1",
        )
        session.add_all([source, batch])
        session.commit()

        assert session.get(ImportBatchModel, "batch-1") is not None
    engine.dispose()


def test_repeated_preview_replaces_quality_issues_transactionally(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("QUANT_LAB_PROJECT_ROOT", str(tmp_path))
    settings = Settings(project_root=tmp_path)
    command.upgrade(Config("backend/alembic.ini"), "head")
    engine = create_sqlite_engine(settings)
    now = datetime.now(UTC)

    with Session(engine) as session:
        source = DataSourceModel(
            source_id="source-repeat",
            identifier="local_csv",
            name="repeat.csv",
            source_type="LOCAL_CSV",
            is_local=True,
            version="1",
            original_file="repeat.csv",
            created_at=now,
        )
        batch = ImportBatchModel(
            batch_id="batch-repeat",
            data_source_id=source.source_id,
            provider_name="local_csv",
            source_name="repeat.csv",
            source_file="repeat.csv",
            source_file_hash="b" * 64,
            requested_at=now,
            status=ImportBatchStatus.PENDING.value,
            row_count=1,
            accepted_count=0,
            rejected_count=0,
            warning_count=0,
            schema_version="1",
        )
        session.add_all([source, batch])
        session.commit()

    repository = MarketDataRepository(engine)
    issue = QualityIssue(
        row_number=2,
        symbol="600000",
        field_name="high",
        severity=IssueSeverity.ERROR,
        issue_code="HIGH_BELOW_LOW",
        message="最高价不得低于最低价",
        raw_value="9",
        normalized_value="9.00000000",
    )
    completed_at = datetime.now(UTC)
    preview = PreviewRecord(
        source_file_size=123,
        field_mapping_json=_canonical_mapping(REQUIRED_MAPPING),
        provider_version="local_csv@1",
        schema_version=SCHEMA_VERSION,
        normalization_version=NORMALIZATION_RULES_VERSION,
        quality_rules_version=QUALITY_RULES_VERSION,
        preview_fingerprint_version=PREVIEW_FINGERPRINT_VERSION,
        row_count=1,
        accepted_count=0,
        rejected_count=1,
        warning_count=0,
        preview_fingerprint="d" * 64,
        preview_completed_at=completed_at,
        issues=(issue,),
    )
    for _ in range(2):
        updated = repository.complete_preview("batch-repeat", preview)

    assert updated.accepted_count == 0
    assert updated.rejected_count == 1
    assert updated.warning_count == 0
    assert updated.source_file_size == 123
    assert updated.field_mapping_json == _canonical_mapping(REQUIRED_MAPPING)
    assert updated.provider_version == "local_csv@1"
    assert updated.schema_version == SCHEMA_VERSION
    assert updated.normalization_version == NORMALIZATION_RULES_VERSION
    assert updated.quality_rules_version == QUALITY_RULES_VERSION
    assert updated.preview_fingerprint_version == PREVIEW_FINGERPRINT_VERSION
    assert updated.preview_fingerprint == "d" * 64
    assert updated.preview_completed_at == completed_at
    assert len(repository.list_issues("batch-repeat")) == 1
    persisted_issue = repository.list_issues("batch-repeat")[0]
    assert persisted_issue.issue_fingerprint_version == ISSUE_FINGERPRINT_VERSION
    assert persisted_issue.normalized_value == '"9.00000000"'
    engine.dispose()


def test_complete_preview_rolls_back_metadata_and_issues_together(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("QUANT_LAB_PROJECT_ROOT", str(tmp_path))
    settings = Settings(project_root=tmp_path)
    command.upgrade(Config("backend/alembic.ini"), "head")
    engine = create_sqlite_engine(settings)
    now = datetime.now(UTC)

    with Session(engine) as session:
        source = DataSourceModel(
            source_id="source-rollback",
            identifier="local_csv",
            name="rollback.csv",
            source_type="LOCAL_CSV",
            is_local=True,
            version="1",
            original_file="rollback.csv",
            created_at=now,
        )
        batch = ImportBatchModel(
            batch_id="batch-rollback",
            data_source_id=source.source_id,
            provider_name="local_csv",
            source_name="rollback.csv",
            source_file="rollback.csv",
            source_file_hash="e" * 64,
            requested_at=now,
            status=ImportBatchStatus.PENDING.value,
            row_count=0,
            accepted_count=0,
            rejected_count=0,
            warning_count=0,
            schema_version="1",
        )
        session.add_all([source, batch])
        session.commit()

    repository = MarketDataRepository(engine)
    issue = QualityIssue(
        row_number=2,
        symbol="600000",
        field_name="high",
        severity=IssueSeverity.ERROR,
        issue_code="HIGH_BELOW_LOW",
        message="localized message",
        raw_value="9",
        normalized_value="9.00000000",
    )
    completed_at = datetime.now(UTC)
    preview = PreviewRecord(
        source_file_size=456,
        field_mapping_json=_canonical_mapping(REQUIRED_MAPPING),
        provider_version="local_csv@1",
        schema_version=SCHEMA_VERSION,
        normalization_version=NORMALIZATION_RULES_VERSION,
        quality_rules_version=QUALITY_RULES_VERSION,
        preview_fingerprint_version=PREVIEW_FINGERPRINT_VERSION,
        row_count=1,
        accepted_count=0,
        rejected_count=1,
        warning_count=0,
        preview_fingerprint="f" * 64,
        preview_completed_at=completed_at,
        issues=(issue,),
    )

    def fail_issue_insert(*_args, **_kwargs) -> None:
        raise RuntimeError("forced issue insertion failure")

    event.listen(DataQualityIssueModel, "before_insert", fail_issue_insert)
    try:
        with pytest.raises(RuntimeError, match="forced issue insertion failure"):
            repository.complete_preview("batch-rollback", preview)
    finally:
        event.remove(DataQualityIssueModel, "before_insert", fail_issue_insert)

    unchanged = repository.get_batch("batch-rollback")
    assert unchanged.status == ImportBatchStatus.PENDING.value
    assert unchanged.row_count == 0
    assert unchanged.accepted_count == 0
    assert unchanged.rejected_count == 0
    assert unchanged.warning_count == 0
    assert unchanged.source_file_size is None
    assert unchanged.field_mapping_json is None
    assert unchanged.provider_version is None
    assert unchanged.schema_version == "1"
    assert unchanged.normalization_version is None
    assert unchanged.quality_rules_version is None
    assert unchanged.preview_fingerprint_version is None
    assert unchanged.preview_fingerprint is None
    assert unchanged.preview_completed_at is None
    assert repository.list_issues("batch-rollback") == ()
    engine.dispose()


@pytest.mark.parametrize(
    "blocked_status",
    ("PARSING", "VALIDATING", "CANCELLED", "PUBLISHING", "PUBLISHED", "PUBLISH_FAILED"),
)
def test_complete_preview_atomically_rejects_non_previewable_states(
    tmp_path: Path,
    monkeypatch,
    blocked_status: str,
) -> None:
    monkeypatch.setenv("QUANT_LAB_PROJECT_ROOT", str(tmp_path))
    settings = Settings(project_root=tmp_path)
    command.upgrade(Config("backend/alembic.ini"), "head")
    engine = create_sqlite_engine(settings)
    now = datetime.now(UTC)
    with Session(engine) as session:
        source = DataSourceModel(
            source_id="source-state",
            identifier="local_csv",
            name="state.csv",
            source_type="LOCAL_CSV",
            is_local=True,
            version="1",
            original_file="state.csv",
            created_at=now,
        )
        batch = ImportBatchModel(
            batch_id="batch-state",
            data_source_id=source.source_id,
            provider_name="local_csv",
            source_name="state.csv",
            source_file="state.csv",
            source_file_hash="9" * 64,
            requested_at=now,
            status=ImportBatchStatus.PENDING.value,
            row_count=0,
            accepted_count=0,
            rejected_count=0,
            warning_count=0,
            schema_version="1",
        )
        session.add_all([source, batch])
        session.commit()

    original_issue = QualityIssue(
        row_number=2,
        symbol="600000",
        field_name="high",
        severity=IssueSeverity.WARNING,
        issue_code="ORIGINAL_WARNING",
        message="original",
        raw_value="10",
        normalized_value="10.00000000",
    )
    repository = MarketDataRepository(engine)
    original_preview = _valid_preview_record(issues=(original_issue,))
    repository.complete_preview("batch-state", original_preview)
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE import_batches SET status = :status WHERE batch_id = 'batch-state'"),
            {"status": blocked_status},
        )
    before = repository.get_batch("batch-state")
    before_issue_hashes = tuple(
        issue.issue_fingerprint for issue in repository.list_issues("batch-state")
    )
    replacement_issue = replace(
        original_issue,
        issue_code="REPLACEMENT_ERROR",
        severity=IssueSeverity.ERROR,
    )
    replacement_preview = replace(
        original_preview,
        source_file_size=999,
        preview_fingerprint="1" * 64,
        preview_completed_at=datetime.now(UTC),
        issues=(replacement_issue,),
    )

    with pytest.raises(ImportDataError) as captured:
        repository.complete_preview("batch-state", replacement_preview)

    assert captured.value.category == "PREVIEW_STATE_INVALID"
    after = repository.get_batch("batch-state")
    assert after.status == blocked_status
    assert after.source_file_size == before.source_file_size
    assert after.field_mapping_json == before.field_mapping_json
    assert after.provider_version == before.provider_version
    assert after.schema_version == before.schema_version
    assert after.normalization_version == before.normalization_version
    assert after.quality_rules_version == before.quality_rules_version
    assert after.preview_fingerprint_version == before.preview_fingerprint_version
    assert after.preview_fingerprint == before.preview_fingerprint
    assert after.preview_completed_at == before.preview_completed_at
    assert tuple(
        issue.issue_fingerprint for issue in repository.list_issues("batch-state")
    ) == before_issue_hashes
    engine.dispose()


def test_revision_0003_deduplicates_legacy_issues_and_enforces_identity(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("QUANT_LAB_PROJECT_ROOT", str(tmp_path))
    settings = Settings(project_root=tmp_path)
    config = Config("backend/alembic.ini")
    command.upgrade(config, "20260720_0002")
    engine = create_sqlite_engine(settings)
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
                "'legacy.csv', :source_hash, :now, 'PREVIEW_READY', 1, 0, 1, 0, '1')"
            ),
            {"source_hash": "c" * 64, "now": now},
        )
        for issue_id in ("issue-legacy-1", "issue-legacy-2"):
            connection.execute(
                text(
                    "INSERT INTO data_quality_issues "
                    "(issue_id, batch_id, row_number, symbol, field_name, severity, "
                    "issue_code, message, raw_value, created_at) VALUES "
                    "(:issue_id, 'batch-legacy', 2, '600000', 'high', 'ERROR', "
                    "'HIGH_BELOW_LOW', '最高价不得低于最低价', '9', :now)"
                ),
                {"issue_id": issue_id, "now": now},
            )

    command.upgrade(config, "head")

    columns = {item["name"] for item in inspect(engine).get_columns("data_quality_issues")}
    with engine.connect() as connection:
        persisted = connection.execute(
            text(
                "SELECT issue_id, issue_fingerprint FROM data_quality_issues "
                "WHERE batch_id = 'batch-legacy'"
            )
        ).all()
    assert "issue_fingerprint" in columns
    assert len(persisted) == 1
    assert len(persisted[0].issue_fingerprint) == 64

    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO data_quality_issues "
                "(issue_id, batch_id, row_number, symbol, field_name, severity, "
                "issue_code, message, raw_value, issue_fingerprint, created_at) "
                "SELECT 'issue-legacy-copy', batch_id, row_number, symbol, field_name, "
                "severity, issue_code, message, raw_value, issue_fingerprint, created_at "
                "FROM data_quality_issues WHERE issue_id = :issue_id"
            ),
            {"issue_id": persisted[0].issue_id},
        )
    engine.dispose()
