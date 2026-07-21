from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import Engine, delete, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from alembic import command
from quant_lab.core.config import Settings
from quant_lab.datasets.domain import DatasetVersionStatus
from quant_lab.datasets.persistence import DatasetFileModel, DatasetModel, DatasetVersionModel
from quant_lab.db.sqlite import create_sqlite_engine
from quant_lab.market_data.persistence import DataSourceModel, ImportBatchModel


def _migrated_engine(tmp_path: Path, monkeypatch) -> Engine:
    monkeypatch.setenv("QUANT_LAB_PROJECT_ROOT", str(tmp_path))
    settings = Settings(project_root=tmp_path)
    command.upgrade(Config("backend/alembic.ini"), "head")
    return create_sqlite_engine(settings)


def _seed_version(engine: Engine, *, status: DatasetVersionStatus) -> None:
    now = datetime.now(UTC)
    initial_status = (
        DatasetVersionStatus.FILES_COMMITTED
        if status is DatasetVersionStatus.PUBLISHED
        else status
    )
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
            source_file="uploads/bars.csv",
            source_file_hash="a" * 64,
            requested_at=now,
            status="PUBLISHING",
            row_count=1,
            accepted_count=1,
            rejected_count=0,
            warning_count=0,
            schema_version="market-bar@1",
        )
        dataset = DatasetModel(
            dataset_id="dataset-1",
            dataset_key="b" * 64,
            logical_key="research-daily-bars",
            name="研究日线",
            description=None,
            dataset_type="MARKET_BARS",
            market="A_SHARE",
            frequency="DAILY",
            adjustment_type="NONE",
            schema_version="market-bar@1",
            created_at=now,
            updated_at=now,
            is_active=True,
        )
        version = DatasetVersionModel(
            dataset_version_id="version-1",
            dataset_id=dataset.dataset_id,
            version=1,
            status=initial_status.value,
            source_batch_id=batch.batch_id,
            source_preview_fingerprint="c" * 64,
            publication_fingerprint="d" * 64,
            schema_version="market-bar@1",
            normalization_version="a-share-normalization@1",
            quality_rules_version="a-share-quality@1",
            publication_format_version="parquet-market-bars@1",
            partition_strategy_version="daily-exchange-year@1",
            row_count=1,
            instrument_count=1,
            partition_count=1,
            file_count=1,
            total_size_bytes=128,
            quality_issue_count=0,
            warning_count=0,
            blocking_issue_count=0,
            quality_summary_json="{}",
            relative_version_root="market_bars/dataset=dataset-1/version=000001",
            manifest_path="manifest.json",
            manifest_sha256="e" * 64,
            publication_claimed_at=now,
            created_at=now,
        )
        dataset_file = DatasetFileModel(
            dataset_file_id="file-1",
            dataset_version_id=version.dataset_version_id,
            relative_path="frequency=DAILY/exchange=XSHG/year=2026/part-00000.parquet",
            partition_values_json='{"exchange":"XSHG","frequency":"DAILY","year":2026}',
            row_count=1,
            size_bytes=128,
            sha256="f" * 64,
            min_timestamp=now,
            max_timestamp=now,
            created_at=now,
        )
        session.add_all([source, dataset])
        session.flush()
        session.add(batch)
        session.flush()
        session.add(version)
        session.flush()
        session.add(dataset_file)
        session.commit()

    if status is DatasetVersionStatus.PUBLISHED:
        with engine.begin() as connection:
            connection.execute(
                update(DatasetVersionModel)
                .where(DatasetVersionModel.dataset_version_id == "version-1")
                .values(status=status.value, published_at=now)
            )


def test_files_committed_version_can_transition_to_published(
    tmp_path: Path,
    monkeypatch,
) -> None:
    engine = _migrated_engine(tmp_path, monkeypatch)
    _seed_version(engine, status=DatasetVersionStatus.FILES_COMMITTED)
    published_at = datetime.now(UTC)

    with engine.begin() as connection:
        connection.execute(
            update(DatasetVersionModel)
            .where(DatasetVersionModel.dataset_version_id == "version-1")
            .values(status=DatasetVersionStatus.PUBLISHED.value, published_at=published_at)
        )

    with Session(engine) as session:
        persisted = session.get(DatasetVersionModel, "version-1")
        assert persisted is not None
        assert persisted.status == DatasetVersionStatus.PUBLISHED.value
        assert persisted.published_at is not None
    engine.dispose()


@pytest.mark.parametrize(
    "status",
    [
        DatasetVersionStatus.VALIDATING,
        DatasetVersionStatus.STAGING,
        DatasetVersionStatus.FILES_COMMITTING,
        DatasetVersionStatus.FILES_COMMITTED,
    ],
)
def test_non_published_version_allows_file_insert(
    tmp_path: Path,
    monkeypatch,
    status: DatasetVersionStatus,
) -> None:
    engine = _migrated_engine(tmp_path, monkeypatch)
    _seed_version(engine, status=status)

    with engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM dataset_files")).scalar_one() == 1
    engine.dispose()


def test_published_version_rejects_update_and_delete(tmp_path: Path, monkeypatch) -> None:
    engine = _migrated_engine(tmp_path, monkeypatch)
    _seed_version(engine, status=DatasetVersionStatus.PUBLISHED)

    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(
            update(DatasetVersionModel)
            .where(DatasetVersionModel.dataset_version_id == "version-1")
            .values(failure_reason="must remain immutable")
        )
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(
            delete(DatasetVersionModel).where(
                DatasetVersionModel.dataset_version_id == "version-1"
            )
        )
    engine.dispose()


def test_files_of_published_version_reject_update_and_delete(
    tmp_path: Path,
    monkeypatch,
) -> None:
    engine = _migrated_engine(tmp_path, monkeypatch)
    _seed_version(engine, status=DatasetVersionStatus.PUBLISHED)

    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(
            update(DatasetFileModel)
            .where(DatasetFileModel.dataset_file_id == "file-1")
            .values(relative_path="changed.parquet")
        )
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(
            delete(DatasetFileModel).where(DatasetFileModel.dataset_file_id == "file-1")
        )
    engine.dispose()


def test_published_version_rejects_new_file(tmp_path: Path, monkeypatch) -> None:
    engine = _migrated_engine(tmp_path, monkeypatch)
    _seed_version(engine, status=DatasetVersionStatus.PUBLISHED)
    now = datetime.now(UTC).isoformat()

    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO dataset_files "
                "(dataset_file_id, dataset_version_id, relative_path, partition_values_json, "
                "row_count, size_bytes, sha256, min_timestamp, max_timestamp, created_at) "
                "VALUES ('file-2', 'version-1', 'second.parquet', '{}', 1, 64, :sha256, "
                ":now, :now, :now)"
            ),
            {"sha256": "0" * 64, "now": now},
        )
    engine.dispose()


def test_parent_deletion_is_restricted_not_cascaded(tmp_path: Path, monkeypatch) -> None:
    engine = _migrated_engine(tmp_path, monkeypatch)
    _seed_version(engine, status=DatasetVersionStatus.FILES_COMMITTED)

    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(text("DELETE FROM datasets WHERE dataset_id = 'dataset-1'"))
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(text("DELETE FROM import_batches WHERE batch_id = 'batch-1'"))
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(
            text("DELETE FROM dataset_versions WHERE dataset_version_id = 'version-1'")
        )

    with engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM datasets")).scalar_one() == 1
        assert connection.execute(text("SELECT count(*) FROM dataset_versions")).scalar_one() == 1
        assert connection.execute(text("SELECT count(*) FROM dataset_files")).scalar_one() == 1
    engine.dispose()
