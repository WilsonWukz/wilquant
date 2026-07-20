import hashlib
from pathlib import Path

import pytest

from quant_lab.market_data.errors import ImportDataError
from quant_lab.market_data.staging import ControlledUploadStore


def test_stages_upload_under_controlled_root_without_modifying_source(tmp_path: Path) -> None:
    source = tmp_path / "source.csv"
    content = b"symbol,close\n600000,10.5\n"
    source.write_bytes(content)
    staging_root = tmp_path / "runtime" / "imports"
    store = ControlledUploadStore(staging_root, max_bytes=1024)

    staged = store.stage(source.name, [source.read_bytes()])

    assert staged.path.parent == staging_root.resolve()
    assert staged.path.name != source.name
    assert staged.path.suffix == ".csv"
    assert staged.sha256 == hashlib.sha256(content).hexdigest()
    assert staged.size == len(content)
    assert source.read_bytes() == content


@pytest.mark.parametrize(
    ("filename", "expected_category"),
    [
        ("bars.exe", "UNSUPPORTED_FORMAT"),
        ("../bars.txt", "INVALID_FILENAME"),
        ("bars", "UNSUPPORTED_FORMAT"),
    ],
)
def test_rejects_unsupported_upload_types(
    tmp_path: Path, filename: str, expected_category: str
) -> None:
    store = ControlledUploadStore(tmp_path / "staging", max_bytes=1024)

    with pytest.raises(ImportDataError) as error:
        store.stage(filename, [b"data"])

    assert error.value.category == expected_category


def test_rejects_oversized_upload_without_leaving_file(tmp_path: Path) -> None:
    staging_root = tmp_path / "staging"
    store = ControlledUploadStore(staging_root, max_bytes=4)

    with pytest.raises(ImportDataError) as error:
        store.stage("bars.csv", [b"123", b"45"])

    assert error.value.category == "FILE_TOO_LARGE"
    assert list(staging_root.glob("*")) == []
