from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest
from alembic.config import Config

from alembic import command
from quant_lab.core.config import Settings
from quant_lab.datasets.errors import DatasetError
from quant_lab.datasets.repository import (
    DatasetIdentity,
    DatasetRepository,
    canonical_dataset_identity,
    dataset_key_for,
)
from quant_lab.db.sqlite import create_sqlite_engine


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
def repository(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> DatasetRepository:
    settings = Settings(project_root=tmp_path, runtime_root=tmp_path / "runtime")
    monkeypatch.setenv("QUANT_LAB_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("QUANT_LAB_RUNTIME_ROOT", str(settings.runtime_root))
    command.upgrade(Config("backend/alembic.ini"), "head")
    engine = create_sqlite_engine(settings)
    yield DatasetRepository(engine)
    engine.dispose()


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
) -> None:
    dataset = repository.create_or_get(identity(), name="A股日线").dataset

    repository.assert_identity_mutable(dataset.dataset_id)
