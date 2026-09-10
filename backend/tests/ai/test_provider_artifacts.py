import json

import pytest


def test_artifact_module_exists():
    from importlib.util import find_spec

    assert find_spec("quant_lab.ai.provider_artifacts") is not None


def test_raw_redacted_and_reasoning_removed(tmp_path):
    from quant_lab.ai.provider_artifacts import ProviderArtifactStore

    store = ProviderArtifactStore(tmp_path, max_bytes=4096)
    metadata = store.write(
        "raw",
        {
            "content": "ok",
            "Authorization": "Bearer supersecret",
            "nested": {"reasoning_content": "hidden", "apiKey": "very secret"},
        },
    )
    content = (tmp_path / metadata["path"]).read_text()
    assert "supersecret" not in content and "very secret" not in content
    assert "hidden" not in content
    assert metadata["sha256"] and metadata["bytes"] == len(content.encode())
    assert json.loads(content)["content"] == "ok"


def test_artifact_bound_and_namespace(tmp_path):
    from quant_lab.ai.provider_artifacts import ProviderArtifactStore

    store = ProviderArtifactStore(tmp_path, max_bytes=10)
    with pytest.raises(ValueError, match="PROVIDER_RESPONSE_TOO_LARGE"):
        store.write("raw", "x" * 20)
    with pytest.raises(ValueError):
        store.write("../../escape", "ok")
