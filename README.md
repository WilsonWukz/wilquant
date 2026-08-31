# wilquant

wilquant 是一个覆盖行情数据管理、策略回测、研究分析和 PAPER 模拟执行的量化工作台。它把数据导入、版本发布、策略管理、回测评估、实验比较和模拟交易组织在同一套可追溯工作流中。

## 功能概览

- 导入 CSV 或 Parquet 行情文件，完成列映射、规范化和数据质量检查；
- 发布不可变 DatasetVersion，并通过交易日历和 MarketDataProfile 组织可复现的数据输入；
- 管理不可变 StrategyVersion，运行内置策略并持久化回测结果；
- 比较多次回测，查看诊断结果，生成研究报告和研究日志；
- 使用 PAPER 账户按交易日推进策略或人工委托，模拟订单、成交、持仓和资金变化；
- 冻结 AI Research Copilot 的证据包，执行 grounding、时间截断、事实漂移校验和可审计案例检索；
- 通过版本指纹、事务、幂等请求和追加式审计保存完整运行轨迹。

## 核心工作流

```text
本地行情文件
    ↓ 导入、映射、规范化、质量检查
DatasetVersion + TradingCalendarVersion
    ↓ 组成 MarketDataProfile
StrategyVersion
    ↓
BacktestEngine
    ↓
回测结果、指标与制品
    ↓
Research Workspace
    ↓
实验比较、诊断、报告与日志

MarketDataProfile + StrategyVersion
    ↓
PaperSession
    ↓ ADVANCE
Intent → RiskDecision → PaperOrder → PaperFill
    ↓
持仓、资金、净值、账本与审计
```

所有消费方都显式绑定数据、日历和策略版本。后续发布新数据或更新策略不会改变已经完成的回测和 PAPER 会话输入。

## 主要模块

### 数据与市场数据

- 支持本地 CSV/Parquet 文件导入、SHA-256 校验和受控暂存；
- 支持显式列映射、字段规范化、预览和质量问题记录；
- 将通过检查的数据发布为不可变、分区存储的 Parquet DatasetVersion；
- 使用版本化交易日历、MarketDataProfile、覆盖率和健康检查组织行情；
- SQLite 保存事务与控制状态，DuckDB 负责对 Parquet 执行分析查询。

### 策略与回测

- StrategyDefinition 管理策略定义，StrategyVersion 保存不可变执行规格；
- 内置 `BUY_AND_HOLD` 和 `TOP_N_MOMENTUM_ROTATION` 策略；
- BacktestEngine 按交易日历驱动策略、订单、成交、持仓和净值计算；
- 支持手续费、滑点、成交量参与率、现金约束、A 股 T+1 和 FIFO lot；
- 持久化运行状态、订单、成交、权益曲线、指标和回测制品。

### 研究工作台

- 将多个 BacktestRun 组织为实验；
- 提供运行比较、诊断和结果可比性检查；
- 保存研究报告及追加式研究日志；
- 所有研究结果都引用原始数据、策略和回测版本。

### AI 证据与时间安全校验

- 冻结 ResearchCase 的 market/instrument、market-data cutoff、knowledge cutoff 与版本指纹；
- 通过显式 resolver registry 和字段 allowlist 解析 Dataset、行情快照、策略、回测、研究、PAPER 快照与风控决定；
- 生成不可变 EvidencePack，并按 Syntax、Schema、Semantic、Grounding、Temporal、Immutable Fact 六层校验结构化 claim；
- 使用固定优先级 ResearchGate 输出 `REJECT / WAIT_FOR_EVIDENCE / ABSTAIN / PROCEED`；
- 以 ResearchCaseDocument 作为 durable retrieval input，通过 structured score 与 derived SQLite FTS5 索引生成不可变 RetrievalSnapshot；
- 发布不可变 PromptTemplateVersion 与 provider-neutral ModelConfigVersion；
- 记录 AIAnalysisRun、AIAnalysisAttempt、AnalysisTrace、AIUsage、EvidenceRef、ValidationResult 与检索快照；
- 使用 canonical SHA-256、数据库约束和 triggers 保护身份、终态与 append-only 记录；
- 应用启动时可从 canonical ResearchCaseDocument 重建 FTS；AI 组件不可用不影响 Data、Backtest、PAPER 或系统 readiness。

当前尚未安装 LLM SDK，也没有 Provider Host、模型调用、Copilot 对话或 AI UI。FTS 是可丢弃并重建的索引，不是 provenance 或 source of truth。

### PAPER 模拟执行

- 创建 PAPER 账户、版本化 RiskPolicy 和可恢复的 PaperSession；
- 通过 `ADVANCE` 按开放交易日确定性推进会话；
- 支持策略生成和人工创建 OrderIntent；
- 检查单笔名义金额、仓位、总敞口、现金缓冲、开放订单、日损失和回撤；
- 支持完整成交、部分成交后到期、撤单、拒单、T+1 和 FIFO lot；
- 保存资金、持仓、PositionLot、Fill、Ledger、Snapshot 和 Audit；
- 支持幂等推进、乐观并发、事务回滚以及应用重启后继续运行。

回测与 PAPER 共用纯函数式 ExecutionKernel，从而保持费用、滑点、成交量和 A 股交易规则一致。

## 快速开始

### 环境要求

- Windows 10/11；
- PowerShell 5.1 或更高；
- [uv](https://docs.astral.sh/uv/)；
- Node.js 22 或兼容版本；
- npm 10 或兼容版本。

### 安装依赖

在仓库根目录执行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/bootstrap.ps1
```

脚本会在项目目录创建 `.venv`，并安装 `frontend/node_modules`。

### 初始化数据库

```powershell
$env:QUANT_LAB_PROJECT_ROOT = (Get-Location).Path
.\.venv\Scripts\alembic.exe -c backend/alembic.ini upgrade head
```

当前 Alembic head 为 `20260830_0015`，可以安全地重复执行 `upgrade head`。

### 启动

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/dev.ps1
```

常用入口：

- 工作台：<http://127.0.0.1:5173>
- 数据导入：<http://127.0.0.1:5173/data/import>
- 数据集：<http://127.0.0.1:5173/datasets>
- 市场数据：<http://127.0.0.1:5173/market-data>
- 回测：<http://127.0.0.1:5173/backtests>
- 研究：<http://127.0.0.1:5173/research>
- PAPER：<http://127.0.0.1:5173/paper>
- OpenAPI：<http://127.0.0.1:8000/docs>
- 就绪检查：<http://127.0.0.1:8000/api/v1/health/ready>

停止服务：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/stop.ps1
```

`dev.ps1` 会启动本地 Uvicorn 和 Vite，并将 PID 写入 `.run/`、日志写入 `logs/`。`stop.ps1` 会核验进程所属项目后再停止服务。

## 数据目录与配置

配置统一使用 `QUANT_LAB_` 前缀：

```dotenv
QUANT_LAB_RUN_MODE=RESEARCH
QUANT_LAB_API_HOST=127.0.0.1
QUANT_LAB_API_PORT=8000
QUANT_LAB_RUNTIME_ROOT=
QUANT_LAB_SQLITE_PATH=data/quant_lab.db
QUANT_LAB_DUCKDB_PATH=data/analytics.duckdb
QUANT_LAB_LOG_PATH=logs/quant-lab.jsonl
QUANT_LAB_RUN_DIRECTORY=.run
QUANT_LAB_IMPORT_DIRECTORY=imports/staging
QUANT_LAB_PUBLICATION_STAGING_DIRECTORY=data/publication-staging
QUANT_LAB_PUBLISHED_DIRECTORY=data/published
QUANT_LAB_LOG_LEVEL=INFO
```

默认运行数据位于项目目录。也可以为不同运行实例指定独立目录：

```powershell
$env:QUANT_LAB_RUNTIME_ROOT = 'F:\wilquant-runtime'
```

设置 `QUANT_LAB_RUNTIME_ROOT` 后，SQLite、DuckDB、日志、PID、导入暂存和发布目录都会相对该目录解析。切换配置不会自动移动或删除已有数据。

## 技术架构

```text
React + TypeScript
        ↓ HTTP / JSON
FastAPI
    ├── Dataset Domain
    ├── MarketData Domain
    ├── Strategy / Backtest Domain
    ├── Research Domain
    ├── AI Evidence / Validation / Retrieval Domain
    ├── Shared ExecutionKernel
    └── Paper Domain
        ↓                    ↓
      SQLite          Parquet + DuckDB
```

- React 提供数据、回测、研究和 PAPER 操作页面；
- FastAPI 暴露稳定的 `/api/v1` 与 OpenAPI 契约；
- SQLite 保存控制状态和事务数据；
- Parquet 保存已发布的行情数据；
- DuckDB 提供只读分析查询；
- Alembic 管理 SQLite schema。

更完整的领域边界和数据流见 [ARCHITECTURE.md](ARCHITECTURE.md)。

## 项目结构

```text
backend/src/quant_lab/
    datasets/       数据导入、发布和查询
    market_data/    日历、Profile 和行情消费
    execution/      确定性执行内核
    backtest/       策略库与回测引擎
    research/       实验、诊断、报告和日志
    ai/             AI 案例、证据包、六层校验、ResearchGate、检索快照与 provenance
    paper/          PAPER 会话、风控、订单、持仓和账务
    api/            FastAPI 路由与 HTTP 契约
backend/alembic/    SQLite 迁移
backend/tests/      后端自动化测试
frontend/src/       React 页面、服务与测试
scripts/            安装、启动、停止和质量门禁脚本
```

## 测试

运行完整质量门禁：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/test.ps1
```

门禁包含后端 pytest、Ruff、mypy、前端 Vitest、TypeScript 检查和 Vite 生产构建。

分别运行：

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests -q
.\.venv\Scripts\python.exe -m ruff check backend/src backend/tests backend/alembic
.\.venv\Scripts\python.exe -m mypy backend/src

Set-Location frontend
npm.cmd run test:run
npm.cmd run build
```

## 当前支持范围

wilquant 当前提供数据管理、策略回测、研究分析、AI provenance foundation 和 PAPER 模拟执行。AI provenance 不调用模型，PAPER 使用模拟资金和本地行情推进，系统不会向外部交易通道提交订单。
