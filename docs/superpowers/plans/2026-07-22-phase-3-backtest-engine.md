# Phase 3 Trustworthy A-Share Backtest Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 `dev` 分支构建可重复、不可变、遵守 A 股日线交易规则的事件驱动回测闭环，不接入 Broker、PAPER、LIVE 或网络行情。

**Architecture:** BacktestRun 在 SQLite 中冻结 MarketDataSnapshot、策略规范和配置 fingerprint；BacktestEngine 通过 MarketDataService 读取冻结快照，按 TradingCalendarVersion 驱动日线事件，生成 OrderIntent、模拟订单、成交、持仓、现金和净值。最终结果先写 runtime-root 下的 staging 目录，校验 manifest 与 SHA-256 后原子提升，并在 SQLite 标记 SUCCEEDED。

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy/SQLite, DuckDB read-only, PyArrow/Parquet, React/TypeScript, pytest, mypy, Ruff, Vitest.

---

### Task 1: Baseline and domain contracts

**Files:**
- Create: `backend/src/quant_lab/backtest/domain.py`
- Create: `backend/src/quant_lab/backtest/fingerprints.py`
- Test: `backend/tests/backtest/test_domain.py`

- [ ] Define typed enums and dataclasses for BacktestRunStatus, OrderIntent, SimulatedOrder, SimulatedFill, PositionLot, EquityPoint, and frozen run inputs.
- [ ] Reuse existing canonical JSON/fingerprint helpers where possible; ensure strategy and config fingerprints exclude runtime timestamps and IDs.
- [ ] Add deterministic tests for input fingerprints and order/lot state transitions.

### Task 2: Immutable BacktestRun persistence

**Files:**
- Create: `backend/alembic/versions/20260722_0007_create_backtests.py`
- Create: `backend/src/quant_lab/backtest/persistence.py`
- Create: `backend/src/quant_lab/backtest/repository.py`
- Test: `backend/tests/backtest/test_persistence.py`

- [ ] Add BacktestRun and BacktestArtifact tables with relative paths, RESTRICT foreign keys, and triggers preventing updates/deletes after SUCCEEDED.
- [ ] Claim a run by freezing the full snapshot JSON, strategy/config JSON and fingerprints in one transaction.
- [ ] Persist only metadata and artifacts in SQLite; never create a daily-bar SQLite table.
- [ ] Verify empty upgrade, single head, downgrade/upgrade, idempotent claim, and immutable SUCCEEDED behavior.

### Task 3: A-share rule services

**Files:**
- Create: `backend/src/quant_lab/backtest/rules.py`
- Create: `backend/src/quant_lab/backtest/fees.py`
- Create: `backend/src/quant_lab/backtest/planner.py`
- Test: `backend/tests/backtest/test_rules.py`
- Test: `backend/tests/backtest/test_planner.py`

- [ ] Implement lot-size rounding, one-lot minimum, cash sufficiency, non-negative cash, T+1 PositionLot sellable dates, stock/ETF fee policies, directional tick slippage, price limits, and max volume participation.
- [ ] Make missing metadata and unsupported assumptions fail closed with stable error codes.
- [ ] Make sell intents precede buy intents and keep planning deterministic.

### Task 4: Event-driven engine and reference strategies

**Files:**
- Create: `backend/src/quant_lab/backtest/engine.py`
- Create: `backend/src/quant_lab/backtest/strategies.py`
- Test: `backend/tests/backtest/test_engine.py`
- Test: `backend/tests/backtest/test_strategies.py`

- [ ] Drive only explicit open calendar sessions and load bars through MarketDataService and frozen snapshot metadata.
- [ ] Process prior-close signals at next open; execute pending orders before generating today’s close signal; never use future bars.
- [ ] Implement deterministic BuyAndHold and TopNMomentumRotation with sell-before-buy rebalance ordering.
- [ ] Handle missing bars, suspended/open-invalid bars, no-next-session expiry, limit-up/down rejection and partial fills without fabricating prices.

### Task 5: Artifacts, metrics, and restart-safe results

**Files:**
- Create: `backend/src/quant_lab/backtest/artifacts.py`
- Create: `backend/src/quant_lab/backtest/metrics.py`
- Test: `backend/tests/backtest/test_artifacts.py`
- Test: `backend/tests/backtest/test_metrics.py`

- [ ] Write orders, fills, positions, equity_curve, metrics and manifest to a run-specific staging directory.
- [ ] Close handles, hash and count every artifact, atomically promote to final relative path, then commit SQLite success metadata.
- [ ] Compute required return, volatility, Sharpe, drawdown, turnover, fees, exposure and trade metrics with nulls for insufficient samples.
- [ ] Reopen artifacts after a new service instance and verify identical fingerprints and values.

### Task 6: Backtest service and API

**Files:**
- Create: `backend/src/quant_lab/backtest/service.py`
- Create: `backend/src/quant_lab/api/backtests.py`
- Create: `backend/src/quant_lab/api/backtest_schemas.py`
- Modify: `backend/src/quant_lab/main.py`
- Test: `backend/tests/backtest/test_api.py`

- [ ] Validate RESEARCH mode, READY profile health, calendar/dataset coverage, dates, cash and numeric bounds.
- [ ] Reject code/Python/SQL strategy payloads; accept only the two built-in strategy specifications.
- [ ] Expose POST/list/detail/metrics/equity/orders/fills/positions routes with stable errors and run status.
- [ ] Ensure repeated identical inputs produce the same run input fingerprint and immutable result metadata.

### Task 7: Minimal research UI and final acceptance

**Files:**
- Create: `frontend/src/pages/BacktestsPage.tsx`
- Create: `frontend/src/pages/BacktestsPage.test.tsx`
- Create: `frontend/src/services/backtests.ts`
- Create: `frontend/src/types/backtests.ts`
- Modify: `frontend/src/App.tsx`

- [ ] Add `/backtests` profile/strategy/config form with validation, duplicate-submit protection, run list, status/error, snapshot/version display and result tables.
- [ ] Do not add charts, code editors, optimization, broker controls or live actions.
- [ ] Run the formal helper, complete backend pytest, Ruff, mypy, Vitest, TypeScript, Vite build, migration checks, runtime smoke, diff check and clean-worktree verification once after all changes.

