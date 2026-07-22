from quant_lab.main import create_app


def test_phase_2c_routes_are_public_in_openapi():
    paths = create_app().openapi()["paths"]
    assert "/api/v1/market-calendars" in paths
    assert "/api/v1/market-calendars/{calendar_id}/versions/import" in paths
    assert "/api/v1/market-data/profiles" in paths
    assert "/api/v1/market-data/profiles/{profile_id}/bars" in paths
    assert "/api/v1/market-data/profiles/{profile_id}/coverage" in paths
    assert "/api/v1/market-data/profiles/{profile_id}/snapshot" in paths
