from __future__ import annotations

import hashlib
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from threading import Barrier

import pytest
from alembic.config import Config
from sqlalchemy import Engine, func, select, text
from sqlalchemy.orm import Session

from alembic import command
from quant_lab.core.config import RunMode, Settings
from quant_lab.datasets.errors import DatasetError
from quant_lab.datasets.persistence import (
    DatasetVersionModel,
    PublicationAuditModel,
)
from quant_lab.datasets.repository import (
    DatasetIdentity,
    DatasetRepository,
    PublicationConfig,
    publication_fingerprint_for,
)
from quant_lab.db.sqlite import create_sqlite_engine
from quant_lab.market_data.persistence import (
    DataQualityIssueModel,
    DataSourceModel,
    ImportBatchModel,
)

NOW = datetime(2026, 7, 21, 9, 0, tzinfo=UTC)
PREVIEW_FINGERPRINT = "a" * 64


@pytest.fixture
def engine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Engine]:
    settings = Settings(project_root=tmp_path, runtime_root=tmp_path / "runtime")
    monkeypatch.setenv("QUANT_LAB_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("QUANT_LAB_RUNTIME_ROOT", str(settings.runtime_root))
    command.upgrade(Config("backend/alembic.ini"), "head")
    database_engine = create_sqlite_engine(settings)
    yield database_engine
    database_engine.dispose()


def identity(*, logical_key: str = "cn-a-share-daily-bars") -> DatasetIdentity:
    return DatasetIdentity(
        logical_key=logical_key,
        dataset_type="MARKET_BARS",
        market="CN_A_SHARE",
        frequency="DAILY",
        adjustment_type="NONE",
        schema_version="market-bar@1",
    )


def config(**changes: str) -> PublicationConfig:
    values = {
        "frequency": "DAILY",
        "adjustment_type": "NONE",
        "schema_version": "market-bar@1",
        "publication_format_version": "parquet@1",
        "partition_strategy_version": "frequency-exchange-year@1",
        "compression_version": "zstd@1",
        "column_definition_version": "market-bar-columns@1",
    }
    values.update(changes)
    return PublicationConfig(**values)


def insert_preview(
    engine: Engine,
    *,
    suffix: str = "one",
    status: str = "PREVIEW_READY",
    preview_fingerprint: str = PREVIEW_FINGERPRINT,
    accepted_count: int = 2,
    rejected_count: int = 0,
    warning_count: int = 0,
    field_mapping_json: str | None = '{"close":"close","symbol":"symbol"}',
    blocking_issue: bool = False,
) -> str:
    source_id = f"source-{suffix}"
    batch_id = f"batch-{suffix}"
    with Session(engine) as session, session.begin():
        session.add(
            DataSourceModel(
                source_id=source_id,
                identifier=f"local-csv-{suffix}",
                name=f"{suffix}.csv",
                source_type="LOCAL_CSV",
                is_local=True,
                version="1",
                original_file=f"uploads/{suffix}.csv",
                created_at=NOW,
            )
        )
        session.flush()
        session.add(
            ImportBatchModel(
                batch_id=batch_id,
                data_source_id=source_id,
                provider_name="local_csv",
                source_name=f"{suffix}.csv",
                source_file=f"uploads/{suffix}.csv",
                source_file_hash=hashlib.sha256(suffix.encode("utf-8")).hexdigest(),
                requested_at=NOW,
                started_at=NOW,
                completed_at=NOW,
                status=status,
                row_count=accepted_count + rejected_count,
                accepted_count=accepted_count,
                rejected_count=rejected_count,
                warning_count=warning_count,
                schema_version="market-bar@1",
                source_file_size=128,
                field_mapping_json=field_mapping_json,
                provider_version="local-csv@1",
                normalization_version="a-share-daily-normalization@1",
                quality_rules_version="a-share-daily-quality@1",
                preview_fingerprint_version="preview-sha256@1",
                preview_fingerprint=preview_fingerprint,
                preview_completed_at=NOW,
            )
        )
        if blocking_issue:
            session.flush()
            session.add(
                DataQualityIssueModel(
                    issue_id=f"issue-{suffix}",
                    batch_id=batch_id,
                    row_number=2,
                    symbol="600000",
                    field_name="close",
                    severity="ERROR",
                    issue_code="BLOCKED",
                    message="blocked",
                    raw_value="bad",
                    normalized_value=None,
                    issue_fingerprint="f" * 64,
                    issue_fingerprint_version="quality-issue-sha256@2",
                    created_at=NOW,
                )
            )
    return batch_id


def create_dataset(repository: DatasetRepository, *, suffix: str = "one") -> str:
    return repository.create_or_get(
        identity(logical_key=f"cn-a-share-daily-bars-{suffix}"),
        name=f"dataset-{suffix}",
    ).dataset.dataset_id


def claim(
    repository: DatasetRepository,
    batch_id: str,
    dataset_id: str,
    *,
    claimed_at: datetime = NOW,
):
    return repository.claim_publication(
        batch_id=batch_id,
        dataset_id=dataset_id,
        expected_preview_fingerprint=PREVIEW_FINGERPRINT,
        publication_config=config(),
        confirm_warnings=True,
        request_id="request-one",
        operator_label="local operator",
        request_note="confirmed in local UI",
        claimed_at=claimed_at,
    )


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("source_preview_fingerprint", "b" * 64),
        ("dataset_id", "dataset-two"),
        ("frequency", "MINUTE_1"),
        ("adjustment_type", "FORWARD"),
        ("schema_version", "market-bar@2"),
        ("publication_format_version", "parquet@2"),
        ("partition_strategy_version", "frequency-exchange@2"),
        ("compression_version", "zstd@2"),
        ("column_definition_version", "market-bar-columns@2"),
    ],
)
def test_publication_fingerprint_is_stable_and_covers_publication_identity(
    field: str,
    replacement: str,
) -> None:
    baseline = {
        "source_preview_fingerprint": PREVIEW_FINGERPRINT,
        "dataset_id": "dataset-one",
        **asdict(config()),
    }
    changed = dict(baseline)
    changed[field] = replacement

    assert publication_fingerprint_for(**baseline) == publication_fingerprint_for(**baseline)
    assert publication_fingerprint_for(**baseline) != publication_fingerprint_for(**changed)
    assert len(publication_fingerprint_for(**baseline)) == 64


def test_claim_atomically_creates_validating_version_transitions_batch_and_audits(
    engine: Engine,
) -> None:
    repository = DatasetRepository(engine, run_mode=RunMode.RESEARCH)
    dataset_id = create_dataset(repository)
    batch_id = insert_preview(engine)

    result = claim(repository, batch_id, dataset_id)

    assert result.created is True
    assert result.idempotent_replay is False
    assert result.version.version == 1
    assert result.version.status == "VALIDATING"
    assert result.version.publication_claimed_at == NOW
    with Session(engine) as session:
        batch = session.get(ImportBatchModel, batch_id)
        audits = session.scalars(select(PublicationAuditModel)).all()
    assert batch is not None and batch.status == "PUBLISHING"
    assert len(audits) == 1
    assert audits[0].dataset_version_id == result.version.dataset_version_id
    assert audits[0].actor_type == "LOCAL_UNAUTHENTICATED_USER"
    assert audits[0].operator_label == "local operator"
    assert audits[0].request_note == "confirmed in local UI"
    assert audits[0].result == "CLAIMED"


def test_naive_claimed_at_is_rejected_without_database_writes(engine: Engine) -> None:
    repository = DatasetRepository(engine, run_mode=RunMode.RESEARCH)
    dataset_id = create_dataset(repository)
    batch_id = insert_preview(engine)
    naive_claimed_at = datetime(2026, 7, 21, 9, 0)

    with pytest.raises(DatasetError) as raised:
        claim(repository, batch_id, dataset_id, claimed_at=naive_claimed_at)

    assert raised.value.category == "PUBLICATION_CLAIM_TIME_INVALID"
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(DatasetVersionModel)) == 0
        assert session.scalar(select(func.count()).select_from(PublicationAuditModel)) == 0
        batch = session.get(ImportBatchModel, batch_id)
    assert batch is not None and batch.status == "PREVIEW_READY"


def test_non_utc_claimed_at_is_normalized_before_first_claim(engine: Engine) -> None:
    repository = DatasetRepository(engine, run_mode=RunMode.RESEARCH)
    dataset_id = create_dataset(repository)
    batch_id = insert_preview(engine)
    shanghai = timezone(timedelta(hours=8))
    local_claimed_at = datetime(2026, 7, 21, 17, 0, tzinfo=shanghai)

    result = claim(repository, batch_id, dataset_id, claimed_at=local_claimed_at)
    fetched = repository.get_version(dataset_id, result.version.dataset_version_id)

    assert result.version.publication_claimed_at == NOW
    assert result.version.publication_claimed_at.tzinfo is UTC
    assert fetched.publication_claimed_at == NOW
    assert fetched.publication_claimed_at.tzinfo is UTC


def test_replay_reuses_first_normalized_utc_claim_time(engine: Engine) -> None:
    repository = DatasetRepository(engine, run_mode=RunMode.RESEARCH)
    dataset_id = create_dataset(repository)
    batch_id = insert_preview(engine)
    shanghai = timezone(timedelta(hours=8))
    local_claimed_at = datetime(2026, 7, 21, 17, 0, tzinfo=shanghai)
    first = claim(repository, batch_id, dataset_id, claimed_at=local_claimed_at)

    replay = claim(
        repository,
        batch_id,
        dataset_id,
        claimed_at=NOW + timedelta(days=1),
    )

    assert first.version.publication_claimed_at == NOW
    assert replay.version.publication_claimed_at == NOW
    assert first.version.publication_claimed_at.tzinfo is UTC
    assert replay.version.publication_claimed_at.tzinfo is UTC


def test_concurrent_same_fingerprint_claims_one_version_transition_and_substantive_audit(
    engine: Engine,
) -> None:
    repository = DatasetRepository(engine, run_mode=RunMode.RESEARCH)
    dataset_id = create_dataset(repository)
    batch_id = insert_preview(engine)
    workers = 2
    barrier = Barrier(workers)

    def concurrent_claim(index: int):
        barrier.wait()
        return DatasetRepository(engine, run_mode=RunMode.RESEARCH).claim_publication(
            batch_id=batch_id,
            dataset_id=dataset_id,
            expected_preview_fingerprint=PREVIEW_FINGERPRINT,
            publication_config=config(),
            confirm_warnings=True,
            request_id=f"request-{index}",
            claimed_at=NOW + timedelta(minutes=index),
        )

    with ThreadPoolExecutor(max_workers=workers) as executor:
        results = list(executor.map(concurrent_claim, range(workers)))

    assert len({result.version.dataset_version_id for result in results}) == 1
    assert {result.version.version for result in results} == {1}
    assert sum(result.created for result in results) == 1
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(DatasetVersionModel)) == 1
        assert session.scalar(select(func.count()).select_from(PublicationAuditModel)) == 1
        batch = session.get(ImportBatchModel, batch_id)
    assert batch is not None and batch.status == "PUBLISHING"
    claimed_times = {result.version.publication_claimed_at for result in results}
    created_result = next(result for result in results if result.created)
    assert claimed_times == {created_result.version.publication_claimed_at}


@pytest.mark.parametrize("existing_status", ["VALIDATING", "STAGING", "FILES_COMMITTED"])
def test_processing_replay_returns_same_id_status_and_frozen_claim_time(
    engine: Engine,
    existing_status: str,
) -> None:
    repository = DatasetRepository(engine, run_mode=RunMode.RESEARCH)
    dataset_id = create_dataset(repository)
    batch_id = insert_preview(engine)
    first = claim(repository, batch_id, dataset_id)
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE dataset_versions SET status=:status WHERE dataset_version_id=:id"),
            {"status": existing_status, "id": first.version.dataset_version_id},
        )

    replay = claim(repository, batch_id, dataset_id, claimed_at=NOW + timedelta(days=1))

    assert replay.created is False
    assert replay.idempotent_replay is True
    assert replay.version.dataset_version_id == first.version.dataset_version_id
    assert replay.version.status == existing_status
    assert replay.version.publication_claimed_at == NOW


def test_published_replay_returns_existing_version_without_new_audit(engine: Engine) -> None:
    repository = DatasetRepository(engine, run_mode=RunMode.RESEARCH)
    dataset_id = create_dataset(repository)
    batch_id = insert_preview(engine)
    first = claim(repository, batch_id, dataset_id)
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE dataset_versions SET status='PUBLISHED' WHERE dataset_version_id=:id"),
            {"id": first.version.dataset_version_id},
        )
        connection.execute(
            text("UPDATE import_batches SET status='PUBLISHED' WHERE batch_id=:id"),
            {"id": batch_id},
        )

    replay = claim(repository, batch_id, dataset_id, claimed_at=NOW + timedelta(days=1))

    assert replay.version.dataset_version_id == first.version.dataset_version_id
    assert replay.version.status == "PUBLISHED"
    assert replay.idempotent_replay is True
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(PublicationAuditModel)) == 1


@pytest.mark.parametrize(
    ("case", "batch_options", "confirm_warnings", "expected_category"),
    [
        ("pending-replay", {"status": "PENDING"}, True, "PUBLICATION_BATCH_NOT_READY"),
        ("failed-replay", {"status": "FAILED"}, True, "PUBLICATION_BATCH_NOT_READY"),
        (
            "mapping-replay",
            {"field_mapping_json": None},
            True,
            "PUBLICATION_PREVIEW_INCOMPLETE",
        ),
        ("zero-replay", {"accepted_count": 0}, True, "PUBLICATION_PREVIEW_EMPTY"),
        (
            "rejected-replay",
            {"rejected_count": 1},
            True,
            "PUBLICATION_BLOCKED_BY_QUALITY",
        ),
        (
            "blocked-replay",
            {"blocking_issue": True},
            True,
            "PUBLICATION_BLOCKED_BY_QUALITY",
        ),
        (
            "warning-replay",
            {"warning_count": 1},
            False,
            "PUBLICATION_WARNINGS_NOT_CONFIRMED",
        ),
    ],
)
def test_existing_fingerprint_does_not_bypass_current_batch_eligibility(
    engine: Engine,
    case: str,
    batch_options: dict[str, object],
    confirm_warnings: bool,
    expected_category: str,
) -> None:
    repository = DatasetRepository(engine, run_mode=RunMode.RESEARCH)
    dataset_id = create_dataset(repository)
    winner_batch_id = insert_preview(engine, suffix="winner")
    winner = claim(repository, winner_batch_id, dataset_id)
    challenger_batch_id = insert_preview(engine, suffix=case, **batch_options)  # type: ignore[arg-type]

    with pytest.raises(DatasetError) as raised:
        repository.claim_publication(
            batch_id=challenger_batch_id,
            dataset_id=dataset_id,
            expected_preview_fingerprint=PREVIEW_FINGERPRINT,
            publication_config=config(),
            confirm_warnings=confirm_warnings,
            request_id=f"request-{case}",
            claimed_at=NOW + timedelta(hours=1),
        )

    assert raised.value.category == expected_category
    with Session(engine) as session:
        versions = session.scalars(select(DatasetVersionModel)).all()
        audits = session.scalars(select(PublicationAuditModel)).all()
        challenger = session.get(ImportBatchModel, challenger_batch_id)
    assert [version.dataset_version_id for version in versions] == [
        winner.version.dataset_version_id
    ]
    assert len(audits) == 1
    assert challenger is not None
    assert challenger.status == batch_options.get("status", "PREVIEW_READY")


def test_existing_fingerprint_from_different_eligible_batch_is_a_stable_conflict(
    engine: Engine,
) -> None:
    repository = DatasetRepository(engine, run_mode=RunMode.RESEARCH)
    dataset_id = create_dataset(repository)
    winner_batch_id = insert_preview(engine, suffix="winner")
    winner = claim(repository, winner_batch_id, dataset_id)
    challenger_batch_id = insert_preview(engine, suffix="challenger")

    with pytest.raises(DatasetError) as raised:
        claim(repository, challenger_batch_id, dataset_id)

    assert raised.value.category == "PUBLICATION_FINGERPRINT_BATCH_CONFLICT"
    with Session(engine) as session:
        versions = session.scalars(select(DatasetVersionModel)).all()
        audits = session.scalars(select(PublicationAuditModel)).all()
        challenger = session.get(ImportBatchModel, challenger_batch_id)
    assert [version.dataset_version_id for version in versions] == [
        winner.version.dataset_version_id
    ]
    assert len(audits) == 1
    assert challenger is not None and challenger.status == "PREVIEW_READY"


@pytest.mark.parametrize("run_mode", [RunMode.PAPER, RunMode.LIVE, "UNKNOWN"])
def test_non_research_mode_rejects_claim_without_writes(
    engine: Engine,
    run_mode: RunMode | str,
) -> None:
    setup_repository = DatasetRepository(engine, run_mode=RunMode.RESEARCH)
    dataset_id = create_dataset(setup_repository)
    batch_id = insert_preview(engine)
    restricted_repository = DatasetRepository(engine, run_mode=run_mode)

    with pytest.raises(DatasetError) as raised:
        claim(restricted_repository, batch_id, dataset_id)

    assert raised.value.category == "PUBLICATION_DISABLED_FOR_RUN_MODE"
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(DatasetVersionModel)) == 0
        assert session.scalar(select(func.count()).select_from(PublicationAuditModel)) == 0
        batch = session.get(ImportBatchModel, batch_id)
    assert batch is not None and batch.status == "PREVIEW_READY"


@pytest.mark.parametrize("run_mode", [RunMode.PAPER, RunMode.LIVE, "UNKNOWN"])
def test_non_research_mode_rejects_idempotent_replay_without_writes(
    engine: Engine,
    run_mode: RunMode | str,
) -> None:
    research_repository = DatasetRepository(engine, run_mode=RunMode.RESEARCH)
    dataset_id = create_dataset(research_repository)
    batch_id = insert_preview(engine)
    winner = claim(research_repository, batch_id, dataset_id)
    restricted_repository = DatasetRepository(engine, run_mode=run_mode)

    with pytest.raises(DatasetError) as raised:
        claim(restricted_repository, batch_id, dataset_id)

    assert raised.value.category == "PUBLICATION_DISABLED_FOR_RUN_MODE"
    with Session(engine) as session:
        versions = session.scalars(select(DatasetVersionModel)).all()
        audits = session.scalars(select(PublicationAuditModel)).all()
        batch = session.get(ImportBatchModel, batch_id)
    assert [version.dataset_version_id for version in versions] == [
        winner.version.dataset_version_id
    ]
    assert len(audits) == 1
    assert batch is not None and batch.status == "PUBLISHING"


def test_unique_constraint_race_rereads_winner_without_leaking_integrity_error(
    engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = DatasetRepository(engine, run_mode=RunMode.RESEARCH)
    dataset_id = create_dataset(repository)
    batch_id = insert_preview(engine)
    winner = claim(repository, batch_id, dataset_id)
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE import_batches SET status='PREVIEW_READY' WHERE batch_id=:id"),
            {"id": batch_id},
        )

    original_scalar = Session.scalar
    stale_read_injected = False

    def scalar_with_one_stale_read(self, statement, *args, **kwargs):
        nonlocal stale_read_injected
        sql = str(statement)
        if not stale_read_injected and "dataset_versions.publication_fingerprint" in sql:
            stale_read_injected = True
            return None
        return original_scalar(self, statement, *args, **kwargs)

    monkeypatch.setattr(Session, "scalar", scalar_with_one_stale_read)

    replay = claim(repository, batch_id, dataset_id, claimed_at=NOW + timedelta(days=1))

    assert stale_read_injected is True
    assert replay.created is False
    assert replay.idempotent_replay is True
    assert replay.version.dataset_version_id == winner.version.dataset_version_id
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(DatasetVersionModel)) == 1
        assert session.scalar(select(func.count()).select_from(PublicationAuditModel)) == 1


def test_versions_are_allocated_independently_per_dataset(engine: Engine) -> None:
    repository = DatasetRepository(engine, run_mode=RunMode.RESEARCH)
    dataset_a = create_dataset(repository, suffix="a")
    dataset_b = create_dataset(repository, suffix="b")
    batch_a = insert_preview(engine, suffix="a", preview_fingerprint="a" * 64)
    batch_b = insert_preview(engine, suffix="b", preview_fingerprint="b" * 64)
    barrier = Barrier(2)

    def worker(dataset_id: str, batch_id: str, fingerprint: str):
        barrier.wait()
        return DatasetRepository(engine, run_mode=RunMode.RESEARCH).claim_publication(
            batch_id=batch_id,
            dataset_id=dataset_id,
            expected_preview_fingerprint=fingerprint,
            publication_config=config(),
            confirm_warnings=True,
            request_id=f"request-{batch_id}",
            claimed_at=NOW,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(
                lambda args: worker(*args),
                ((dataset_a, batch_a, "a" * 64), (dataset_b, batch_b, "b" * 64)),
            )
        )

    assert [result.version.version for result in results] == [1, 1]
    assert len({result.version.dataset_id for result in results}) == 2


@pytest.mark.parametrize(
    ("case", "batch_options", "expected_category"),
    [
        ("pending", {"status": "PENDING"}, "PUBLICATION_BATCH_NOT_READY"),
        ("failed", {"status": "FAILED"}, "PUBLICATION_BATCH_NOT_READY"),
        ("mapping", {"field_mapping_json": None}, "PUBLICATION_PREVIEW_INCOMPLETE"),
        ("zero", {"accepted_count": 0}, "PUBLICATION_PREVIEW_EMPTY"),
        ("blocked", {"blocking_issue": True}, "PUBLICATION_BLOCKED_BY_QUALITY"),
    ],
)
def test_claim_rejects_ineligible_preview_without_partial_state(
    engine: Engine,
    case: str,
    batch_options: dict[str, object],
    expected_category: str,
) -> None:
    repository = DatasetRepository(engine, run_mode=RunMode.RESEARCH)
    dataset_id = create_dataset(repository, suffix=case)
    batch_id = insert_preview(engine, suffix=case, **batch_options)  # type: ignore[arg-type]

    with pytest.raises(DatasetError) as raised:
        claim(repository, batch_id, dataset_id)

    assert raised.value.category == expected_category
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(DatasetVersionModel)) == 0
        assert session.scalar(select(func.count()).select_from(PublicationAuditModel)) == 0
        batch = session.get(ImportBatchModel, batch_id)
    assert batch is not None and batch.status == batch_options.get("status", "PREVIEW_READY")


def test_claim_checks_expected_fingerprint_and_dataset_identity(engine: Engine) -> None:
    repository = DatasetRepository(engine, run_mode=RunMode.RESEARCH)
    dataset_id = create_dataset(repository)
    batch_id = insert_preview(engine)

    with pytest.raises(DatasetError) as fingerprint_error:
        repository.claim_publication(
            batch_id=batch_id,
            dataset_id=dataset_id,
            expected_preview_fingerprint="0" * 64,
            publication_config=config(),
            confirm_warnings=True,
            request_id="request-mismatch",
            claimed_at=NOW,
        )
    assert fingerprint_error.value.category == "PREVIEW_FINGERPRINT_MISMATCH"

    with pytest.raises(DatasetError) as identity_error:
        repository.claim_publication(
            batch_id=batch_id,
            dataset_id=dataset_id,
            expected_preview_fingerprint=PREVIEW_FINGERPRINT,
            publication_config=replace(config(), frequency="MINUTE_1"),
            confirm_warnings=True,
            request_id="request-identity",
            claimed_at=NOW,
        )
    assert identity_error.value.category == "PUBLICATION_DATASET_MISMATCH"
