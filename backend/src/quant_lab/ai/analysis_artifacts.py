from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from quant_lab.ai.configuration import contains_forbidden_secret_material
from quant_lab.ai.provider_artifacts import sanitize_provider_content
from quant_lab.market_data.fingerprints import canonical_json_bytes


class AnalysisArtifactStore:
    """Exact frozen input/output bytes: reject secret-shaped inputs, never silently alter them."""

    def __init__(self, root: Path, max_bytes: int = 262144) -> None:
        self.root, self.max_bytes = root.resolve(), max_bytes

    def write(self, kind: str, value: object) -> dict[str, object]:
        if kind not in {"prompt", "request", "context", "accepted"}:
            raise ValueError("ANALYSIS_ARTIFACT_NAMESPACE_INVALID")
        if contains_forbidden_secret_material(value) or sanitize_provider_content(value) != value:
            raise ValueError("ANALYSIS_SECRET_MATERIAL_FORBIDDEN")
        data = canonical_json_bytes(value)
        if len(data) > self.max_bytes:
            raise ValueError("ANALYSIS_CONTEXT_TOO_LARGE")
        digest = hashlib.sha256(data).hexdigest()
        relative = Path("ai") / "analysis" / kind / (digest + ".json")
        target = (self.root / relative).resolve()
        if not target.is_relative_to(self.root):
            raise ValueError("ANALYSIS_ARTIFACT_PATH_INVALID")
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix=".pending-", dir=target.parent)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, target)
        finally:
            Path(name).unlink(missing_ok=True)
        return {"path": relative.as_posix(), "sha256": digest, "bytes": len(data), "kind": kind}

    def read(self, metadata: dict[str, Any]) -> dict[str, Any]:
        path = (self.root / str(metadata["path"])).resolve()
        if not path.is_relative_to(self.root / "ai"):
            raise ValueError("ANALYSIS_ARTIFACT_PATH_INVALID")
        with path.open("rb") as stream:
            data = stream.read(self.max_bytes + 1)
        if (
            len(data) > self.max_bytes
            or hashlib.sha256(data).hexdigest() != metadata["sha256"]
            or len(data) != metadata["bytes"]
        ):
            raise ValueError("ANALYSIS_ARTIFACT_INTEGRITY")
        value = json.loads(data)
        if not isinstance(value, dict):
            raise ValueError("ANALYSIS_ARTIFACT_FORMAT_INVALID")
        return value
