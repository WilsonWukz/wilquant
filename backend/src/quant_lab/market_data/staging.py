from __future__ import annotations

import hashlib
from collections.abc import AsyncIterable
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from quant_lab.market_data.errors import ImportDataError

_ALLOWED_SUFFIXES = {".csv", ".parquet"}


@dataclass(frozen=True, slots=True)
class StagedUpload:
    path: Path
    storage_key: str
    original_filename: str
    sha256: str
    size: int


class ControlledUploadStore:
    def __init__(self, root: Path, max_bytes: int) -> None:
        self._root = root.resolve()
        self._max_bytes = max_bytes

    def stage(self, filename: str, chunks: list[bytes]) -> StagedUpload:
        display_name, suffix = self._validate_filename(filename)

        self._root.mkdir(parents=True, exist_ok=True)
        identifier = uuid4().hex
        temporary_path = self._root / f".{identifier}.tmp"
        final_path = self._root / f"{identifier}{suffix}"
        digest = hashlib.sha256()
        size = 0
        try:
            with temporary_path.open("xb") as output:
                for chunk in chunks:
                    size += len(chunk)
                    if size > self._max_bytes:
                        raise ImportDataError("FILE_TOO_LARGE", "上传文件超过允许大小")
                    digest.update(chunk)
                    output.write(chunk)
            temporary_path.replace(final_path)
        except Exception:
            temporary_path.unlink(missing_ok=True)
            raise
        return StagedUpload(
            path=final_path,
            storage_key=final_path.name,
            original_filename=display_name,
            sha256=digest.hexdigest(),
            size=size,
        )

    async def stage_stream(self, filename: str, chunks: AsyncIterable[bytes]) -> StagedUpload:
        display_name, suffix = self._validate_filename(filename)
        self._root.mkdir(parents=True, exist_ok=True)
        identifier = uuid4().hex
        temporary_path = self._root / f".{identifier}.tmp"
        final_path = self._root / f"{identifier}{suffix}"
        digest = hashlib.sha256()
        size = 0
        try:
            with temporary_path.open("xb") as output:
                async for chunk in chunks:
                    size += len(chunk)
                    if size > self._max_bytes:
                        raise ImportDataError("FILE_TOO_LARGE", "上传文件超过允许大小")
                    digest.update(chunk)
                    output.write(chunk)
            temporary_path.replace(final_path)
        except Exception:
            temporary_path.unlink(missing_ok=True)
            raise
        return StagedUpload(
            final_path,
            final_path.name,
            display_name,
            digest.hexdigest(),
            size,
        )

    @staticmethod
    def _validate_filename(filename: str) -> tuple[str, str]:
        if not filename or "/" in filename or "\\" in filename:
            raise ImportDataError("INVALID_FILENAME", "文件名无效")
        display_name = Path(filename).name
        suffix = Path(display_name).suffix.lower()
        if suffix not in _ALLOWED_SUFFIXES:
            raise ImportDataError("UNSUPPORTED_FORMAT", "仅支持 CSV 或 Parquet 文件")
        return display_name, suffix
