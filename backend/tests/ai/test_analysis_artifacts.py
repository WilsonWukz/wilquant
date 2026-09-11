import pytest


def test_analysis_artifact_round_trip_verifies_hash_and_namespace(tmp_path):
    from quant_lab.ai.analysis_artifacts import AnalysisArtifactStore

    store = AnalysisArtifactStore(tmp_path)
    metadata = store.write("prompt", {"messages": ["有限研究上下文"]})
    assert store.read(metadata) == {"messages": ["有限研究上下文"]}
    (tmp_path / metadata["path"]).write_text("{}")
    with pytest.raises(ValueError, match="ARTIFACT_INTEGRITY"):
        store.read(metadata)


def test_analysis_artifact_rejects_secret_instead_of_changing_frozen_prompt(tmp_path):
    from quant_lab.ai.analysis_artifacts import AnalysisArtifactStore

    with pytest.raises(ValueError, match="SECRET"):
        AnalysisArtifactStore(tmp_path).write("prompt", {"content": "api_key=private"})
