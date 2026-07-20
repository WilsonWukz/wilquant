# Personal A-Share Quant Lab Architecture

## 架构原则

本项目是面向个人 A 股研究、回测、模拟交易和复盘的本地模块化单体。设计优先级为：正确性、资金安全、可追溯性、可测试性、可解释性、易用性、界面美观、策略收益。

项目不是高频交易平台、自动荐股系统或无人监管实盘系统。Phase 0–5 不实现任何真实券商交易能力。

## 系统边界

```text
React Web
    ↓ HTTP API
FastAPI Modular Monolith
    ├── Configuration and Runtime Guards
    ├── Market Data
    ├── Strategy and Backtest
    ├── Portfolio and Risk
    ├── Execution Adapters
    ├── Journal and Audit
    └── AI Assistant
         ↓
SQLite                 Parquet + DuckDB
事务与控制状态          行情与分析数据
```

开发时前后端分别启动。页面只能通过 API 访问系统能力，不能直接访问数据库。

## 存储边界

SQLite 保存配置、策略版本、回测记录、信号、订单意图、风险决定、模拟订单、成交、持仓批次、复盘和审计记录。Alembic 只管理 SQLite 迁移。

Parquet 保存行情、交易日历、标的信息、公司行为和数据质量明细；DuckDB 提供分析查询。DuckDB 不承担订单、资金或持仓的事务状态。

两个数据平面通过稳定的 `instrument_id`、`data_version` 和导入批次 ID 关联，不建立跨数据库外键。

## 交易安全数据流

```text
Market Data
    ↓
Strategy Engine
    ↓
Signal
    ↓
OrderIntent
    ↓
Deterministic Risk Engine
    ↓
Order Preview
    ↓
Human Confirmation
    ↓
BrokerAdapter
    ↓
BrokerOrder → Fill
    ↓
Position Reconciliation
    ↓
Journal and Audit
```

策略不得直接访问 Broker。AI 不得持有 BrokerAdapter，也不得绕过确定性风控和人工确认。订单意图、风险决定、券商订单和成交是独立对象。

## 运行模式

- `RESEARCH`：默认模式，只允许数据研究、策略和回测能力；
- `PAPER`：Phase 5 才能启用，只连接 MockBroker 或 PaperBroker；
- `LIVE`：第一版不可用，配置或 API 请求都必须明确拒绝。

实盘能力未来不能由单个布尔值开启，必须同时经过环境、配置、界面、API、能力检测、确定性风控和人工确认等独立门禁。

## Phase 1 边界

Phase 1 仅实现：

- FastAPI 后端与 React 状态页；
- Pydantic 配置和结构化日志；
- SQLite、Alembic 与最小 `app_metadata` 表；
- DuckDB 连接健康检查；
- `/api/v1/health/live` 和 `/api/v1/health/ready`；
- Windows 本地启动、测试和安全停止脚本；
- 基础自动化测试与运行文档。

Phase 1 不实现行情、策略、回测、订单、模拟交易、AI 或 QMT 业务代码。

### 已实现的 Phase 1 请求链路

```text
React SystemStatusPage
    ↓ GET /api/v1/health/ready
FastAPI health router
    ↓
HealthService
    ├── SQLAlchemy SQLite SELECT 1
    └── DuckDB SELECT 1
```

后端采用 `backend/src/quant_lab` 包布局。应用模块导入不会创建数据库；SQLite引擎和DuckDB探针在FastAPI生命周期内初始化。`/api/v1/health/live`不依赖数据库，`/api/v1/health/ready`在任一依赖失败时返回脱敏的HTTP 503。

Windows启动脚本直接保存Uvicorn Python进程和Vite Node进程的PID。停止脚本同时核验仓库路径与服务标识，无法确认归属时拒绝停止。

## Windows 与本地数据

项目脚本只使用项目级虚拟环境和本地依赖，不修改系统执行策略或全局环境。开发进程的 PID 保存在项目内，停止脚本校验进程后只终止本项目进程。

当前主项目位于非 OneDrive 目录。SQLite、DuckDB 和 Parquet 运行文件默认不提交；其他部署若位于 OneDrive 等同步目录，可通过配置把运行数据放到非同步本地磁盘，以降低文件锁和原子写入风险。配置变化不会自动移动或删除旧运行文件。

## 设计记录

Phase 0–1 的完整决策、表规划、阶段顺序和风险分析见 `docs/superpowers/specs/2026-07-20-phase-0-1-foundation-design.md`。

## Phase 2A 数据基础

Phase 2A 的导入链路独立于任何交易运行时：

```text
Browser upload
    ↓ controlled staging + SHA-256
MarketDataProvider (CSV / Parquet / Synthetic)
    ↓ raw rows + explicit column mapping
Normalization
    ↓ typed InstrumentId + Bar
Data Quality Validation
    ├── SQLite: source, batch, issue and instrument metadata
    └── Preview response: accepted samples and issue summary

Future publish step
    ↓
Partitioned Parquet
    ↓
DuckDB analytical views
```

SQLite 是导入控制面的事实来源，但不保存逐根 K 线。行情数据发布后使用分区 Parquet，DuckDB 只负责分析查询；三者通过稳定的批次 ID、标的 ID 和未来的数据版本关联。上传暂存区不是长期数据仓库，Phase 2A 不删除或覆盖用户源文件，也不自动发布有问题的数据。

`QUANT_LAB_RUNTIME_ROOT` 为 SQLite、DuckDB、日志、PID 和上传暂存区提供统一的非同步运行根目录。所有 Provider 都必须通过相同的规范化与质量管道，不能直接写交易状态或绕过质量检查。

vn.py 目前只是未安装、未验证的候选基础设施，不是已选定的唯一交易运行时，也未获准进入 Phase V1。若未来明确选择 vn.py，[ADR-0001](docs/ADR-0001-vnpy-runtime-boundary.md) 已批准它必须在独立本地进程运行；FastAPI 仍拥有业务领域、数据管理、策略版本、风险审批、审计、复盘和 Web API。直接 QMT/XtQuant 或其他官方能力的独立 Adapter 仍是可选方案。无论采用何种运行时，都只能作为新的 `MarketDataProvider` 或 Broker Runtime 接入，不能成为历史存储和质量管道的唯一来源。Phase 2B、Phase 2C 的数据工作优先级不变，当前系统仍只有 RESEARCH 模式。
