# WIL_QUANT Architecture

## 架构定位

WIL_QUANT 是面向个人 A 股研究、回测、PAPER 模拟执行和复盘的本地模块化单体。Phase 0–5 的优先级是正确性、资金与状态一致性、可追溯性、可测试性和可解释性。

当前系统没有 Broker、LIVE execution、真实 credential、真实账户、真实资金授权或 AI runtime integration。

## 当前系统边界

```text
React Web
    ↓ HTTP / JSON
FastAPI Modular Monolith
    ├── Dataset Domain
    ├── MarketData Domain
    ├── Strategy Library
    ├── Backtest Domain
    ├── Research Domain
    ├── Shared ExecutionKernel
    └── Paper Domain
         ├── PaperSession Advance
         ├── Deterministic RiskEngine
         ├── Order / Fill
         ├── Position / PositionLot
         ├── Ledger / Snapshot
         └── Audit
             ↓
        SQLite             Parquet + DuckDB
        事务与控制状态       行情文件与分析查询
```

前端只能通过 FastAPI 使用领域能力，不能直接访问 SQLite、DuckDB 或 Parquet。后端模块在同一进程中运行，但通过明确的 service、repository 和不可变版本 ID 维持领域边界。

## SQLite / Parquet / DuckDB 分工

### SQLite

SQLite 是控制面和事务状态的事实来源，保存：

- 数据源、导入批次、质量问题、Dataset 与 DatasetVersion 元数据；
- TradingCalendarVersion、MarketDataProfile 和标的元数据；
- StrategyDefinition、StrategyVersion、BacktestRun 和结果索引；
- Research experiment、journal 与报告元数据；
- PaperAccount、RiskPolicyVersion、RiskDecision、Session、Intent、Order、Fill、Position、Lot、Snapshot、Ledger、Audit 和 Advance record。

Alembic 只管理 SQLite schema。Paper 的 RiskDecision、Fill、Ledger、Audit 和 RiskPolicyVersion 由数据库 trigger 阻止 UPDATE/DELETE。

### Parquet

Parquet 保存已发布的规范化行情数据。发布采用不可变 DatasetVersion、受控 staging、指纹和文件清单；消费方只能读取已确认发布且校验通过的版本。

### DuckDB

DuckDB 负责对 Parquet 的本地分析查询，不承担资金、订单、成交、持仓或会话事务。SQLite 和 Parquet/DuckDB 通过稳定的 dataset、version、instrument 和 calendar 标识关联，不建立跨数据库外键。

## 数据与市场数据链路

```text
Local CSV / Parquet
    ↓ controlled staging + SHA-256
MarketDataProvider
    ↓ explicit column mapping
Normalization + Quality Rules
    ↓ preview / issues
PublicationService
    ↓ immutable DatasetVersion
Partitioned Parquet
    ↓
DatasetQueryService / DuckDB
    ↓
MarketDataProfile
    ├── bars DatasetVersion
    └── TradingCalendarVersion
```

PaperSession 和 BacktestRun 在创建时记录具体版本或 snapshot。MarketDataProfile 后续改绑不会让历史运行自动漂移，也不能读取目标交易日之后的行情。

## Strategy Library 与 BacktestEngine

StrategyDefinition 是可归档的逻辑定义，StrategyVersion 是不可变执行规格。已有策略类型为 `BUY_AND_HOLD` 和 `TOP_N_MOMENTUM_ROTATION`；策略规格不允许 Python、SQL、表达式或脚本注入。

```text
StrategyVersion
    ↓
BacktestEngine
    ├── MarketDataProfile snapshot
    ├── Trading calendar
    ├── strategy on_close
    └── Shared ExecutionKernel
         ↓
Backtest orders / fills / equity / metrics / artifacts
```

BacktestEngine 负责编排历史交易日、策略状态和回测持久化。价格、滑点、费用、成交量参与率、手数、现金约束、A 股 T+1 和 FIFO lot 等执行语义由 Shared ExecutionKernel 提供。

## Shared ExecutionKernel

`quant_lab.execution` 是回测和 PAPER 共用的确定性执行内核。它接收显式的订单、账户、lot、标的规格、目标交易日 bar、费用和滑点配置，返回不带外部副作用的执行结果。

共享内核的目标是让同一输入产生同一结果，并避免回测与 PAPER 在以下语义上分叉：

- 市价模拟成交；
- 费用、印花税、过户费和滑点；
- 现金不足与非法卖出拒绝；
- 成交量参与率和部分成交；
- T+1 可卖日期；
- FIFO lot consumption 与 realized PnL。

ExecutionKernel 不连接 Broker，也不写数据库。事务性持久化由调用它的 BacktestEngine 或 PaperSessionService 负责。

## Research Domain

Research Domain 消费已完成的 BacktestRun 和不可变策略/数据版本，提供：

- experiment 与多个 run 的组织；
- run comparison；
- diagnostics；
- research report；
- 追加式 research journal。

Research Domain 不修改行情版本、策略版本或执行结果，也不能创建 PaperFill、修改现金或绕过 RiskEngine。

## Paper Domain

### 领域对象

```text
PaperAccount
    ├── RiskPolicy → immutable RiskPolicyVersion
    ├── PaperSession → frozen market-data/config/strategy binding
    ├── Position → PositionLot
    ├── AccountSnapshot
    └── Ledger

OrderIntent
    ↓
immutable RiskDecision
    ↓
PaperOrder
    ↓
immutable PaperFill
```

PaperAccount 保存当前现金、市值和权益。Ledger 是现金变化的追加式记录；PositionLot 是数量、成本、T+1 和 FIFO 的事实来源；Position 是按标的聚合的当前视图；Snapshot 保存每个成功交易日推进后的净值状态。

### PaperSession Advance

`ADVANCE` 是 PAPER 的唯一市场时钟，一次只推进到冻结 TradingCalendarVersion 的下一个开放交易日：

```text
Advance request
    ↓ idempotency + expected version/date
BEGIN IMMEDIATE transaction
    ↓
Execute SUBMITTED orders for target session
    ↓ Shared ExecutionKernel
Persist Fill → Cash → Position/Lot → Ledger → Audit
    ↓
Mark to market using bar <= target
    ↓ Snapshot + stale instrument audit
Run strategy/manual close phase
    ↓ OrderIntent → RiskEngine → RiskDecision → PaperOrder
Update current_session_date/version + completed Advance + Audit
COMMIT
```

若主事务中 Fill、Position、Snapshot 或 Audit 写入失败，主事务整体回滚；随后使用独立失败记录事务把 Session 和 Advance 标为 `FAILED` 并追加 `SESSION_FAILED`。相同幂等键不会重新执行失败操作。

### 确定性 RiskEngine

RiskEngine 只消费显式快照和不可变 RiskPolicyVersion，检查：

- account frozen 状态；
- security type；
- single-order notional；
- cash buffer；
- single-position weight；
- total exposure；
- open-order count；
- daily loss 和 drawdown。

输出是不可变 RiskDecision。触发 hard risk 时，账户变为 `FROZEN`，现有 `APPROVED`/`SUBMITTED` 订单被取消；新 intent 继续产生可审计的拒绝决定。只有显式用户入口可以 unfreeze，且不重置 RiskPolicy、PnL、drawdown 或历史决定。

### 历史一致性

- RiskDecision 永久引用当时的 RiskPolicyVersion；
- PaperSession 永久绑定创建时的 StrategyVersion；
- MarketDataSnapshot 固定 DatasetVersion 和 TradingCalendarVersion；
- execution config JSON 与 fingerprint 在 session 创建时冻结；
- StrategyDefinition 归档或 MarketDataProfile 改绑不改变既有 session 的历史输入。

## API 与前端

FastAPI 暴露稳定的 `/api/v1` HTTP 契约，错误响应使用结构化 `error_code` 和 message。Paper API 覆盖账户、风控策略、冻结/解冻、session 生命周期、advance、manual intent、order cancel，以及 orders/fills/positions/equity/audit/risk decisions 查询。

React 页面包括系统状态、导入、数据集、市场数据、回测、研究和 `/paper`。`PaperPage` 是对正式 API 的操作台，不包含浏览器内执行逻辑或绕过后端风控的路径。

## 运行模式与安全边界

配置层当前只允许 `RESEARCH` 进程模式。PAPER 是本地领域模拟，不代表启用外部交易。

当前运行时代码明确不包含：

- Broker SDK 或 credential loader；
- 真实账户查询或真实 order submission；
- LIVE execution；
- scheduler/background worker；
- AI/LLM/Agent integration；
- 任何可跳过 RiskDecision、直接创建 Fill 或直接改现金的外部路径。

## FUTURE / NOT IMPLEMENTED

以下只是未来设计边界，不是当前能力，也未获准实现：

```text
FastAPI business process
    ↓ approved intent only
ExecutionGateway                       FUTURE / NOT IMPLEMENTED
    ↓ authenticated IPC
Broker process isolation              FUTURE / NOT IMPLEMENTED
    ↓
Official Broker API

Capital Authorization                 FUTURE / NOT IMPLEMENTED
    ├── explicit account scope
    ├── explicit capital limit
    ├── human confirmation
    ├── deterministic risk gates
    ├── Kill Switch
    └── reconciliation
```

未来 ExecutionGateway 不得复用 PaperExecutionEngine 假装实盘，也不得让策略或 AI 持有 Broker 连接。任何 Broker 选型、资本授权和 LIVE 设计都必须在独立阶段重新评审。

## Windows 本地运行

项目脚本使用项目级 `.venv` 和 `frontend/node_modules`，不修改全局 Python 包或系统执行策略。`dev.ps1` 保存精确 PID，`stop.ps1` 核验仓库路径与服务标识后才停止进程。

SQLite、DuckDB、Parquet、日志、PID 和上传目录可通过 `QUANT_LAB_RUNTIME_ROOT` 放入独立本地 runtime。配置变化不会自动移动、覆盖或删除旧数据；自动化测试使用 Windows system TEMP 的 fresh runtime。
