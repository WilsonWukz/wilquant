import subprocess
import sys

import pytest


@pytest.mark.parametrize("source", ["environment", "dotenv"])
def test_smoke_database_isolated_from_inherited_configuration(tmp_path, monkeypatch, source):
    from sqlalchemy import text

    from quant_lab import ai_provider_smoke as smoke
    from quant_lab.ai_provider_protocol import EndpointProfile, ProviderCapabilities
    from quant_lab.core.config import Settings

    external = tmp_path / "main.db"
    external.write_bytes(b"existing main database must not be opened")
    original = external.read_bytes()
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("QUANT_LAB_SQLITE_PATH", raising=False)
    if source == "environment":
        monkeypatch.setenv("QUANT_LAB_SQLITE_PATH", str(external))
    else:
        (tmp_path / ".env").write_text(f"QUANT_LAB_SQLITE_PATH={external.as_posix()}\n")
    # Restore all process settings modified by this standalone CLI after the test.
    for key in ("PROJECT_ROOT", "RUNTIME_ROOT"):
        monkeypatch.setenv("QUANT_LAB_" + key, str(tmp_path))
    profile_path = tmp_path / "profile.json"
    profile_path.write_text(
        EndpointProfile(
            profile_id="smoke",
            base_url="https://example.com/v1",
            model="test",
            credential_ref="wilquant.ai.smoke",
            capabilities=ProviderCapabilities(),
        ).model_dump_json()
    )
    audit_root = tmp_path / "audit"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "smoke",
            "--confirm-external-call",
            "--profile",
            str(profile_path),
            "--token-file",
            str(tmp_path / "unused"),
            "--audit-root",
            str(audit_root),
        ],
    )

    class StopBeforeProvider(Exception):
        pass

    def check_database(repository, profile):
        database = Settings().sqlite_path
        assert database.is_relative_to(audit_root)
        with repository.engine.connect() as connection:
            assert (
                connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
                == "20260910_0016"
            )
        raise StopBeforeProvider

    monkeypatch.setattr(smoke, "smoke_context", check_database)
    with pytest.raises(StopBeforeProvider):
        smoke.main()
    assert external.read_bytes() == original


def test_manual_smoke_requires_explicit_confirmation():
    from importlib.util import find_spec

    assert find_spec("quant_lab.ai_provider_smoke") is not None
    result = subprocess.run(
        [sys.executable, "-m", "quant_lab.ai_provider_smoke"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode != 0
    assert "--confirm-external-call" in result.stderr
