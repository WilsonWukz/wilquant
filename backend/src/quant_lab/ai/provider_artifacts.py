from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path


def sanitize_provider_content(value: object, *, depth: int = 0) -> object:
    """Second defensive boundary; actual credential-value removal happens in Host."""
    if depth > 32:
        return "[REDACTED]"
    if isinstance(value, dict):
        result: dict[str, object] = {}
        for key, item in value.items():
            normalized = re.sub(r"[^a-z0-9]", "", str(key).lower())
            if any(
                word in normalized
                for word in (
                    "reasoning",
                    "thinking",
                    "apikey",
                    "accesstoken",
                    "clientsecret",
                    "authorization",
                    "credential",
                    "hosttoken",
                    "cookie",
                    "password",
                )
            ):
                continue
            result[str(key)] = sanitize_provider_content(item, depth=depth + 1)
        return result
    if isinstance(value, list):
        return [sanitize_provider_content(item, depth=depth + 1) for item in value]
    if isinstance(value, str):
        text = re.sub(r"(?i)\bBearer\s+\S+", "[REDACTED]", value)
        text = re.sub(r"(?i)\b(?:sk|pk)-[a-z0-9_-]{20,}", "[REDACTED]", text)
        return re.sub(
            r"(?i)(api[_-]?key|access[_-]?token|client[_-]?secret)\s*[:=]\s*\S+", "[REDACTED]", text
        )
    return value


class ProviderArtifactStore:
    def __init__(self, root: Path, max_bytes: int = 1048576) -> None:
        self.root = root.resolve()
        self.max_bytes = max_bytes

    def write(self, kind: str, value: object) -> dict[str, object]:
        if kind not in {"raw", "candidate"}:
            raise ValueError("AI_ARTIFACT_NAMESPACE_INVALID")
        data = json.dumps(
            sanitize_provider_content(value),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        if len(data) > self.max_bytes:
            raise ValueError("PROVIDER_RESPONSE_TOO_LARGE")
        digest = hashlib.sha256(data).hexdigest()
        relative = Path("ai") / kind / f"{digest}.json"
        target = self.root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.resolve().is_relative_to(self.root):
            raise ValueError("AI_ARTIFACT_PATH_INVALID")
        fd, name = tempfile.mkstemp(prefix=".pending-", dir=target.parent)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, target)
        finally:
            Path(name).unlink(missing_ok=True)
        return {
            "path": relative.as_posix(),
            "sha256": digest,
            "bytes": len(data),
            "kind": kind,
            "retention_policy": "ai-artifact-v1-no-reasoning",
        }
