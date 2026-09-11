from __future__ import annotations

import ast
from pathlib import Path

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.anyio

AI_SOURCE = Path("backend/src/quant_lab/ai")
FORBIDDEN_IMPORTS = (
    "quant_lab.live",
    "quant_lab.execution_gateway",
    "quant_lab.brokers",
    "openai",
    "anthropic",
    "httpx",
    "requests",
)
READ_ONLY_DOMAIN_IMPORTS = {
    ("source_resolvers.py", "quant_lab.paper.repository"),
    # AI-4's explicitly wired resolver relationship check is SELECT-only;
    # test_analysis_relationships also verifies that no SQL mutation is issued.
    ("analysis_relationships.py", "quant_lab.paper.models"),
}


def _imports(path: Path) -> tuple[str, ...]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            names.append(node.module)
    return tuple(names)


async def test_ai_package_has_no_execution_or_provider_network_imports() -> None:
    violations = {
        str(path): name
        for path in AI_SOURCE.glob("*.py")
        for name in _imports(path)
        if name.startswith(FORBIDDEN_IMPORTS)
        or (
            name.startswith("quant_lab.paper")
            and (path.name, name) not in READ_ONLY_DOMAIN_IMPORTS
        )
    }
    assert violations == {}


async def test_ai_unavailable_does_not_change_required_readiness(client: AsyncClient) -> None:
    ready = await client.get("/api/v1/health/ready")
    unavailable = await client.get("/api/v1/research-cases/missing")

    assert ready.status_code == 200
    assert ready.json()["status"] == "ready"
    assert {item["name"] for item in ready.json()["components"]} == {"sqlite", "duckdb"}
    assert unavailable.status_code == 503
    assert unavailable.json()["error_code"] == "AI_PROVENANCE_UNAVAILABLE"
