# wilquant Architecture

## 架构定位

wilquant 是覆盖行情数据、策略回测、研究分析、AI 证据校验和 PAPER 模拟执行的本地模块化单体。现有运行能力以 CN A-share 为主，领域合同已为 CN/US 严格隔离的 multi-market 演进保留明确边界。

当前系统没有 Broker、LIVE execution、真实账户或真实资金授权。AI-1/AI-2 已稳定；AI-3 新增可选的独立 Provider Host、authenticated localhost IPC、Credential Manager 边界、通用兼容 adapter 与调用审计，已通过最终完整验收（后端 823 / AI 295、前端 48，脚本退出码 0）。Core 仍控制确定性证据和验证，Host 不访问数据库或执行领域。AI-2 历史验收见 `docs/ai-2-contract-closure-acceptance.md`；AI-3 设计与运维分别见 `docs/superpowers/specs/2026-09-10-ai-3-provider-isolation-design.md`、`docs/ai-3-provider-operations.md`。停止在 AI-4 之前。

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
    ├── AI Evidence / Validation / Retrieval Domain
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
- AI ResearchCase、EvidenceRef、EvidencePack、ValidationResult、ResearchCaseDocument、RetrievalSnapshot、Prompt/Model config version、AnalysisRun、AnalysisAttempt、Trace 与 Usage；
- PaperAccount、RiskPolicyVersion、RiskDecision、Session、Intent、Order、Fill、Position、Lot、Snapshot、Ledger、Audit 和 Advance record。

Alembic 只管理 SQLite schema。Paper 的 RiskDecision、Fill、Ledger、Audit 和 RiskPolicyVersion，以及 AI provenance 的不可变记录、身份字段与终态，由数据库 trigger 保护。`ai_research_case_fts` 是唯一例外：它是可从 `ai_research_case_documents` 重建的 derived index，不是历史事实，也不套用 append-only trigger。

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

## AI Evidence / Validation / Retrieval Domain

`quant_lab.ai` 是 AI Research Copilot 的无模型确定性控制面，负责：

- 冻结 multi-market ResearchCase identity、UTC cutoff 与确定性版本绑定；
- 通过显式 registry 和字段 allowlist 把 11 类已批准来源解析为 canonical evidence；
- 冻结 EvidencePack，并区分 market-data cutoff 与 knowledge cutoff；
- 按 Syntax、Schema、Semantic、Grounding、Temporal、Immutable Fact 执行六层校验，Core 重算 DELTA/PERCENT_CHANGE；
- 记录 schema-invalid candidate 中仅用于 retry/forensic 的 `trusted=false` assertion observation；
- 使用固定优先级 ResearchGate 处理确定性违规、缺失/过期证据和不可回答场景；
- 以 ResearchCaseDocument 为 durable input，经 hard filters、structured score、FTS 与 stable tie-break 生成不可变 RetrievalSnapshot；
- 发布不可变 PromptTemplateVersion 与 provider-neutral ModelConfigVersion；
- 记录 AIAnalysisRun、AIAnalysisAttempt、AnalysisTrace、AIUsage 与 append-only validation/retrieval provenance；
- 使用 canonical fingerprint、受控状态转换、append-only triggers 和 restart recovery 保存 provenance。

`ResearchCase.created_at` 是 server-generated immutable `known_at`，`as_of_utc` 是 `case_end_at`；描述旧市场的后导入 case 不会进入更早的 historical knowledge context。CN/US 检索严格隔离，MarketRules 只在分析确实依赖交易规则时成为必要证据。

AI package 不导入 PAPER/LIVE/Gateway/Broker 或 provider network client。API 允许创建 Case/Run、读取 Case/Run/Trace/Usage，并只读查询 EvidencePack、ValidationResult 与 RetrievalSnapshot；不暴露 resolver、validation、attempt 完成、raw content、provider call 或任何执行操作。AI 数据库不可用时只让这些可选 API 返回安全错误，不改变 SQLite/DuckDB readiness，也不影响现有研究、回测或 PAPER。

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
- AI Provider/LLM 调用、AI 对话、诊断、建议或 Agent 工具执行；
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
