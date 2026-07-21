from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

from sqlalchemy.exc import OperationalError

from quant_lab.datasets.domain import DatasetVersionStatus
from quant_lab.datasets.repository import DatasetRepository


class PublicationRecoveryService:
    """Bounded, idempotent recovery for interrupted publication file/SQLite gaps."""

    def __init__(
        self, repository: DatasetRepository, staging_root: Path, published_root: Path
    ) -> None:
        self.repository = repository
        self.staging_root = staging_root.resolve()
        self.published_root = published_root.resolve()

    def recover(self) -> dict[str, int]:
        recovered = failed = 0
        try:
            versions = self.repository.list_all_versions()
        except OperationalError:
            # Health-only app fixtures may intentionally start before migrations.
            return {"recovered": 0, "failed": 0}
        for version in versions:
            if version.status == DatasetVersionStatus.PUBLISHED.value:
                continue
            staging = self.staging_root / version.dataset_version_id
            relative_root = (
                f"market_bars/dataset={version.dataset_id}/version={version.version:06d}"
            )
            final = self.published_root / relative_root
            if version.status in {
                DatasetVersionStatus.VALIDATING.value,
                DatasetVersionStatus.STAGING.value,
                DatasetVersionStatus.FILES_COMMITTING.value,
            } and (staging.exists() or not final.exists()):
                    self.repository.mark_publication_failed(
                        version_id=version.dataset_version_id,
                        batch_id=version.source_batch_id,
                        code="PUBLICATION_INTERRUPTED",
                        reason="publication interrupted before final commit",
                        request_id="recovery",
                        config_json="{}",
                        confirm_warnings=False,
                    )
                    failed += 1
                    continue
            if version.status != DatasetVersionStatus.FILES_COMMITTED.value or not final.is_dir():
                continue
            manifest_path = final / "manifest.json"
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                if (
                    manifest["dataset_version_id"] != version.dataset_version_id
                    or manifest["dataset_id"] != version.dataset_id
                ):
                    raise ValueError("manifest identity mismatch")
                files = []
                for item in manifest["files"]:
                    path = (final / item["relative_path"]).resolve()
                    if (
                        final not in path.parents
                        or not path.is_file()
                        or path.stat().st_size != item["size_bytes"]
                    ):
                        raise ValueError("file missing")
                    digest = hashlib.sha256(path.read_bytes()).hexdigest()
                    if digest != item["sha256"]:
                        raise ValueError("file hash mismatch")
                    files.append(
                        dict(
                            item,
                            min_timestamp=datetime.fromisoformat(item["min_timestamp"]),
                            max_timestamp=datetime.fromisoformat(item["max_timestamp"]),
                        )
                    )
                self.repository.finalize_publication(
                    version_id=version.dataset_version_id,
                    batch_id=version.source_batch_id,
                    dataset_id=version.dataset_id,
                    files=files,
                    relative_root=relative_root,
                    manifest_path=f"{relative_root}/manifest.json",
                    manifest_sha256=hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
                    row_count=int(manifest["row_count"]),
                    instrument_count=version.instrument_count,
                    min_timestamp=version.min_timestamp,
                    max_timestamp=version.max_timestamp,
                    partition_count=len(files),
                    total_size_bytes=sum(int(item["size_bytes"]) for item in files),
                    quality_issue_count=version.quality_issue_count,
                    warning_count=version.warning_count,
                    blocking_issue_count=version.blocking_issue_count,
                    quality_summary_json=version.quality_summary_json or "{}",
                    request_id="recovery",
                    publication_fingerprint=version.publication_fingerprint,
                    config_json="{}",
                    confirm_warnings=False,
                    claimed_at=version.publication_claimed_at,
                )
                recovered += 1
            except Exception:
                self.repository.mark_publication_failed(
                    version_id=version.dataset_version_id,
                    batch_id=version.source_batch_id,
                    code="PUBLICATION_RECOVERY_FAILED",
                    reason="published files failed recovery validation",
                    request_id="recovery",
                    config_json="{}",
                    confirm_warnings=False,
                )
                failed += 1
        return {"recovered": recovered, "failed": failed}
