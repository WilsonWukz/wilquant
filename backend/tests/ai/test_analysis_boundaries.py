import ast
from pathlib import Path


def test_orchestration_has_no_direct_provider_or_trading_write_imports():
    root = Path(__file__).parents[2] / "src" / "quant_lab" / "ai"
    paths = list(root.glob("analysis_*.py"))
    assert paths
    forbidden = (
        "httpx",
        "requests",
        "openai",
        "quant_lab.paper.service",
        "quant_lab.paper.risk_service",
        "quant_lab.execution",
        "quant_lab.live",
        "quant_lab.broker",
        "quant_lab.gateway",
    )
    for path in paths:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            imports = (
                [alias.name for alias in node.names]
                if isinstance(node, ast.Import)
                else ([node.module or ""] if isinstance(node, ast.ImportFrom) else [])
            )
            assert not any(
                name == prefix or name.startswith(prefix + ".")
                for name in imports
                for prefix in forbidden
            ), path
