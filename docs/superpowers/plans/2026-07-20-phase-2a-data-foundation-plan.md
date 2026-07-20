# Phase 2A Data Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a secure local CSV/Parquet inspection and preview workflow with typed A-share models, deterministic validation, SQLite metadata, and a minimal React import page.

**Architecture:** Add a `market_data` vertical module inside the existing FastAPI modular monolith. Providers read controlled staged files, normalization and validation stay source-independent, repositories persist only metadata/issues, and preview bars remain ephemeral; React accesses the workflow only through four APIs.

**Tech Stack:** Python 3.12, FastAPI, Pydantic, SQLAlchemy, Alembic, DuckDB, stdlib CSV/Decimal/zoneinfo/hashlib, pytest, React 19, TypeScript, Vitest, PowerShell.

---

## File map

- Modify `core/config.py`, `core/logging.py`, `main.py`, `.env.example`, lifecycle scripts and docs for runtime-root and API wiring.
- Create `market_data/domain.py`, `providers.py`, `normalization.py`, `validation.py`, `persistence.py`, `service.py`, and `errors.py` with one responsibility each.
- Create `api/data_imports.py` and `api/data_schemas.py` for HTTP contracts only.
- Create Alembic revision `20260720_0002_create_market_data_metadata.py`; import models into Alembic metadata.
- Add focused backend tests and repository fixtures under `backend/tests/market_data/`.
- Add `DataImportPage`, typed service/contracts and route tests under `frontend/src/`.

## Task 1: Runtime root

- [ ] Write failing Settings and PowerShell path tests.
- [ ] Verify RED with targeted pytest and `scripts/test_common.ps1`.
- [ ] Implement centralized runtime-root resolution in Python and `scripts/common.ps1`.
- [ ] Verify targeted and existing tests, Ruff and mypy.

## Task 2: Domain, normalization and validation

- [ ] Write failing tests for exchange/symbol normalization, Decimal/date/time semantics and quality rules.
- [ ] Verify RED.
- [ ] Implement immutable domain types, parser and deterministic validator.
- [ ] Verify GREEN; refactor only after all targeted tests pass.

## Task 3: Providers and secure staging

- [ ] Write failing CSV, BOM, Parquet, synthetic, hash, size and original-file-integrity tests.
- [ ] Verify RED.
- [ ] Implement Provider Protocol, CSV/DuckDB-Parquet/Synthetic providers and controlled upload store.
- [ ] Verify GREEN and no-network behavior.

## Task 4: SQLite metadata and migration

- [ ] Write failing empty-database migration and repository tests.
- [ ] Verify RED.
- [ ] Add four SQLAlchemy models, repository and forward-only migration.
- [ ] Verify migration twice, metadata writes and absence of any Bar table.

## Task 5: Import application service and API

- [ ] Write failing service/API tests for inspect, preview, batch lookup, issues, duplicate hash, traversal, extension, size and redaction.
- [ ] Verify RED.
- [ ] Implement state transitions, persistence, safe errors/logging and four routes.
- [ ] Verify GREEN plus RESEARCH/PAPER/LIVE regression tests.

## Task 6: React import preview

- [ ] Write failing route, service and page tests.
- [ ] Verify RED.
- [ ] Implement explicit routes, file inspect/preview flow, results/issues and 404.
- [ ] Verify `/` remains available and no publish/trading controls exist.

## Task 7: Documentation and full verification

- [ ] Update README, ARCHITECTURE and `.env.example` with verified behavior and limitations.
- [ ] Run Alembic on a temporary empty database, full backend tests, Ruff, mypy, frontend tests/build.
- [ ] Start services with an isolated runtime root, smoke-test health/import routes, stop through the safe script, and confirm ports close.
- [ ] Run `git diff --check`, scan forbidden dependencies/code, and provide the requested handoff without merging or pushing.

