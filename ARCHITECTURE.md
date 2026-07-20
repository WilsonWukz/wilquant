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

## Windows 与本地数据

项目脚本只使用项目级虚拟环境和本地依赖，不修改系统执行策略或全局环境。开发进程的 PID 保存在项目内，停止脚本校验进程后只终止本项目进程。

当前仓库位于 OneDrive 同步目录。SQLite、DuckDB 和 Parquet 运行文件默认不提交，并允许通过配置将运行目录迁移到非同步本地磁盘，以降低同步引起的文件锁和原子写入风险。

## 设计记录

Phase 0–1 的完整决策、表规划、阶段顺序和风险分析见 `docs/superpowers/specs/2026-07-20-phase-0-1-foundation-design.md`。
