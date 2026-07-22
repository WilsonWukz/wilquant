from quant_lab.main import create_app


def test_backtest_routes_are_public_in_openapi():
    paths = create_app().openapi()["paths"]
    assert "/api/v1/backtests" in paths
    assert "/api/v1/backtests/{run_id}" in paths
    assert "/api/v1/backtests/{run_id}/{artifact_type}" in paths
    for artifact in ("metrics", "equity", "orders", "fills", "positions"):
        assert f"/api/v1/backtests/{{run_id}}/{artifact}" in paths
