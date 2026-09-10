from pathlib import Path

import pytest


def test_client_module_exists():
    from importlib.util import find_spec

    assert find_spec("quant_lab.ai_provider_client") is not None


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com",
        "http://192.168.1.1:8011",
        "http://127.0.0.1:8011@evil.com",
        "http://127.0.0.1:8011/path",
        "file:///secret",
    ],
)
def test_client_rejects_nonlocal_or_noncanonical_url(url):
    from quant_lab.ai_provider_client import AIProviderHostClient

    with pytest.raises(ValueError):
        AIProviderHostClient(url, Path("unused"))


def test_missing_token_is_safe_known_failure(tmp_path):
    from quant_lab.ai_provider_client import AIProviderHostClient
    from quant_lab.ai_provider_protocol import ProviderFailure

    client = AIProviderHostClient("http://127.0.0.1:8011", tmp_path / "missing")
    with pytest.raises(ProviderFailure) as caught:
        client.health()
    assert caught.value.code == "PROVIDER_HOST_UNAVAILABLE"
    assert str(tmp_path) not in str(caught.value)
