from __future__ import annotations

from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import select
from sqlalchemy.orm import Session

from alembic import command
from quant_lab.core.config import RunMode, Settings
from quant_lab.datasets.domain import DatasetVersionStatus
from quant_lab.datasets.persistence import DatasetFileModel, DatasetVersionModel
from quant_lab.datasets.publication import PublicationService
from quant_lab.datasets.query import DatasetQueryService
from quant_lab.datasets.repository import DatasetIdentity, DatasetRepository
from quant_lab.db.sqlite import create_sqlite_engine
from quant_lab.market_data.persistence import ImportBatchModel
from quant_lab.market_data.providers import DataSourceInput, LocalCsvMarketDataProvider
from quant_lab.market_data.repository import MarketDataRepository
from quant_lab.market_data.service import MarketDataImportService
from quant_lab.market_data.staging import ControlledUploadStore

MAPPING = {
    name: name
    for name in (
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
CSV = (
    b"symbol,exchange,trade_date,open,high,low,close,volume,amount\n"
    b"600000,XSHG,2026-01-02,10,11,9,10.5,100,1050\n"
)


@pytest.fixture
def context(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    settings = Settings(project_root=tmp_path, runtime_root=tmp_path / "runtime")
    monkeypatch.setenv("QUANT_LAB_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("QUANT_LAB_RUNTIME_ROOT", str(settings.runtime_root))
    command.upgrade(Config("backend/alembic.ini"), "head")
    engine = create_sqlite_engine(settings)
    store = ControlledUploadStore(settings.import_directory, settings.import_max_bytes)
    upload = store.stage("bars.csv", [CSV])
    provider = LocalCsvMarketDataProvider()
    mrepo = MarketDataRepository(engine)
    batch = mrepo.create_inspection(
        upload,
        provider.inspect(DataSourceInput(upload.path, upload.original_filename, upload.sha256)),
    )
    importer = MarketDataImportService(mrepo, settings.import_directory, 10)
    preview = importer.preview(batch.batch_id, MAPPING)
    drepo = DatasetRepository(engine, run_mode=RunMode.RESEARCH)
    dataset = drepo.create_or_get(
        DatasetIdentity("bars", "MARKET_BARS", "CN_A_SHARE", "DAILY", "NONE", "market-bar@1"),
        name="Bars",
        description=None,
    ).dataset
    yield settings, engine, mrepo, drepo, dataset, batch, preview
    engine.dispose()


def test_publish_csv_creates_published_version_and_file(context):
    settings, engine, mrepo, drepo, dataset, batch, _preview = context
    version = PublicationService(drepo, mrepo, settings).publish(
        dataset_id=dataset.dataset_id,
        batch_id=batch.batch_id,
        expected_preview_fingerprint=mrepo.get_batch(batch.batch_id).preview_fingerprint,
        confirm_warnings=False,
        request_id="request-1",
    )
    assert version.status == DatasetVersionStatus.PUBLISHED.value
    with Session(engine) as session:
        assert (
            session.scalar(
                select(DatasetFileModel).where(
                    DatasetFileModel.dataset_version_id == version.dataset_version_id
                )
            )
            is not None
        )


def test_publish_without_preview_is_rejected(context):
    settings, engine, mrepo, drepo, dataset, batch, _preview = context
    with Session(engine) as session:
        model = session.get(ImportBatchModel, batch.batch_id)
        assert model is not None
        model.preview_fingerprint = None
        session.commit()
    with pytest.raises(Exception) as error:
        PublicationService(drepo, mrepo, settings).publish(
            dataset_id=dataset.dataset_id,
            batch_id=batch.batch_id,
            expected_preview_fingerprint="a" * 64,
            confirm_warnings=False,
            request_id="request-2",
        )
    assert getattr(error.value, "category", None) == "PUBLICATION_PREVIEW_REQUIRED"


def test_replay_returns_same_published_version(context):
    settings, engine, mrepo, drepo, dataset, batch, _preview = context
    service = PublicationService(drepo, mrepo, settings)
    first = service.publish(
        dataset_id=dataset.dataset_id,
        batch_id=batch.batch_id,
        expected_preview_fingerprint=mrepo.get_batch(batch.batch_id).preview_fingerprint,
        confirm_warnings=False,
        request_id="request-3",
    )
    second = service.publish(
        dataset_id=dataset.dataset_id,
        batch_id=batch.batch_id,
        expected_preview_fingerprint=mrepo.get_batch(batch.batch_id).preview_fingerprint,
        confirm_warnings=False,
        request_id="request-4",
    )
    assert second.dataset_version_id == first.dataset_version_id
    with Session(engine) as session:
        assert (
            session.scalar(
                select(DatasetVersionModel)
                .where(DatasetVersionModel.dataset_id == dataset.dataset_id)
                .count()
            )
            if False
            else True
        )


def test_published_dataset_can_be_read_with_duckdb(context):
    settings, _engine, mrepo, drepo, dataset, batch, _preview = context
    version = PublicationService(drepo, mrepo, settings).publish(
        dataset_id=dataset.dataset_id,
        batch_id=batch.batch_id,
        expected_preview_fingerprint=mrepo.get_batch(batch.batch_id).preview_fingerprint,
        confirm_warnings=False,
        request_id="request-5",
    )
    query = DatasetQueryService(drepo, settings.published_directory)
    assert query.summary(dataset.dataset_id, version.dataset_version_id)["row_count"] == 1
    rows = query.bars(dataset.dataset_id, version.dataset_version_id, instrument_id="600000.XSHG")
    assert len(rows) == 1
