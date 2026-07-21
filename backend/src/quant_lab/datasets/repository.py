from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast
from uuid import uuid4

from sqlalchemy import Engine, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from quant_lab.datasets.errors import DatasetError
from quant_lab.datasets.persistence import DatasetModel, DatasetVersionModel

_LOGICAL_KEY_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._:-]{0,254}$")
_IDENTITY_FIELDS = (
    "logical_key",
    "dataset_type",
    "market",
    "frequency",
    "adjustment_type",
    "schema_version",
)


@dataclass(frozen=True, slots=True)
class DatasetIdentity:
    logical_key: str
    dataset_type: str
    market: str
    frequency: str
    adjustment_type: str
    schema_version: str


@dataclass(frozen=True, slots=True)
class DatasetCreateResult:
    dataset: DatasetModel
    created: bool


def _normalized_text(value: str, *, uppercase: bool = False) -> str:
    normalized = unicodedata.normalize("NFC", value).strip()
    return normalized.upper() if uppercase else normalized


def canonical_dataset_identity(identity: DatasetIdentity) -> dict[str, str]:
    logical_key = _normalized_text(identity.logical_key).lower()
    if not _LOGICAL_KEY_PATTERN.fullmatch(logical_key):
        raise DatasetError("INVALID_DATASET_IDENTITY", "数据集逻辑标识无效")

    canonical = {
        "logical_key": logical_key,
        "dataset_type": _normalized_text(identity.dataset_type, uppercase=True),
        "market": _normalized_text(identity.market, uppercase=True),
        "frequency": _normalized_text(identity.frequency, uppercase=True),
        "adjustment_type": _normalized_text(identity.adjustment_type, uppercase=True),
        "schema_version": _normalized_text(identity.schema_version),
    }
    if any(not canonical[field] for field in _IDENTITY_FIELDS):
        raise DatasetError("INVALID_DATASET_IDENTITY", "数据集身份字段不能为空")
    return canonical


def dataset_key_for(identity: DatasetIdentity) -> str:
    payload = json.dumps(
        canonical_dataset_identity(identity),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _utc_aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _restore_dataset_datetimes(dataset: DatasetModel) -> DatasetModel:
    dataset.created_at = cast(datetime, _utc_aware(dataset.created_at))
    dataset.updated_at = cast(datetime, _utc_aware(dataset.updated_at))
    return dataset


def _restore_version_datetimes(version: DatasetVersionModel) -> DatasetVersionModel:
    version.min_timestamp = _utc_aware(version.min_timestamp)
    version.max_timestamp = _utc_aware(version.max_timestamp)
    version.publication_claimed_at = cast(
        datetime,
        _utc_aware(version.publication_claimed_at),
    )
    version.published_at = _utc_aware(version.published_at)
    version.created_at = cast(datetime, _utc_aware(version.created_at))
    return version


class DatasetRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def create_or_get(
        self,
        identity: DatasetIdentity,
        *,
        name: str,
        description: str | None = None,
    ) -> DatasetCreateResult:
        canonical = canonical_dataset_identity(identity)
        dataset_key = dataset_key_for(identity)
        display_name = unicodedata.normalize("NFC", name).strip()
        if not display_name:
            raise DatasetError("INVALID_DATASET", "数据集名称不能为空")
        display_description = (
            unicodedata.normalize("NFC", description).strip() if description is not None else None
        )
        now = datetime.now(UTC)
        values = {
            "dataset_id": str(uuid4()),
            "dataset_key": dataset_key,
            **canonical,
            "name": display_name,
            "description": display_description or None,
            "created_at": now,
            "updated_at": now,
            "is_active": True,
        }
        with Session(self._engine, expire_on_commit=False) as session, session.begin():
            result = session.execute(
                sqlite_insert(DatasetModel)
                .values(**values)
                .on_conflict_do_nothing(index_elements=[DatasetModel.dataset_key])
            )
            dataset = session.scalars(
                select(DatasetModel).where(DatasetModel.dataset_key == dataset_key)
            ).one()
            if any(getattr(dataset, field) != canonical[field] for field in _IDENTITY_FIELDS):
                raise DatasetError(
                    "DATASET_IDENTITY_CONFLICT",
                    "数据集身份冲突, 请检查本地数据一致性",
                )
            created = cast(CursorResult[Any], result).rowcount == 1
            _restore_dataset_datetimes(dataset)
            session.expunge(dataset)
        return DatasetCreateResult(dataset=dataset, created=created)

    def list_datasets(self) -> tuple[DatasetModel, ...]:
        with Session(self._engine) as session:
            datasets = tuple(
                _restore_dataset_datetimes(dataset)
                for dataset in session.scalars(
                    select(DatasetModel).order_by(
                        DatasetModel.created_at,
                        DatasetModel.dataset_id,
                    )
                )
            )
            session.expunge_all()
        return datasets

    def list_versions(self, dataset_id: str) -> tuple[DatasetVersionModel, ...]:
        self._require_dataset(dataset_id)
        with Session(self._engine) as session:
            versions = tuple(
                _restore_version_datetimes(version)
                for version in session.scalars(
                    select(DatasetVersionModel)
                    .where(DatasetVersionModel.dataset_id == dataset_id)
                    .order_by(DatasetVersionModel.version)
                )
            )
            session.expunge_all()
        return versions

    def get_version(self, dataset_id: str, version_id: str) -> DatasetVersionModel:
        self._require_dataset(dataset_id)
        with Session(self._engine) as session:
            version = session.scalar(
                select(DatasetVersionModel).where(
                    DatasetVersionModel.dataset_id == dataset_id,
                    DatasetVersionModel.dataset_version_id == version_id,
                )
            )
            if version is None:
                raise DatasetError("DATASET_VERSION_NOT_FOUND", "数据集版本不存在")
            _restore_version_datetimes(version)
            session.expunge(version)
        return version

    def assert_identity_mutable(self, dataset_id: str) -> None:
        self._require_dataset(dataset_id)
        with Session(self._engine) as session:
            version_id = session.scalar(
                select(DatasetVersionModel.dataset_version_id)
                .where(DatasetVersionModel.dataset_id == dataset_id)
                .limit(1)
            )
        if version_id is not None:
            raise DatasetError("DATASET_IDENTITY_IMMUTABLE", "已有版本的数据集身份不可修改")

    def _require_dataset(self, dataset_id: str) -> None:
        with Session(self._engine) as session:
            exists = session.scalar(
                select(DatasetModel.dataset_id).where(DatasetModel.dataset_id == dataset_id)
            )
        if exists is None:
            raise DatasetError("DATASET_NOT_FOUND", "数据集不存在")
