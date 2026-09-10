import json
import os
import socket
import subprocess
import time
from pathlib import Path

import pytest


@pytest.mark.skipif(os.name != "nt", reason="Windows process ownership and ACL")
def test_start_preserves_unowned_existing_token(tmp_path):
    from quant_lab.ai_provider_host.token_file import HostTokenFile
    from quant_lab.ai_provider_protocol import EndpointProfile

    runtime = tmp_path / "host"
    profile = tmp_path / "profile.json"
    profile.write_text(
        EndpointProfile(
            profile_id="process",
            model="fake",
            base_url="https://example.com/v1",
            credential_ref="wilquant.ai.test",
        ).model_dump_json()
    )
    token_file = HostTokenFile(runtime / ".secrets" / "ai-provider-host.token")
    original = token_file.create()
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    try:
        with (tmp_path / "output.log").open("w+") as output:
            result = subprocess.run(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(Path("scripts/ai-provider-host.ps1").resolve()),
                    "-Action",
                    "start",
                    "-RuntimeRoot",
                    str(runtime),
                    "-ProfilePath",
                    str(profile),
                    "-Port",
                    str(port),
                    "-Fake",
                ],
                stdout=output,
                stderr=output,
                timeout=45,
            )
        assert result.returncode != 0
        assert token_file.path.exists(), "failed start deleted another owner's token"
        assert token_file.read() == original
        assert not (runtime / "process.json").exists()
    finally:
        token_file.close()


@pytest.mark.skipif(os.name != "nt", reason="Windows exclusive file sharing")
def test_runtime_operations_wait_for_exclusive_lock(tmp_path):
    runtime = tmp_path / "host"
    runtime.mkdir()
    with (runtime / ".operation.lock").open("w+"):
        process = subprocess.Popen(
            [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(Path("scripts/ai-provider-host.ps1").resolve()),
                "-Action",
                "status",
                "-RuntimeRoot",
                str(runtime),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            time.sleep(2)
            assert process.poll() is None, "operation ignored the same-runtime lock"
        except BaseException:
            process.kill()
            process.communicate(timeout=10)
            raise
    stdout, stderr = process.communicate(timeout=15)
    assert process.returncode == 0, stderr
    assert "stopped" in stdout


def test_host_lifecycle_script_exists_and_is_opt_in():
    script = Path("scripts/ai-provider-host.ps1")
    assert script.exists()
    source = script.read_text(encoding="utf-8")
    assert "-WindowStyle Hidden" in source
    assert "CreationDate" in source and "CommandLine" in source
    assert "Get-Process python" not in source
    assert "ai-provider-host.ps1" not in Path("scripts/dev.ps1").read_text()


@pytest.mark.skipif(os.name != "nt", reason="Windows process ownership and ACL")
def test_real_host_start_health_duplicate_stop_rotation(tmp_path):
    from quant_lab.ai_provider_client import AIProviderHostClient
    from quant_lab.ai_provider_protocol import EndpointProfile

    profile = EndpointProfile(
        profile_id="process",
        model="fake",
        base_url="https://example.com/v1",
        credential_ref="wilquant.ai.test",
    )
    profile_path = tmp_path / "profile.json"
    profile_path.write_text(profile.model_dump_json())
    runtime = tmp_path / "host"
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    base = [
        "powershell.exe",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(Path("scripts/ai-provider-host.ps1").resolve()),
        "-RuntimeRoot",
        str(runtime),
    ]

    def invoke(action):
        extra = (
            ["-ProfilePath", str(profile_path), "-Port", str(port), "-Fake"]
            if action == "start"
            else []
        )
        # Windows detached grandchildren can inherit anonymous pipe handles.
        # Use files so completion tracks the PowerShell process, not pipe EOF.
        log = tmp_path / (action + ".output")
        with log.open("w+") as output:
            result = subprocess.run(
                [*base, "-Action", action, *extra],
                stdout=output,
                stderr=output,
                text=True,
                timeout=45,
            )
        result.stderr = log.read_text(errors="replace")
        return result

    token_path = runtime / ".secrets" / "ai-provider-host.token"
    try:
        started = invoke("start")
        assert started.returncode == 0, started.stderr
        first = token_path.read_text()
        client = AIProviderHostClient(f"http://127.0.0.1:{port}", token_path)
        assert client.health()["process_id"] > 0
        assert invoke("start").returncode != 0
        assert token_path.read_text() == first
        # A tampered ownership record must fail closed, not kill the actual host.
        state_path = runtime / "process.json"
        original = state_path.read_text(encoding="utf-8-sig")
        state = json.loads(original)
        state["created_at"] = "wrong"
        state_path.write_text(json.dumps(state), encoding="utf-8")
        assert invoke("stop").returncode != 0
        assert client.health()["process_id"] > 0
        state_path.write_text(original, encoding="utf-8")
        assert invoke("stop").returncode == 0
        assert not token_path.exists()
        assert invoke("start").returncode == 0
        assert token_path.read_text() != first
    finally:
        stopped = invoke("stop")
        assert stopped.returncode == 0, stopped.stderr
