from __future__ import annotations

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from threading import Barrier

import pytest
from alembic.config import Config
from sqlalchemy import Engine
from sqlalchemy.orm import Session

import quant_lab.datasets.repository as repository_module
from alembic import command
from quant_lab.core.config import RunMode, Settings
from quant_lab.datasets.errors import DatasetError
from quant_lab.datasets.persistence import DatasetVersionModel
from quant_lab.datasets.repository import (
    DatasetIdentity,
    DatasetRepository,
    canonical_dataset_identity,
    dataset_key_for,
)
from quant_lab.db.sqlite import create_sqlite_engine
from quant_lab.market_data.persistence import DataSourceModel, ImportBatchModel


def identity(**overrides: str) -> DatasetIdentity:
    values = {
        "logical_key": "cn-a-share-daily-bars",
        "dataset_type": "MARKET_BARS",
        "market": "CN_A_SHARE",
        "frequency": "DAILY",
        "adjustment_type": "NONE",
        "schema_version": "market-bar@1",
    }
    values.update(overrides)
    return DatasetIdentity(**values)


@pytest.fixture
def engine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Engine]:
    settings = Settings(project_root=tmp_path, runtime_root=tmp_path / "runtime")
    monkeypatch.setenv("QUANT_LAB_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("QUANT_LAB_RUNTIME_ROOT", str(settings.runtime_root))
    command.upgrade(Config("backend/alembic.ini"), "head")
    database_engine = create_sqlite_engine(settings)
    yield database_engine
    database_engine.dispose()


@pytest.fixture
def repository(engine: Engine) -> DatasetRepository:
    return DatasetRepository(engine, run_mode=RunMode.RESEARCH)


def insert_dataset_version(engine: Engine, dataset_id: str) -> str:
    now = datetime(2026, 7, 21, 8, 30, tzinfo=UTC)
    source_id = "source-for-dataset-version"
    batch_id = "batch-for-dataset-version"
    version_id = "version-for-dataset"
    with Session(engine) as session, session.begin():
        session.add(
            DataSourceModel(
                source_id=source_id,
                identifier="dataset-version-source",
                name="Dataset version source",
                source_type="LOCAL_FILE",
                is_local=True,
                version="1",
                original_file="controlled-upload.csv",
                created_at=now,
            )
        )
        session.flush()
        session.add(
            ImportBatchModel(
                batch_id=batch_id,
                data_source_id=source_id,
                provider_name="local_csv",
                source_name="controlled-upload.csv",
                source_file="controlled-upload.csv",
                source_file_hash="a" * 64,
                requested_at=now,
                started_at=now,
                completed_at=now,
                status="PREVIEW_READY",
                row_count=1,
                accepted_count=1,
                rejected_count=0,
                warning_count=0,
                schema_version="market-bar@1",
            )
        )
        session.flush()
        session.add(
            DatasetVersionModel(
                dataset_version_id=version_id,
                dataset_id=dataset_id,
                version=1,
                status="VALIDATING",
                source_batch_id=batch_id,
                source_preview_fingerprint="b" * 64,
                publication_fingerprint="c" * 64,
                schema_version="market-bar@1",
                normalization_version="normalization@1",
                quality_rules_version="quality@1",
                publication_format_version="parquet@1",
                partition_strategy_version="market-bars@1",
                row_count=0,
                instrument_count=0,
                min_timestamp=now,
                max_timestamp=now,
                partition_count=0,
                file_count=0,
                total_size_bytes=0,
                quality_issue_count=0,
                warning_count=0,
                blocking_issue_count=0,
                publication_claimed_at=now,
                published_at=now,
                created_at=now,
            )
        )
    return version_id


def test_same_logical_identity_returns_existing_dataset(
    repository: DatasetRepository,
) -> None:
    first = repository.create_or_get(
        identity(),
        name="A股日线",
        description="首次展示文本",
    )
    second = repository.create_or_get(
        identity(),
        name="Renamed display label",
        description="Changed display description",
    )

    assert first.created is True
    assert second.created is False
    assert second.dataset.dataset_id == first.dataset.dataset_id
    assert second.dataset.dataset_key == first.dataset.dataset_key
    assert second.dataset.name == "A股日线"
    assert second.dataset.description == "首次展示文本"


@pytest.mark.parametrize(
    ("field", "changed"),
    [
        ("logical_key", "cn-a-share-weekly-bars"),
        ("dataset_type", "FUNDAMENTALS"),
        ("market", "HK_EQUITY"),
        ("frequency", "WEEKLY"),
        ("adjustment_type", "FORWARD"),
        ("schema_version", "market-bar@2"),
    ],
)
def test_each_immutable_identity_field_changes_dataset_key(
    field: str,
    changed: str,
) -> None:
    assert dataset_key_for(identity()) != dataset_key_for(identity(**{field: changed}))


def test_dataset_key_excludes_display_fields_and_has_stable_canonical_form() -> None:
    canonical = canonical_dataset_identity(identity())

    assert canonical == canonical_dataset_identity(
        identity(
            logical_key="  CN-A-SHARE-DAILY-BARS  ",
            dataset_type=" market_bars ",
            market=" cn_a_share ",
            frequency=" daily ",
            adjustment_type=" none ",
            schema_version=" market-bar@1 ",
        )
    )
    assert dataset_key_for(identity()) == dataset_key_for(identity())
    assert len(dataset_key_for(identity())) == 64


@pytest.mark.parametrize(
    "logical_key",
    ["", "   ", "../bars", "bars/daily", r"C:\bars", ".hidden", "bars?daily"],
)
def test_rejects_empty_or_unsafe_logical_key(logical_key: str) -> None:
    with pytest.raises(DatasetError) as raised:
        dataset_key_for(identity(logical_key=logical_key))

    assert raised.value.category == "INVALID_DATASET_IDENTITY"
    assert raised.value.safe_message
    if logical_key.strip():
        assert logical_key not in raised.value.safe_message


def test_concurrent_create_or_get_returns_one_dataset(
    repository: DatasetRepository,
) -> None:
    workers = 6
    barrier = Barrier(workers)

    def create(index: int) -> tuple[str, bool]:
        barrier.wait()
        result = repository.create_or_get(
            identity(),
            name=f"display-{index}",
            description=f"description-{index}",
        )
        return result.dataset.dataset_id, result.created

    with ThreadPoolExecutor(max_workers=workers) as executor:
        results = list(executor.map(create, range(workers)))

    assert len({dataset_id for dataset_id, _created in results}) == 1
    assert sum(created for _dataset_id, created in results) == 1
    assert len(repository.list_datasets()) == 1


def test_identity_guard_rejects_changes_after_a_version_exists(
    repository: DatasetRepository,
    engine: Engine,
) -> None:
    dataset = repository.create_or_get(identity(), name="A股日线").dataset
    insert_dataset_version(engine, dataset.dataset_id)

    with pytest.raises(DatasetError) as raised:
        repository.assert_identity_mutable(dataset.dataset_id)

    assert raised.value.category == "DATASET_IDENTITY_IMMUTABLE"
    assert raised.value.safe_message == "已有版本的数据集身份不可修改"


def test_sqlite_datetimes_are_restored_as_utc_aware(
    repository: DatasetRepository,
    engine: Engine,
) -> None:
    created = repository.create_or_get(identity(), name="A股日线").dataset
    version_id = insert_dataset_version(engine, created.dataset_id)

    listed_dataset = repository.list_datasets()[0]
    listed_version = repository.list_versions(created.dataset_id)[0]
    fetched_version = repository.get_version(created.dataset_id, version_id)

    assert created.created_at.tzinfo is UTC
    assert created.updated_at.tzinfo is UTC
    assert listed_dataset.created_at.tzinfo is UTC
    assert listed_dataset.updated_at.tzinfo is UTC
    for version in (listed_version, fetched_version):
        assert version.publication_claimed_at.tzinfo is UTC
        assert version.created_at.tzinfo is UTC
        assert version.min_timestamp is not None and version.min_timestamp.tzinfo is UTC
        assert version.max_timestamp is not None and version.max_timestamp.tzinfo is UTC
        assert version.published_at is not None and version.published_at.tzinfo is UTC


def test_dataset_key_conflict_never_returns_a_different_identity(
    repository: DatasetRepository,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    existing = repository.create_or_get(identity(), name="A股日线").dataset
    monkeypatch.setattr(
        repository_module,
        "dataset_key_for",
        lambda _identity: existing.dataset_key,
    )

    with pytest.raises(DatasetError) as raised:
        repository.create_or_get(
            identity(market="HK_EQUITY"),
            name="different identity",
        )

    assert raised.value.category == "DATASET_IDENTITY_CONFLICT"
    assert raised.value.safe_message == "数据集身份冲突, 请检查本地数据一致性"
    assert "HK_EQUITY" not in raised.value.safe_message
