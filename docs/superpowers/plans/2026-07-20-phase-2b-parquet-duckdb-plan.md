# Phase 2B Parquet Publication and DuckDB Query Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish explicitly confirmed Phase 2A previews as immutable, recoverable Parquet DatasetVersions and expose only SQLite-approved PUBLISHED files through bounded DuckDB domain queries.

**Architecture:** Phase 2A remains the single normalization and validation pipeline. Preview persists deterministic replay metadata and a content fingerprint; Publish replays the immutable upload, claims one DatasetVersion in a short SQLite BEGIN IMMEDIATE transaction, validates Parquet and a canonical Manifest in same-volume staging, atomically promotes the version directory, and finalizes SQLite metadata. DuckDB receives only validated file paths for a requested PUBLISHED version and never accepts user SQL.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2, Alembic, SQLite, DuckDB, Parquet, React 19, TypeScript, Vitest, PowerShell.

---

## File map

Create:

- backend/src/quant_lab/market_data/versions.py — all Provider, Schema, normalization, quality and fingerprint versions.
- backend/src/quant_lab/market_data/fingerprints.py — canonical scalar/JSON, issue, Preview and publication fingerprints.
- backend/src/quant_lab/market_data/processing.py — reusable Phase 2A parse, normalize and validate operation.
- backend/src/quant_lab/datasets/domain.py — Dataset, DatasetVersion, DatasetFile and publication status types.
- backend/src/quant_lab/datasets/persistence.py — SQLite ORM for Dataset control-plane objects and audit.
- backend/src/quant_lab/datasets/repository.py — Dataset creation, BEGIN IMMEDIATE claim and finalization.
- backend/src/quant_lab/datasets/manifest.py — canonical Manifest models, serialization and verification.
- backend/src/quant_lab/datasets/parquet_store.py — bounded partition writer, validation and same-volume promotion.
- backend/src/quant_lab/datasets/publication.py — replay gate, state machine, recovery and audit orchestration.
- backend/src/quant_lab/datasets/query.py — bounded DuckDB parameterized market-bar queries.
- backend/src/quant_lab/datasets/errors.py — stable safe publication/query errors.
- backend/src/quant_lab/api/datasets.py and dataset_schemas.py — Dataset, version and Publish API.
- backend/src/quant_lab/api/market_bars.py and market_bar_schemas.py — read-only market-bar API.
- backend/alembic/versions/20260720_0004_create_dataset_publication_control_plane.py.
- backend/tests/datasets/ — fingerprints, migration, repository, Manifest, Parquet, publication, recovery, query and API tests.
- frontend/src/types/datasets.ts and services/datasets.ts.
- frontend/src/pages/DatasetsPage.tsx, DatasetDetailPage.tsx and their tests.
- frontend/src/services/datasets.test.ts.

Modify:

- backend/src/quant_lab/market_data/domain.py — normalized issue value and new ImportBatch statuses.
- backend/src/quant_lab/market_data/providers.py — fixed Provider versions.
- backend/src/quant_lab/market_data/persistence.py — Preview replay metadata and issue fingerprint v2 columns.
- backend/src/quant_lab/market_data/repository.py — transactional Preview metadata persistence.
- backend/src/quant_lab/market_data/service.py — delegate to reusable processing operation.
- backend/src/quant_lab/core/config.py and .env.example — published/staging roots and query limits.
- backend/alembic/env.py and backend/src/quant_lab/main.py — load models and inject publication/query services.
- backend/src/quant_lab/api/data_imports.py and data_schemas.py — return Preview fingerprint and versions.
- existing backend market-data/config/API tests — Phase 2A regression contract.
- frontend/src/App.tsx, pages/DataImportPage.tsx, services/dataImports.ts, types/dataImports.ts and tests.
- frontend/src/styles.css.
- README.md and ARCHITECTURE.md.
- docs/superpowers/specs/2026-07-20-phase-2b-parquet-duckdb-design.md only for corrections discovered during implementation review.

### Task 1: Deterministic fingerprint primitives and reusable processing

**Files:**

- Create: backend/tests/datasets/test_fingerprints.py
- Create: backend/tests/datasets/test_processing.py
- Create: backend/src/quant_lab/market_data/versions.py
- Create: backend/src/quant_lab/market_data/fingerprints.py
- Create: backend/src/quant_lab/market_data/processing.py
- Modify: backend/src/quant_lab/market_data/domain.py
- Modify: backend/src/quant_lab/market_data/providers.py
- Modify: backend/src/quant_lab/market_data/service.py
- Test: backend/tests/market_data/test_import_api.py
- Test: backend/tests/market_data/test_validation.py

- [ ] **Step 1: Write failing issue fingerprint tests**

Create tests proving that severity, code, field, row, canonical raw value and normalized value change the Hash, while localized message, created time and Python exception text do not. Include null versus empty, Unicode NFC and Decimal canonicalization.

~~~python
def test_issue_fingerprint_excludes_localized_message() -> None:
    left = issue_payload(message="最高价错误")
    right = issue_payload(message="High price error")
    assert fingerprint_issue(left) == fingerprint_issue(right)
~~~

- [ ] **Step 2: Write failing Preview fingerprint tests**

Build two equivalent processed batches whose Bars differ only in ingested_at, request ID and batch ID. Assert equal Hash. Then change source order, OHLC, quality status, mapping, summary or a rule version and assert unequal Hash.

- [ ] **Step 3: Verify RED**

Run:

~~~powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/datasets/test_fingerprints.py backend/tests/datasets/test_processing.py -q
~~~

Expected: collection fails because versions, fingerprints and processing modules do not exist.

- [ ] **Step 4: Implement fixed versions and canonical serialization**

Implement explicit constants, Unicode NFC handling, non-exponent Decimal formatting, UTC microsecond timestamps, JSON key ordering and SHA-256 helpers. Reject NaN, Infinity and unsupported objects rather than stringifying them.

- [ ] **Step 5: Extract one processing operation**

Move parse/normalize/validate iteration from MarketDataImportService into a function returning immutable processed rows, issues, statistics and Preview fingerprint. Both Preview and future Publish must call this operation. Do not persist Bars or add a second parser.

- [ ] **Step 6: Verify GREEN and Phase 2A regression**

Run:

~~~powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/datasets/test_fingerprints.py backend/tests/datasets/test_processing.py backend/tests/market_data -q
~~~

Expected: all selected tests pass and repeated Preview remains deterministic.

- [ ] **Step 7: Commit**

~~~powershell
git add backend/src/quant_lab/market_data backend/tests/datasets backend/tests/market_data
git commit -m "feat(data): add deterministic preview fingerprints"
~~~

### Task 2: Alembic 0004 and control-plane persistence

**Files:**

- Create: backend/alembic/versions/20260720_0004_create_dataset_publication_control_plane.py
- Create: backend/src/quant_lab/datasets/__init__.py
- Create: backend/src/quant_lab/datasets/domain.py
- Create: backend/src/quant_lab/datasets/persistence.py
- Modify: backend/alembic/env.py
- Modify: backend/src/quant_lab/market_data/persistence.py
- Create: backend/tests/datasets/test_migration.py
- Create: backend/tests/datasets/test_persistence.py

- [ ] **Step 1: Write failing migration tests**

Test empty database to head, 0003 to 0004, repeated head, and 0004 downgrade to 0003 then upgrade. Assert Preview columns, issue v2 columns, four new tables, unique constraints, RESTRICT foreign keys and triggers.

- [ ] **Step 2: Write failing immutability tests**

Insert FILES_COMMITTED and prove transition to PUBLISHED succeeds. Then prove UPDATE/DELETE of the PUBLISHED DatasetVersion and UPDATE/DELETE of its DatasetFile fail. Prove parent deletion is RESTRICTED rather than cascaded.

- [ ] **Step 3: Verify RED**

~~~powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/datasets/test_migration.py backend/tests/datasets/test_persistence.py -q
~~~

Expected: failures because revision 0004 and Dataset ORM models are absent.

- [ ] **Step 4: Implement revision 0004**

Alter import_batches, migrate issue fingerprint v2 without editing 0001–0003, create datasets, dataset_versions, dataset_files and publication_audits, add all named constraints/indexes, and create narrowly scoped PUBLISHED triggers. Downgrade removes only 0004 objects and restores a valid 0003 structure.

- [ ] **Step 5: Add matching ORM models and import them from Alembic env**

Use no Bar table. All stored file paths are relative strings. All relationships use ON DELETE RESTRICT.

- [ ] **Step 6: Verify GREEN**

~~~powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/datasets/test_migration.py backend/tests/datasets/test_persistence.py backend/tests/market_data/test_persistence.py -q
~~~

- [ ] **Step 7: Commit**

~~~powershell
git add backend/alembic backend/src/quant_lab/datasets backend/src/quant_lab/market_data/persistence.py backend/tests/datasets
git commit -m "feat(data): add dataset publication control plane"
~~~

### Task 3: Persist replayable Preview metadata transactionally

**Files:**

- Modify: backend/src/quant_lab/market_data/repository.py
- Modify: backend/src/quant_lab/market_data/service.py
- Modify: backend/src/quant_lab/api/data_imports.py
- Modify: backend/src/quant_lab/api/data_schemas.py
- Modify: backend/tests/market_data/test_persistence.py
- Modify: backend/tests/market_data/test_import_api.py

- [ ] **Step 1: Add failing Repository and API tests**

Preview one batch and assert source size, canonical mapping, Provider version, all rule versions, statistics, fingerprint and preview_completed_at commit together. Force issue insertion failure and assert none of those fields change.

- [ ] **Step 2: Add failing old-batch compatibility test**

Create a 0003-style PREVIEW_READY batch without replay metadata. Assert it remains readable but its Publish eligibility reports PREVIEW_REQUIRED.

- [ ] **Step 3: Verify RED**

~~~powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/market_data/test_persistence.py backend/tests/market_data/test_import_api.py -q
~~~

- [ ] **Step 4: Extend complete_preview and responses**

Pass one immutable Preview record to Repository.complete_preview, update metadata/statistics/issues in one Session commit, and return fingerprint plus versions in Preview and batch APIs.

- [ ] **Step 5: Verify GREEN**

Run the same command and confirm repeated Preview returns identical statistics, issues and fingerprint.

- [ ] **Step 6: Commit**

~~~powershell
git add backend/src/quant_lab/market_data backend/src/quant_lab/api backend/tests/market_data
git commit -m "feat(data): persist replayable preview metadata"
~~~

### Task 4: Dataset creation API and logical identity

**Files:**

- Create: backend/src/quant_lab/datasets/errors.py
- Create: backend/src/quant_lab/datasets/repository.py
- Create: backend/src/quant_lab/api/datasets.py
- Create: backend/src/quant_lab/api/dataset_schemas.py
- Create: backend/tests/datasets/test_dataset_repository.py
- Create: backend/tests/datasets/test_dataset_api.py
- Modify: backend/src/quant_lab/main.py

- [ ] **Step 1: Write failing identity tests**

Create the same logical_key/type/market/frequency/adjustment/Schema twice with different names. Assert the same Dataset is returned. Change one identity field and assert a different dataset_key. Reject unsafe or empty logical keys.

- [ ] **Step 2: Write failing API tests**

Test POST /api/v1/datasets, GET list and version routes. Assert errors are stable and contain no path or database exception.

- [ ] **Step 3: Verify RED**

~~~powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/datasets/test_dataset_repository.py backend/tests/datasets/test_dataset_api.py -q
~~~

- [ ] **Step 4: Implement canonical dataset_key and create-or-get transaction**

Generate dataset_key from immutable identity only; name and description remain display fields. Publish schemas must contain dataset_id only and must not contain create_dataset.

- [ ] **Step 5: Verify GREEN and OpenAPI route presence**

Run selected tests and inspect app.routes in a unit test for exact /api/v1 paths.

- [ ] **Step 6: Commit**

~~~powershell
git add backend/src/quant_lab/datasets backend/src/quant_lab/api backend/src/quant_lab/main.py backend/tests/datasets
git commit -m "feat(data): add logical dataset registry"
~~~

### Task 5: BEGIN IMMEDIATE publication claim and concurrency

**Files:**

- Modify: backend/src/quant_lab/datasets/repository.py
- Create: backend/tests/datasets/test_publication_claim.py

- [ ] **Step 1: Write failing claim tests**

Assert max(version)+1 is calculated and inserted inside one BEGIN IMMEDIATE transaction. Launch two threads with separate Sessions for the same publication fingerprint; assert one DatasetVersion, one logical version and one batch transition to PUBLISHING.

- [ ] **Step 2: Write failing replay tests**

Assert PUBLISHED returns the existing version, processing returns the existing ID/status, and unique-constraint races are reread rather than exposed as raw IntegrityError.

- [ ] **Step 3: Verify RED**

~~~powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/datasets/test_publication_claim.py -q
~~~

- [ ] **Step 4: Implement claim and frozen time**

Use an explicit SQLite BEGIN IMMEDIATE connection transaction. Freeze publication_claimed_at on first insert. Never allocate versions before acquiring the transaction.

- [ ] **Step 5: Verify GREEN repeatedly**

~~~powershell
1..5 | ForEach-Object { .\.venv\Scripts\python.exe -m pytest backend/tests/datasets/test_publication_claim.py -q }
~~~

All five runs must pass without duplicate versions.

- [ ] **Step 6: Commit**

~~~powershell
git add backend/src/quant_lab/datasets/repository.py backend/tests/datasets/test_publication_claim.py
git commit -m "feat(data): claim dataset versions atomically"
~~~

### Task 6: Canonical Manifest and atomic Parquet store

**Files:**

- Create: backend/src/quant_lab/datasets/manifest.py
- Create: backend/src/quant_lab/datasets/parquet_store.py
- Create: backend/tests/datasets/test_manifest.py
- Create: backend/tests/datasets/test_parquet_store.py
- Modify: backend/src/quant_lab/core/config.py
- Modify: backend/tests/test_config.py
- Modify: .env.example
- Modify: .gitignore

- [ ] **Step 1: Write failing Manifest tests**

Build the same Manifest twice with different current clocks but one frozen publication_claimed_at. Assert identical bytes and Hash. Assert file arrays and warning codes are sorted and no absolute path, environment or final published_at appears.

- [ ] **Step 2: Write failing Parquet tests**

Write accepted/warning Bars across exchange/year partitions. Assert exact Schema, DECIMAL(20,8), UTC timestamp semantics, business-key sort, unique keys, ZSTD files, stable relative names, maximum partition enforcement and successful DuckDB reread.

- [ ] **Step 3: Write failing path/atomicity tests**

Use temp paths containing spaces and Chinese. Reject staging/published roots on different volumes, traversal paths and pre-existing final directories. Inject file lock/rename failure and assert only the exact nonce staging path is eligible for cleanup.

- [ ] **Step 4: Verify RED**

~~~powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/datasets/test_manifest.py backend/tests/datasets/test_parquet_store.py backend/tests/test_config.py -q
~~~

- [ ] **Step 5: Implement Manifest and store**

Use DuckDB only, with typed temporary relations and COPY FORMAT PARQUET COMPRESSION ZSTD. Close writers, reopen every file, verify all invariants, Hash files, finalize Manifest, then use one same-volume directory rename. Do not expose final directories to query code.

- [ ] **Step 6: Verify GREEN**

Run the same tests and inspect git status to confirm no Parquet, DuckDB, manifest or staging artifact entered the repository.

- [ ] **Step 7: Commit**

~~~powershell
git add .env.example .gitignore backend/src/quant_lab/core backend/src/quant_lab/datasets backend/tests/datasets backend/tests/test_config.py
git commit -m "feat(data): write atomic parquet dataset versions"
~~~

### Task 7: Publication orchestration, recovery and audit

**Files:**

- Create: backend/src/quant_lab/datasets/publication.py
- Modify: backend/src/quant_lab/datasets/repository.py
- Modify: backend/src/quant_lab/api/datasets.py
- Modify: backend/src/quant_lab/api/dataset_schemas.py
- Modify: backend/src/quant_lab/main.py
- Create: backend/tests/datasets/test_publication.py
- Create: backend/tests/datasets/test_publication_api.py
- Create: backend/tests/datasets/test_recovery.py

- [ ] **Step 1: Write failing eligibility and stale tests**

Cover missing batch/Preview/source, wrong status, zero accepted, rejected/error/fatal, warning without confirmation, non-RESEARCH, source size/Hash drift, mapping/version/statistics/fingerprint drift. Assert no Parquet and unchanged Preview record.

- [ ] **Step 2: Write failing success and idempotency tests**

Publish a warning-free Preview, then assert PUBLISHED batch/version, Manifest, DatasetFile metadata and audit. Repeat and assert the same version, no new directory/file and idempotent hit audit only.

- [ ] **Step 3: Write failing fault-injection tests**

Inject Parquet write, reread, Manifest, directory rename and final SQLite transaction failures. Assert correct dual state, no PUBLISHED partial result, exact staging cleanup, existing PUBLISHED versions unaffected and original exception preserved when cleanup also fails.

- [ ] **Step 4: Write failing recovery tests**

Simulate valid final directory plus FILES_COMMITTED and failed finalization; retry must verify frozen Manifest/Hashes and complete SQLite. A mismatching directory must return PUBLICATION_RECOVERY_REQUIRED without delete or overwrite.

- [ ] **Step 5: Verify RED**

~~~powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/datasets/test_publication.py backend/tests/datasets/test_publication_api.py backend/tests/datasets/test_recovery.py -q
~~~

- [ ] **Step 6: Implement the state machine**

Keep ImportBatch PUBLISHING across VALIDATING/STAGING/FILES_COMMITTING/FILES_COMMITTED. Finalize DatasetVersion and ImportBatch in one SQLite transaction. Write actor_type on the server; operator_label/request_note are untrusted notes.

- [ ] **Step 7: Verify GREEN**

Run selected tests plus all backend tests. Confirm error responses contain no absolute path, SQL or raw exception.

- [ ] **Step 8: Commit**

~~~powershell
git add backend/src/quant_lab/datasets backend/src/quant_lab/api backend/src/quant_lab/main.py backend/tests/datasets
git commit -m "feat(data): orchestrate recoverable dataset publication"
~~~

### Task 8: DuckDB read-only domain query layer

**Files:**

- Create: backend/src/quant_lab/datasets/query.py
- Create: backend/src/quant_lab/api/market_bars.py
- Create: backend/src/quant_lab/api/market_bar_schemas.py
- Modify: backend/src/quant_lab/main.py
- Create: backend/tests/datasets/test_query.py
- Create: backend/tests/datasets/test_market_bars_api.py

- [ ] **Step 1: Write failing query tests**

Query one explicit PUBLISHED version by instrument and time range; assert stable order/cursor. Test default/max limit, ten-year range, file-count cap, timeout interrupt and invalid cursor.

- [ ] **Step 2: Write failing security tests**

Assert FAILED/STAGING/FILES_COMMITTED are invisible. Reject relative traversal and files outside published root. Prove API accepts no SQL or file path and that service code has no ATTACH/COPY/INSTALL/LOAD route.

- [ ] **Step 3: Verify RED**

~~~powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/datasets/test_query.py backend/tests/datasets/test_market_bars_api.py -q
~~~

- [ ] **Step 4: Implement bounded query templates**

Resolve only DatasetFile rows belonging to the requested PUBLISHED version, validate each path, open a short-lived connection, set resource bounds, run fixed parameterized SQL over read_parquet and interrupt on timeout.

- [ ] **Step 5: Verify GREEN**

Run selected tests and a test that scans OpenAPI for absence of /sql.

- [ ] **Step 6: Commit**

~~~powershell
git add backend/src/quant_lab/datasets/query.py backend/src/quant_lab/api backend/src/quant_lab/main.py backend/tests/datasets
git commit -m "feat(data): add bounded duckdb market bar queries"
~~~

### Task 9: Frontend Dataset, Publish and query workflow

**Files:**

- Create: frontend/src/types/datasets.ts
- Create: frontend/src/services/datasets.ts
- Create: frontend/src/services/datasets.test.ts
- Create: frontend/src/pages/DatasetsPage.tsx
- Create: frontend/src/pages/DatasetsPage.test.tsx
- Create: frontend/src/pages/DatasetDetailPage.tsx
- Create: frontend/src/pages/DatasetDetailPage.test.tsx
- Modify: frontend/src/App.tsx
- Modify: frontend/src/App.test.tsx
- Modify: frontend/src/pages/DataImportPage.tsx
- Modify: frontend/src/pages/DataImportPage.test.tsx
- Modify: frontend/src/services/dataImports.ts
- Modify: frontend/src/types/dataImports.ts
- Modify: frontend/src/styles.css

- [ ] **Step 1: Write failing service tests**

Test exact Dataset create/list/version, Publish and market-bar request bodies and URLs. Publish body must contain dataset_id and no create_dataset/requested_by/SQL/path.

- [ ] **Step 2: Write failing page tests**

Test separate Dataset creation, existing Dataset selection after Preview, fingerprint display, warning confirmation, immutable-version warning, Publish state, version metadata, Manifest summary and bounded query pagination.

- [ ] **Step 3: Verify RED**

~~~powershell
Set-Location frontend
npm.cmd run test:run
~~~

Expected: failures because Dataset services/pages/routes are absent.

- [ ] **Step 4: Implement minimal additive UI**

Preserve Phase 2A inspect/Preview flow. Add Publish only after PREVIEW_READY; add /datasets and /datasets/<id> explicit App branches. Never render SQL input, delete or edit controls.

- [ ] **Step 5: Verify GREEN and build**

~~~powershell
npm.cmd run test:run
npm.cmd run build
Set-Location ..
~~~

- [ ] **Step 6: Commit**

~~~powershell
git add frontend/src
git commit -m "feat(data): add dataset publication workspace"
~~~

### Task 10: Documentation and full acceptance

**Files:**

- Modify: README.md
- Modify: ARCHITECTURE.md
- Review: docs/superpowers/specs/2026-07-20-phase-2b-parquet-duckdb-design.md
- Test: all backend, frontend, migrations and Windows lifecycle scripts.

- [ ] **Step 1: Update operating documentation**

Document explicit Dataset creation, Publish replay verification, relative storage layout, Manifest, recovery states, query limits, RESEARCH-only boundary and all new environment variables. State that no automatic source cleanup or Preview snapshot exists.

- [ ] **Step 2: Run full automated checks**

~~~powershell
git diff --check
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts\test.ps1
~~~

Expected: PowerShell helper tests, all backend tests, Ruff, mypy, all frontend tests, TypeScript and Vite succeed.

- [ ] **Step 3: Run isolated migration matrix**

In a unique F:\tmp directory, verify empty→head, 0003→0004, repeated head and 0004→0003→0004. Inspect tables, triggers and constraints. Remove only the exact verified temp directory afterward.

- [ ] **Step 4: Run isolated end-to-end smoke**

With a unique absolute QUANT_LAB_RUNTIME_ROOT: migrate; start services; create Dataset; upload/inspect/Preview; Publish; repeat Publish; list/detail/query the same DatasetVersion; stop safely; confirm ports 8000/5173 and PID files are gone.

- [ ] **Step 5: Validate paths and scope**

Scan source, config, tests, docs, Git metadata and virtual environment for old OneDrive paths. Test relative/absolute runtime roots plus spaces/Chinese. Scan dependencies and runtime source for vn.py, QMT, XtQuant, Broker, strategy, backtest, PAPER or LIVE implementation.

- [ ] **Step 6: Commit documentation**

~~~powershell
git add README.md ARCHITECTURE.md docs/superpowers/specs/2026-07-20-phase-2b-parquet-duckdb-design.md
git commit -m "docs(data): document immutable dataset publication"
~~~

- [ ] **Step 7: Final read-only audit**

Report branch/HEAD, all local commits, files, migration chain, Dataset models, directory/partition/Manifest examples, atomicity versus durability, idempotency, DuckDB boundary, API/UI, all test results, limitations, clean status and unchanged master/foundation. Do not merge, push or begin Phase 2C/V1.
