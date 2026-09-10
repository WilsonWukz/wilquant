import os
import subprocess
import sys

import pytest

from quant_lab.ai_provider_protocol import ProviderFailure


def test_windows_secret_store_uses_native_boundary():
    from quant_lab.ai_provider_host.secrets import WindowsCredentialManagerSecretStore

    values = {}

    class Native:
        def read(self, target):
            return values.get(target)

        def write(self, target, value):
            values[target] = value

        def delete(self, target):
            values.pop(target, None)

    store = WindowsCredentialManagerSecretStore(native=Native())
    store.set("wilquant.ai.test", "secret")
    assert store.exists("wilquant.ai.test")
    assert store.get("wilquant.ai.test") == "secret"
    store.delete("wilquant.ai.test")
    assert not store.exists("wilquant.ai.test")
    with pytest.raises(ProviderFailure):
        store.set("broker.test", "secret")


def test_usage_rejects_inconsistent_reported_values():
    from pydantic import ValidationError

    from quant_lab.ai_provider_protocol import ProviderUsage

    with pytest.raises(ValidationError):
        ProviderUsage(prompt_tokens=2, completion_tokens=3, total_tokens=10)
    with pytest.raises(ValidationError):
        ProviderUsage(prompt_tokens=2, cached_prompt_tokens=3)


def test_structured_redaction_covers_escaped_secret():
    from quant_lab.ai_provider_host.secrets import redact_json

    secret = 'key"with\\escapes'
    data = {"content": secret, "nested": [{"reasoning_content": secret}]}
    result = redact_json(data, [secret])
    assert result == {"content": "[REDACTED]", "nested": [{"reasoning_content": "[REDACTED]"}]}


def test_redaction_sensitive_keys_and_json_content():
    import json

    from quant_lab.ai_provider_host.secrets import redact_json

    keys = [
        "api_key",
        "apiKey",
        "access_token",
        "accessToken",
        "client_secret",
        "Authorization",
        "credential",
        "cookie",
    ]
    value = {key: "hidden" for key in keys}
    result = redact_json({"content": json.dumps(value), "nested": value}, [])
    assert "hidden" not in json.dumps(result)
    assert all(item == "[REDACTED]" for item in json.loads(result["content"]).values())


def test_cli_help_has_no_key_argument_and_import_isolation():
    result = subprocess.run(
        [sys.executable, "-m", "quant_lab.ai_provider_host", "--help"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "set-credential" in result.stdout
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import quant_lab.ai_provider_host; import sys; "
            'assert not any(m.startswith(("sqlalchemy", "sqlite3", "duckdb", '
            '"quant_lab.ai.", "quant_lab.paper", "quant_lab.execution")) for m in sys.modules)',
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.skipif(os.name != "nt", reason="Windows ACL integration")
def test_token_created_private_rotated_and_owned_cleanup(tmp_path):
    from quant_lab.ai_provider_host.token_file import HostTokenFile

    path = tmp_path / ".secrets" / "host.token"
    first = HostTokenFile(path)
    token = first.create()
    assert len(bytes.fromhex(token)) == 32
    assert first.read() == token
    with pytest.raises(ProviderFailure):
        HostTokenFile(path).create()
    first.close()
    assert not path.exists()
    second = HostTokenFile(path)
    assert second.create() != token
    second.close()


@pytest.mark.skipif(os.name != "nt", reason="Windows ACL integration")
def test_token_verification_failure_cleans_only_its_new_file(tmp_path, monkeypatch):
    from quant_lab.ai_provider_host.token_file import HostTokenFile

    path = tmp_path / ".secrets" / "host.token"
    instance = HostTokenFile(path)

    def fail_read():
        raise ProviderFailure("TOKEN_ACL_INVALID")

    monkeypatch.setattr(instance, "read", fail_read)
    with pytest.raises(ProviderFailure):
        instance.create()
    assert not path.exists()
    owner = HostTokenFile(path)
    original = owner.create()
    with pytest.raises(ProviderFailure):
        HostTokenFile(path).create()
    assert owner.read() == original
    owner.close()


@pytest.mark.skipif(os.name != "nt", reason="Windows ACL integration")
def test_native_post_creation_acl_failure_cleans_token(tmp_path, monkeypatch):
    import quant_lab.ai_provider_host.token_file as module

    instance = module.HostTokenFile(tmp_path / ".secrets" / "host.token")
    monkeypatch.setattr(module, "_ACL_SCRIPT", module._ACL_SCRIPT + "\nthrow 'verify failed'\n")
    with pytest.raises(ProviderFailure):
        instance.create()
    assert not instance.path.exists()
