"""Full application startup, independent local authorization, and crash recovery."""

import os
import subprocess
import sys

import pytest
from alembic.config import Config
from fastapi.testclient import TestClient

from alembic import command
from quant_lab.ai.provenance import AIProvenanceService
from quant_lab.ai_provider_host.token_file import HostTokenFile
from quant_lab.core.config import Settings
from quant_lab.main import create_app


@pytest.fixture
def startup_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("QUANT_LAB_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("QUANT_LAB_RUNTIME_ROOT", str(tmp_path))
    command.upgrade(Config("backend/alembic.ini"), "head")
    return Settings(project_root=tmp_path, runtime_root=tmp_path, ai_analysis_enabled=True)


def local_client(app):
    return TestClient(app, base_url="http://127.0.0.1:8000", client=("127.0.0.1", 12345))


@pytest.mark.skipif(os.name != "nt", reason="Windows current-user ACL")
def test_full_app_reuses_safe_crash_token_and_keeps_it_after_shutdown(startup_settings):
    settings = startup_settings
    token_file = HostTokenFile(settings.run_directory / "ai-analysis-access" / "token")
    settings.ensure_runtime_directories()
    token = token_file.create()  # Simulate an exited Core, without token cleanup.
    app = create_app(settings)
    with local_client(app) as client:
        assert app.state.ai_analysis_service is not None
        assert app.state.ai_analysis_access_token == token
        assert client.get("/api/v1/ai/analyses/missing").status_code == 401
        assert (
            client.get(
                "/api/v1/ai/analyses/missing",
                headers={
                    "Authorization": "Bearer " + token,
                },
            ).status_code
            == 404
        )
        assert (
            client.get(
                "/api/v1/ai/analyses/missing",
                headers={
                    "Origin": settings.frontend_origins[0],
                },
            ).status_code
            == 401
        )  # Allowed CORS origin is not authentication.
        for extra in ({"Origin": "https://evil.example"}, {"Host": "evil.example"}):
            assert (
                client.get(
                    "/api/v1/ai/analyses/missing",
                    headers={
                        "Authorization": "Bearer " + token,
                        **extra,
                    },
                ).status_code
                == 403
            )
        assert not settings.ai_provider_host_token_path.exists()
        remote = TestClient(app, base_url="http://127.0.0.1:8000", client=("192.0.2.1", 12345))
        try:
            assert (
                remote.get(
                    "/api/v1/ai/analyses/missing",
                    headers={"Authorization": "Bearer " + token},
                ).status_code
                == 403
            )
        finally:
            remote.close()
    assert token_file.read() == token


def test_disabled_full_app_skips_analysis_recovery(startup_settings, monkeypatch):
    calls = []
    monkeypatch.setattr(
        AIProvenanceService,
        "recover_incomplete_runs",
        lambda self, now, **kwargs: calls.append(kwargs),
    )
    startup_settings.ai_analysis_enabled = False
    with local_client(create_app(startup_settings)) as client:
        assert client.get("/api/v1/ai/analyses/missing").status_code == 503
    assert calls == [{"recover_analyses": False}]


@pytest.mark.skipif(os.name != "nt", reason="Windows current-user ACL")
def test_second_full_app_cannot_recover_first_instances_runs(startup_settings, monkeypatch):
    calls = []
    monkeypatch.setattr(
        AIProvenanceService,
        "recover_incomplete_runs",
        lambda self, now, **kwargs: calls.append(kwargs),
    )
    first = create_app(startup_settings)
    with local_client(first):
        assert first.state.ai_analysis_service is not None
        with local_client(create_app(startup_settings)) as second:
            assert second.get("/api/v1/ai/analyses/missing").status_code == 503
        assert first.state.ai_analysis_service is not None
    assert calls == [{"recover_analyses": True}, {"recover_analyses": False}]
    with local_client(create_app(startup_settings)) as restarted:
        assert restarted.app.state.ai_analysis_service is not None


@pytest.mark.parametrize("value", ["invalid", "a" * 64])
def test_unsafe_existing_token_is_never_overwritten(startup_settings, value):
    path = startup_settings.run_directory / "ai-analysis-access" / "token"
    path.parent.mkdir(parents=True)
    path.write_text(value, encoding="ascii")  # Inherited ACL is deliberately unsafe.
    with local_client(create_app(startup_settings)) as client:
        assert client.get("/api/v1/ai/analyses/missing").status_code == 503
    assert path.read_text(encoding="ascii") == value


@pytest.mark.skipif(os.name != "nt", reason="Windows current-user ACL")
def test_failed_startup_releases_lock(startup_settings, monkeypatch):
    original = AIProvenanceService.recover_incomplete_runs

    def fail(self, now, **kwargs):
        raise RuntimeError("injected startup failure")

    monkeypatch.setattr(AIProvenanceService, "recover_incomplete_runs", fail)
    with (
        pytest.raises(RuntimeError, match="injected startup failure"),
        local_client(create_app(startup_settings)),
    ):
        pass
    monkeypatch.setattr(AIProvenanceService, "recover_incomplete_runs", original)
    with local_client(create_app(startup_settings)) as restarted:
        assert restarted.app.state.ai_analysis_service is not None


@pytest.mark.skipif(os.name != "nt", reason="Windows current-user ACL")
def test_os_releases_lock_on_abrupt_process_exit(startup_settings):
    path = startup_settings.run_directory / "ai-analysis-access" / "token"
    startup_settings.ensure_runtime_directories()
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import os,sys; from pathlib import Path; "
            "from quant_lab.ai.analysis_local_access import CoreLocalAccess; "
            "access=CoreLocalAccess(Path(sys.argv[1]), lock_path=Path(sys.argv[2])); "
            "access.acquire(); os._exit(23)",
            str(path),
            str(
                startup_settings.sqlite_path.with_name(
                    f".{startup_settings.sqlite_path.name}.ai-analysis.lock"
                )
            ),
        ],
        capture_output=True,
        timeout=40,
    )
    assert result.returncode == 23, result.stderr.decode(errors="replace")
    token = HostTokenFile(path).read()
    with local_client(create_app(startup_settings)) as restarted:
        assert restarted.app.state.ai_analysis_access_token == token
        assert restarted.app.state.ai_analysis_service is not None


@pytest.mark.skipif(os.name != "nt", reason="Windows current-user ACL")
def test_safe_acl_with_invalid_token_format_fails_closed(startup_settings):
    path = startup_settings.run_directory / "ai-analysis-access" / "token"
    startup_settings.ensure_runtime_directories()
    HostTokenFile(path).create()
    path.write_text("not-a-token", encoding="ascii")
    with local_client(create_app(startup_settings)) as client:
        assert client.get("/api/v1/ai/analyses/missing").status_code == 503
    assert path.read_text(encoding="ascii") == "not-a-token"


@pytest.mark.skipif(os.name != "nt", reason="Windows current-user ACL")
def test_same_database_with_different_run_directory_shares_ownership(startup_settings, monkeypatch):
    calls = []
    monkeypatch.setattr(
        AIProvenanceService,
        "recover_incomplete_runs",
        lambda self, now, **kwargs: calls.append(kwargs),
    )
    other_settings = startup_settings.model_copy(
        update={
            "run_directory": startup_settings.project_root / "other-run",
        }
    )
    with local_client(create_app(startup_settings)) as first:
        assert first.app.state.ai_analysis_service is not None
        with local_client(create_app(other_settings)) as second:
            assert second.app.state.ai_analysis_service is None
    assert calls == [{"recover_analyses": True}, {"recover_analyses": False}]
