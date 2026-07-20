# Phase 1 Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a locally runnable and testable FastAPI + React foundation with guarded RESEARCH mode, SQLite/Alembic, DuckDB, structured logging, health checks, and safe Windows scripts.

**Architecture:** Use a monorepo modular monolith with a `src/quant_lab` Python package and a separately developed React SPA. SQLite is the transactional control plane; DuckDB is initialized only as an analytical dependency health check. Phase 1 exposes no market-data, strategy, backtest, broker, PAPER, or LIVE capability.

**Tech Stack:** Python 3.11–3.13, uv, FastAPI, Pydantic Settings, SQLAlchemy 2, Alembic, DuckDB, pytest, httpx, Ruff, mypy, React, TypeScript, Vite, Vitest, Testing Library, npm, PowerShell.

---

## File map

### Repository and documentation

- `.gitignore`: exclude environments, runtime databases, logs, PID files, caches, frontend build output, and real local configuration.
- `.env.example`: document non-secret development defaults; keep RESEARCH as the only enabled mode.
- `README.md`: installation, startup, testing, health-check, storage, limitations, and safety instructions verified against actual commands.
- `scripts/common.ps1`: project-root resolution, executable lookup, port checks, PID validation, and safe process helpers.
- `scripts/bootstrap.ps1`: create the root `.venv`, install locked backend dependencies, and install locked frontend dependencies.
- `scripts/dev.ps1`: reject occupied ports, start only this project's processes, and record their PIDs.
- `scripts/test.ps1`: run backend checks, frontend tests, and frontend build.
- `scripts/stop.ps1`: validate saved PIDs and stop only matching project processes.

### Backend

- `backend/pyproject.toml`: package metadata, runtime/dev dependencies, pytest, Ruff, and mypy settings.
- `backend/src/quant_lab/__init__.py`: expose the application version.
- `backend/src/quant_lab/core/config.py`: typed settings, paths, CORS origins, and runtime-mode rejection.
- `backend/src/quant_lab/core/logging.py`: JSON formatter and idempotent logging configuration.
- `backend/src/quant_lab/db/sqlite.py`: SQLAlchemy model metadata, engine creation, and SQLite probe.
- `backend/src/quant_lab/db/duckdb.py`: DuckDB connection factory and probe.
- `backend/src/quant_lab/health/service.py`: component-health aggregation without sensitive details.
- `backend/src/quant_lab/api/health.py`: liveness and readiness routes.
- `backend/src/quant_lab/api/schemas.py`: typed health response models.
- `backend/src/quant_lab/main.py`: FastAPI factory, lifespan, logging, CORS, and router wiring.
- `backend/alembic.ini`: migration configuration with runtime URL supplied by `env.py`.
- `backend/alembic/env.py`: load SQLAlchemy metadata and settings.
- `backend/alembic/versions/20260720_0001_create_app_metadata.py`: initial `app_metadata` migration.
- `backend/tests/conftest.py`: isolated temporary settings and app fixtures.
- `backend/tests/test_config.py`: RESEARCH defaults, path resolution, and PAPER/LIVE rejection.
- `backend/tests/test_logging.py`: JSON log shape and secret-free output.
- `backend/tests/test_sqlite.py`: initial migration and SQLite probe.
- `backend/tests/test_duckdb.py`: healthy and failed DuckDB probes.
- `backend/tests/test_health_api.py`: liveness, readiness, degraded dependency, and response-redaction behavior.

### Frontend

- `frontend/package.json` and `frontend/package-lock.json`: locked React/Vite/test dependencies and scripts.
- `frontend/tsconfig*.json`, `frontend/vite.config.ts`, `frontend/vitest.config.ts`: strict TypeScript, Vite, and jsdom tests.
- `frontend/index.html`: Vite entry document with Chinese locale.
- `frontend/src/types/health.ts`: health response contract.
- `frontend/src/services/health.ts`: typed health API request with explicit error handling.
- `frontend/src/components/StatusCard.tsx`: reusable component status card.
- `frontend/src/pages/SystemStatusPage.tsx`: Chinese Phase 1 status page with risk-first unavailable states.
- `frontend/src/App.tsx`, `frontend/src/main.tsx`, `frontend/src/styles.css`: application entry and restrained light theme.
- `frontend/src/pages/SystemStatusPage.test.tsx`: loading, healthy, and unavailable UI tests.

## Task 1: Repository guardrails and backend settings

**Files:**
- Create: `.gitignore`
- Create: `.env.example`
- Create: `backend/pyproject.toml`
- Create: `backend/src/quant_lab/__init__.py`
- Create: `backend/src/quant_lab/core/__init__.py`
- Create: `backend/src/quant_lab/core/config.py`
- Create: `backend/tests/test_config.py`

- [ ] **Step 1: Create dependency metadata and repository exclusions**

Declare Python `>=3.11,<3.14`, runtime dependencies `fastapi`, `uvicorn`, `pydantic-settings`, `sqlalchemy`, `alembic`, and `duckdb`, plus development dependencies `pytest`, `pytest-cov`, `httpx`, `ruff`, and `mypy`. Configure package discovery from `src`, pytest from `backend/tests`, Ruff for Python 3.11, and strict mypy for `quant_lab`.

Exclude exactly these runtime classes from Git:

```gitignore
.env
.venv/
.uv-cache/
__pycache__/
.pytest_cache/
.ruff_cache/
.mypy_cache/
.coverage
htmlcov/
*.py[cod]
*.db
*.db-shm
*.db-wal
*.duckdb
*.duckdb.wal
data/raw/
data/normalized/
data/parquet/
logs/
.run/
frontend/node_modules/
frontend/dist/
```

- [ ] **Step 2: Synchronize backend dependencies**

Run from the repository root:

```powershell
$env:UV_PROJECT_ENVIRONMENT = (Join-Path $PWD '.venv')
$env:UV_CACHE_DIR = (Join-Path $PWD '.uv-cache')
uv sync --project backend --all-groups
```

Expected: root `.venv` and `backend/uv.lock` are created; no global Python package is installed.

- [ ] **Step 3: Write failing settings tests**

```python
from pathlib import Path

import pytest
from pydantic import ValidationError

from quant_lab.core.config import RunMode, Settings


def test_defaults_to_research_with_project_local_paths(tmp_path: Path) -> None:
    settings = Settings(project_root=tmp_path)
    assert settings.run_mode is RunMode.RESEARCH
    assert settings.sqlite_path == tmp_path / "data" / "quant_lab.db"
    assert settings.duckdb_path == tmp_path / "data" / "analytics.duckdb"


@pytest.mark.parametrize("mode", ["PAPER", "LIVE"])
def test_phase_one_rejects_non_research_modes(tmp_path: Path, mode: str) -> None:
    with pytest.raises(ValidationError, match="RESEARCH"):
        Settings(project_root=tmp_path, run_mode=mode)
```

- [ ] **Step 4: Run tests and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/test_config.py -q
```

Expected: collection fails because `quant_lab.core.config` does not exist.

- [ ] **Step 5: Implement typed settings and runtime guard**

Implement `RunMode` as a string enum with `RESEARCH`, `PAPER`, and `LIVE`, but validate that Phase 1 accepts only `RESEARCH`. Resolve relative SQLite, DuckDB, log, and PID paths under `project_root`; parse CORS origins as a list; set environment prefix `QUANT_LAB_`; ignore unknown variables; and expose `ensure_runtime_directories()` that creates only configured runtime directories.

The public constructor must support this contract:

```python
settings = Settings(project_root=Path.cwd())
settings.ensure_runtime_directories()
assert settings.run_mode is RunMode.RESEARCH
```

- [ ] **Step 6: Run targeted tests and quality checks**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/test_config.py -q
.\.venv\Scripts\python.exe -m ruff check backend/src backend/tests
.\.venv\Scripts\python.exe -m mypy backend/src
```

Expected: all commands exit 0.

- [ ] **Step 7: Commit Task 1**

```powershell
git add .gitignore .env.example backend/pyproject.toml backend/uv.lock backend/src backend/tests/test_config.py
git commit -m "chore: scaffold guarded backend settings"
```

## Task 2: Structured logging

**Files:**
- Create: `backend/src/quant_lab/core/logging.py`
- Create: `backend/tests/test_logging.py`

- [ ] **Step 1: Write a failing JSON logging test**

```python
import json
import logging

from quant_lab.core.logging import configure_logging


def test_log_record_is_structured_json(capsys) -> None:
    configure_logging(level="INFO")
    logging.getLogger("quant_lab.test").info(
        "database ready", extra={"event": "sqlite.ready", "correlation_id": "test-1"}
    )
    record = json.loads(capsys.readouterr().err)
    assert record["level"] == "INFO"
    assert record["event"] == "sqlite.ready"
    assert record["correlation_id"] == "test-1"
    assert record["message"] == "database ready"
    assert "timestamp" in record
```

- [ ] **Step 2: Run the test and verify RED**

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/test_logging.py -q`

Expected: import fails because `quant_lab.core.logging` does not exist.

- [ ] **Step 3: Implement the JSON formatter**

Create an idempotent `configure_logging(level: str, log_file: Path | None = None)` using standard-library logging. Output `timestamp`, `level`, `logger`, `event`, `message`, `application_version`, and optional `correlation_id`; serialize exceptions as an `exception` field; write UTF-8 JSON lines to stderr and optionally to the configured file. Do not serialize arbitrary `extra` fields or settings objects.

- [ ] **Step 4: Verify logging and backend checks**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/test_logging.py -q
.\.venv\Scripts\python.exe -m ruff check backend/src backend/tests
.\.venv\Scripts\python.exe -m mypy backend/src
```

Expected: all commands exit 0 and the emitted line parses as one JSON object.

- [ ] **Step 5: Commit Task 2**

```powershell
git add backend/src/quant_lab/core/logging.py backend/tests/test_logging.py
git commit -m "feat: add structured application logging"
```

## Task 3: SQLite and Alembic foundation

**Files:**
- Create: `backend/src/quant_lab/db/__init__.py`
- Create: `backend/src/quant_lab/db/sqlite.py`
- Create: `backend/alembic.ini`
- Create: `backend/alembic/env.py`
- Create: `backend/alembic/script.py.mako`
- Create: `backend/alembic/versions/20260720_0001_create_app_metadata.py`
- Create: `backend/tests/test_sqlite.py`

- [ ] **Step 1: Write a failing migration and probe test**

```python
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect

from quant_lab.core.config import Settings
from quant_lab.db.sqlite import create_sqlite_engine, probe_sqlite


def test_initial_migration_creates_app_metadata(tmp_path: Path, monkeypatch) -> None:
    settings = Settings(project_root=tmp_path)
    monkeypatch.setenv("QUANT_LAB_PROJECT_ROOT", str(tmp_path))
    config = Config("backend/alembic.ini")
    command.upgrade(config, "head")
    engine = create_sqlite_engine(settings)
    assert "app_metadata" in inspect(engine).get_table_names()
    assert probe_sqlite(engine) is True
```

- [ ] **Step 2: Run the test and verify RED**

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/test_sqlite.py -q`

Expected: import or migration configuration fails because SQLite/Alembic files do not exist.

- [ ] **Step 3: Implement SQLite engine and initial migration**

Use SQLAlchemy 2 declarative metadata. `app_metadata` has `key` as a bounded string primary key, `value` as text, and `updated_at` as a required timezone-aware timestamp with an application-supplied UTC default. Configure SQLite `check_same_thread=False`, enable foreign keys and busy timeout on connection, and implement `probe_sqlite(engine)` as `SELECT 1` with exceptions propagated to the caller.

`env.py` must replace the configured URL with `Settings().sqlite_url`, use `Base.metadata`, support offline and online migrations, and never print credentials or full settings.

- [ ] **Step 4: Run migration twice and verify idempotence**

Run:

```powershell
$env:QUANT_LAB_PROJECT_ROOT = (Get-Location).Path
.\.venv\Scripts\alembic.exe -c backend/alembic.ini upgrade head
.\.venv\Scripts\alembic.exe -c backend/alembic.ini upgrade head
.\.venv\Scripts\python.exe -m pytest backend/tests/test_sqlite.py -q
```

Expected: both upgrades exit 0; the test finds `app_metadata` and the probe succeeds.

- [ ] **Step 5: Run backend quality checks and commit**

Run Ruff, mypy, and all backend tests. Then:

```powershell
git add backend/alembic.ini backend/alembic backend/src/quant_lab/db backend/tests/test_sqlite.py
git commit -m "feat: initialize sqlite schema with alembic"
```

## Task 4: DuckDB and health aggregation

**Files:**
- Create: `backend/src/quant_lab/db/duckdb.py`
- Create: `backend/src/quant_lab/health/__init__.py`
- Create: `backend/src/quant_lab/health/service.py`
- Create: `backend/tests/test_duckdb.py`

- [ ] **Step 1: Write failing DuckDB probe tests**

```python
from pathlib import Path

import pytest

from quant_lab.db.duckdb import DuckDbStore


def test_duckdb_probe_uses_local_database(tmp_path: Path) -> None:
    store = DuckDbStore(tmp_path / "analytics.duckdb")
    assert store.probe() is True


def test_duckdb_probe_propagates_open_failure(tmp_path: Path) -> None:
    blocked = tmp_path / "blocked"
    blocked.mkdir()
    store = DuckDbStore(blocked)
    with pytest.raises(Exception):
        store.probe()
```

- [ ] **Step 2: Verify RED**

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/test_duckdb.py -q`

Expected: import fails because the DuckDB store does not exist.

- [ ] **Step 3: Implement connection lifecycle and health service**

`DuckDbStore` stores only a `Path`, opens a short-lived connection per operation, runs `SELECT 1`, closes in `finally`, and lets exceptions propagate. Define immutable component results with `name`, `status`, and safe `message`; define `HealthService.readiness()` to probe SQLite and DuckDB independently and return an overall `ready` boolean without paths or exception representations.

- [ ] **Step 4: Verify GREEN and commit**

Run DuckDB tests, all backend tests, Ruff, and mypy. Then:

```powershell
git add backend/src/quant_lab/db/duckdb.py backend/src/quant_lab/health backend/tests/test_duckdb.py
git commit -m "feat: add duckdb and dependency health probes"
```

## Task 5: FastAPI liveness and readiness API

**Files:**
- Create: `backend/src/quant_lab/api/__init__.py`
- Create: `backend/src/quant_lab/api/schemas.py`
- Create: `backend/src/quant_lab/api/health.py`
- Create: `backend/src/quant_lab/main.py`
- Create: `backend/tests/conftest.py`
- Create: `backend/tests/test_health_api.py`

- [ ] **Step 1: Write failing API tests**

```python
def test_liveness_does_not_require_databases(client) -> None:
    response = client.get("/api/v1/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "alive"}


def test_readiness_reports_research_components(client) -> None:
    response = client.get("/api/v1/health/ready")
    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "ready"
    assert body["run_mode"] == "RESEARCH"
    assert {item["name"] for item in body["components"]} == {"sqlite", "duckdb"}


def test_readiness_returns_503_without_leaking_path(unready_client) -> None:
    response = unready_client.get("/api/v1/health/ready")
    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"
    assert "OneDrive" not in response.text
```

- [ ] **Step 2: Verify RED**

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/test_health_api.py -q`

Expected: fixtures and API modules do not exist.

- [ ] **Step 3: Implement API factory and schemas**

Define literal component states `healthy` and `unhealthy`, readiness states `ready` and `not_ready`, and a response containing application version, `RESEARCH` mode, and component list. Create `create_app(settings: Settings | None = None, health_service: HealthService | None = None) -> FastAPI` so tests can inject a failing service. Lifespan creates runtime directories, configures logging, and emits startup/shutdown events. Add localhost CORS origins from settings. Return 503 for non-ready dependencies while keeping the typed response body.

- [ ] **Step 4: Verify API and quality checks**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/test_health_api.py -q
.\.venv\Scripts\python.exe -m pytest backend/tests -q
.\.venv\Scripts\python.exe -m ruff check backend/src backend/tests
.\.venv\Scripts\python.exe -m mypy backend/src
```

Expected: all commands exit 0.

- [ ] **Step 5: Commit Task 5**

```powershell
git add backend/src/quant_lab/api backend/src/quant_lab/main.py backend/tests
git commit -m "feat: expose liveness and readiness endpoints"
```

## Task 6: React system status page

**Files:**
- Create: `frontend/package.json`
- Create: `frontend/package-lock.json`
- Create: `frontend/tsconfig.json`
- Create: `frontend/tsconfig.app.json`
- Create: `frontend/tsconfig.node.json`
- Create: `frontend/vite.config.ts`
- Create: `frontend/vitest.config.ts`
- Create: `frontend/index.html`
- Create: `frontend/src/types/health.ts`
- Create: `frontend/src/services/health.ts`
- Create: `frontend/src/components/StatusCard.tsx`
- Create: `frontend/src/pages/SystemStatusPage.tsx`
- Create: `frontend/src/pages/SystemStatusPage.test.tsx`
- Create: `frontend/src/test/setup.ts`
- Create: `frontend/src/App.tsx`
- Create: `frontend/src/main.tsx`
- Create: `frontend/src/styles.css`

- [ ] **Step 1: Create frontend metadata and install locked dependencies**

Define scripts `dev`, `build`, `test`, and `test:run`. Use React 19, Vite 7, TypeScript 5, Vitest, jsdom, and Testing Library. Configure Vite to proxy `/api` to `http://127.0.0.1:8000`.

Run: `npm.cmd --prefix frontend install`

Expected: `frontend/node_modules` and `frontend/package-lock.json` are created without global installation.

- [ ] **Step 2: Write failing status-page tests**

```tsx
it("shows component health when the backend is ready", async () => {
  vi.spyOn(healthApi, "fetchReadiness").mockResolvedValue(readyResponse);
  render(<SystemStatusPage />);
  expect(screen.getByText("正在检查系统状态…")).toBeInTheDocument();
  expect(await screen.findByText("研究环境已就绪")).toBeInTheDocument();
  expect(screen.getByText("SQLite")).toBeInTheDocument();
  expect(screen.getByText("DuckDB")).toBeInTheDocument();
});

it("prioritizes the unavailable warning", async () => {
  vi.spyOn(healthApi, "fetchReadiness").mockRejectedValue(new Error("unavailable"));
  render(<SystemStatusPage />);
  expect(await screen.findByRole("alert")).toHaveTextContent("系统尚未就绪");
});
```

- [ ] **Step 3: Verify RED**

Run: `npm.cmd --prefix frontend run test:run -- SystemStatusPage.test.tsx`

Expected: test compilation fails because the page and API client do not exist.

- [ ] **Step 4: Implement the typed API client and restrained Chinese UI**

`fetchReadiness(signal?: AbortSignal)` calls `/api/v1/health/ready`, parses JSON, throws a generic Chinese error for non-2xx responses, and never displays raw server exception text. The page fetches once on mount with `AbortController`, displays loading, ready, or alert state, and renders SQLite and DuckDB cards. Use semantic HTML, visible focus states, CSS variables, and a maximum content width; do not add charts, navigation shells, dark mode, or business placeholders in Phase 1.

- [ ] **Step 5: Verify frontend tests and production build**

Run:

```powershell
npm.cmd --prefix frontend run test:run
npm.cmd --prefix frontend run build
```

Expected: tests pass and Vite writes `frontend/dist` without TypeScript errors.

- [ ] **Step 6: Commit Task 6**

```powershell
git add frontend
git commit -m "feat: add phase one system status page"
```

## Task 7: Safe Windows lifecycle scripts

**Files:**
- Create: `scripts/common.ps1`
- Create: `scripts/bootstrap.ps1`
- Create: `scripts/dev.ps1`
- Create: `scripts/test.ps1`
- Create: `scripts/stop.ps1`

- [ ] **Step 1: Write common safety helpers**

`common.ps1` must provide:

```powershell
function Test-ProjectPortAvailable([int]$Port) {
    $listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    return $null -eq $listener
}

function Read-ProjectPid([string]$Name) {
    $pidPath = Join-Path $script:RunDirectory "$Name.pid"
    if (-not (Test-Path -LiteralPath $pidPath)) { return $null }
    [int]$savedProcessId = 0
    if (-not [int]::TryParse((Get-Content -Raw -LiteralPath $pidPath).Trim(), [ref]$savedProcessId)) {
        throw "PID 文件格式无效: $pidPath"
    }
    return $savedProcessId
}

function Save-ProjectPid([string]$Name, [int]$ProcessId) {
    New-Item -ItemType Directory -Force -Path $script:RunDirectory | Out-Null
    Set-Content -LiteralPath (Join-Path $script:RunDirectory "$Name.pid") -Value $ProcessId -Encoding ascii
}

function Test-ProjectProcess([int]$ProcessId, [string]$ExpectedFragment) {
    $process = Get-CimInstance Win32_Process -Filter "ProcessId = $ProcessId" -ErrorAction SilentlyContinue
    if ($null -eq $process) { return $false }
    return $process.CommandLine.Contains($script:ProjectRoot) -and
        $process.CommandLine.Contains($ExpectedFragment)
}
```

Implement them with `Get-NetTCPConnection`, integer-only PID files under `.run`, and `Get-CimInstance Win32_Process`. Reject malformed PID files and verify the command line contains both the repository path and expected backend/frontend fragment.

- [ ] **Step 2: Implement bootstrap and test scripts**

`bootstrap.ps1` checks `uv`, `node`, and `npm.cmd`; sets process-scoped `UV_PROJECT_ENVIRONMENT` and `UV_CACHE_DIR`; runs `uv sync --project backend --all-groups`; then runs `npm.cmd --prefix frontend ci` when a lock exists or `install` otherwise.

`test.ps1` runs backend pytest, Ruff, mypy, frontend Vitest, and frontend build, stopping immediately on any non-zero exit code.

- [ ] **Step 3: Implement safe development start and stop**

`dev.ps1` rejects occupied ports 8000 and 5173, rejects live saved PIDs, starts Uvicorn and npm with hidden windows, redirects logs into `logs`, and writes the exact returned PIDs. It does not start Docker or external infrastructure.

`stop.ps1` reads each PID, verifies repository path plus expected command fragment, calls `Stop-Process -Id <exact pid>`, waits for exit, and removes only that validated PID file. A mismatch produces an error and leaves the process untouched.

- [ ] **Step 4: Parse scripts and scan forbidden commands**

Run:

```powershell
Get-ChildItem scripts\*.ps1 | ForEach-Object {
  [void][scriptblock]::Create((Get-Content -Raw -Encoding UTF8 $_.FullName))
}
rg -n "taskkill|Stop-Process.*-Name|Remove-Item.*-Recurse|ExecutionPolicy" scripts
```

Expected: parsing exits 0 and `rg` finds no forbidden command.

- [ ] **Step 5: Commit Task 7**

```powershell
git add scripts
git commit -m "feat: add safe windows lifecycle scripts"
```

## Task 8: README and end-to-end Phase 1 verification

**Files:**
- Create: `README.md`
- Modify: `ARCHITECTURE.md`
- Modify: `.env.example`

- [ ] **Step 1: Document only verified commands and limitations**

README sections must cover project purpose, Phase 1 scope, prerequisites, bootstrap, development start/stop, direct backend/frontend commands, tests, health endpoints, data directory behavior, RESEARCH/PAPER/LIVE modes, OneDrive warning, troubleshooting for `python` and `npm.ps1`, and an explicit statement that no market-data or broker connection exists.

`.env.example` documents:

```dotenv
QUANT_LAB_RUN_MODE=RESEARCH
QUANT_LAB_API_HOST=127.0.0.1
QUANT_LAB_API_PORT=8000
QUANT_LAB_FRONTEND_ORIGINS=["http://127.0.0.1:5173","http://localhost:5173"]
QUANT_LAB_SQLITE_PATH=data/quant_lab.db
QUANT_LAB_DUCKDB_PATH=data/analytics.duckdb
QUANT_LAB_LOG_LEVEL=INFO
```

- [ ] **Step 2: Run the complete automated suite**

Run: `powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/test.ps1`

Expected: backend pytest, Ruff, mypy, frontend Vitest, and frontend build all exit 0.

- [ ] **Step 3: Apply migrations and start services**

Run:

```powershell
$env:QUANT_LAB_PROJECT_ROOT = (Get-Location).Path
.\.venv\Scripts\alembic.exe -c backend/alembic.ini upgrade head
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/dev.ps1
```

Expected: PID files exist only for this project; ports 8000 and 5173 listen.

- [ ] **Step 4: Verify live services**

Run:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/v1/health/live
Invoke-RestMethod http://127.0.0.1:8000/api/v1/health/ready
Invoke-WebRequest http://127.0.0.1:5173 -UseBasicParsing
```

Expected: liveness is `alive`, readiness is `ready` in `RESEARCH` with healthy SQLite and DuckDB components, and the frontend returns HTTP 200.

- [ ] **Step 5: Stop services safely and verify ports close**

Run:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/stop.ps1
Get-NetTCPConnection -LocalPort 8000,5173 -State Listen -ErrorAction SilentlyContinue
```

Expected: the stop script reports only the recorded backend/frontend PIDs; no listener remains on either port.

- [ ] **Step 6: Review changes and commit Phase 1 documentation**

Run:

```powershell
git diff --check
git status --short
git diff --stat HEAD~1
```

Confirm no `.env`, database, DuckDB, logs, PID files, `node_modules`, build output, or caches are staged. Then:

```powershell
git add README.md ARCHITECTURE.md .env.example
git commit -m "docs: add phase one operating guide"
```

## Completion criteria

- Backend and frontend start on Windows without global dependency installation.
- Liveness and readiness endpoints behave as specified.
- SQLite migration and DuckDB probe are operational.
- Default mode is RESEARCH; PAPER and LIVE are rejected.
- Structured logs contain required fields and no sensitive configuration values.
- Backend tests, Ruff, mypy, frontend tests, and frontend build pass.
- Windows scripts record exact PIDs and stop only validated project processes.
- Tests and demonstrations make no external market-data or broker calls.
- README commands have been exercised successfully.
