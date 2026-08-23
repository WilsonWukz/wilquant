# WIL_QUANT

WIL_QUANT 是一个本地运行的个人 A 股量化研究与 **PAPER 模拟交易终端**。系统覆盖数据导入与发布、市场数据、策略版本、回测、研究工作台，以及带确定性风控和账务审计的 PAPER 执行。

本项目用于研究、验证和复盘，不构成投资建议，也不承诺任何收益。

> **NO BROKER · NO LIVE**
> 当前仓库不连接券商、不读取真实账户、不提交真实订单，也没有任何实盘资金授权能力。

## 当前状态

Phase 0–5 已完成并通过最终验收：

- Phase 0/1：项目设计、FastAPI/React 基础、配置、日志、SQLite、DuckDB 与 Windows 生命周期脚本；
- Phase 2A：受控 CSV/Parquet 导入、规范化与数据质量检查；
- Phase 2B：不可变 DatasetVersion、Parquet 发布与只读查询；
- Phase 2C：TradingCalendarVersion、MarketDataProfile 与数据覆盖检查；
- Phase 3：Strategy Library、BacktestEngine、共享 ExecutionKernel 与回测结果持久化；
- Phase 4：Research Workspace、实验比较、诊断、研究报告与日志；
- Phase 5：PAPER Account、RiskPolicy、PaperSession、订单意图、确定性风控、模拟成交、持仓批次、账本、净值和审计。

Phase 5 里程碑的自动化基线为后端 528 项测试、前端 10 个测试文件/48 项测试，并通过 Ruff、mypy、TypeScript 和 Vite 生产构建。

## 主要能力

### 数据与市场数据

- 受控本地 CSV/Parquet 上传、SHA-256、列映射、规范化与质量问题记录；
- 发布不可变 DatasetVersion 到分区 Parquet，SQLite 保存控制面元数据，DuckDB 执行分析查询；
- 版本化交易日历、MarketDataProfile、覆盖率与健康检查；
- 消费方显式绑定 DatasetVersion 和 TradingCalendarVersion，不跟随后续 profile 变更漂移。

### 策略、回测与研究

- 不可变 StrategyVersion；
- `BUY_AND_HOLD` 与 `TOP_N_MOMENTUM_ROTATION` 内置确定性策略；
- BacktestEngine 与 PAPER 共用 ExecutionKernel 的费用、滑点、成交量参与率和 A 股 T+1 语义；
- 回测运行、指标、成交与制品持久化；
- 实验、对比、诊断、研究报告和研究日志。

### PAPER 模拟交易

- PaperAccount 与版本化、不可变 RiskPolicyVersion；
- PaperSession 生命周期和按开放交易日推进的 `ADVANCE`；
- 策略驱动及人工 OrderIntent；
- 确定性 RiskDecision、名义金额/仓位/敞口/现金缓冲/回撤/日损失等规则；
- 风控冻结、取消 pending order、用户显式解冻；
- 模拟订单、完整成交、部分成交后到期、取消、拒单与 T+1/FIFO lot；
- 资金、持仓、lot、Fill、Ledger、Snapshot 和 Audit 持久化；
- ADVANCE 幂等、乐观并发、事务回滚、应用重启后恢复并继续推进；
- `/paper` 中文操作台及稳定的 FastAPI/OpenAPI 契约。

## 明确不包含

- Broker SDK、BrokerAdapter 或券商进程；
- QMT、XtQuant、vn.py、IBKR、Alpaca 等连接；
- 真实 credential、真实账户、真实资金和真实订单；
- LIVE execution、scheduler、background worker 或实时市场时钟；
- AI/LLM/Agent 交易、AI 风控或绕过 RiskDecision 的路径。

`RunMode` 配置当前仍只允许 `RESEARCH`。PAPER 是本地模拟交易领域能力，不代表进程进入 LIVE 或连接外部账户。

## 环境要求

- Windows 10/11；
- PowerShell 5.1 或更高；
- [uv](https://docs.astral.sh/uv/)；
- Node.js 22 或兼容版本；
- npm 10 或兼容版本。

依赖安装在项目目录内，不依赖全局 Python 包。

## 安装

在仓库根目录执行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/bootstrap.ps1
```

脚本会通过 `uv sync --project backend --all-groups` 创建根目录 `.venv`，并通过 `npm.cmd ci`（无 lock 时为 `install`）安装 `frontend/node_modules`。`-ExecutionPolicy Bypass` 只作用于当前 PowerShell 子进程。

## 初始化或升级数据库

```powershell
$env:QUANT_LAB_PROJECT_ROOT = (Get-Location).Path
.\.venv\Scripts\alembic.exe -c backend/alembic.ini upgrade head
```

当前 Alembic head 为 `20260722_0013`。重复执行 `upgrade head` 是安全的。

默认运行数据位于项目目录；如需隔离，可在启动前指定 Windows 本地路径：

```powershell
$env:QUANT_LAB_RUNTIME_ROOT = 'F:\WIL_QUANT_RUNTIME'
```

SQLite 保存事务与控制状态；发布行情写入 Parquet；DuckDB 用于分析查询。不要把个人历史 runtime 用作自动化测试目录。

## 启动与停止

启动：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/dev.ps1
```

默认地址：

- 前端：<http://127.0.0.1:5173>
- PAPER：<http://127.0.0.1:5173/paper>
- 数据导入：<http://127.0.0.1:5173/data/import>
- 数据集：<http://127.0.0.1:5173/datasets>
- 市场数据：<http://127.0.0.1:5173/market-data>
- 回测：<http://127.0.0.1:5173/backtests>
- 研究：<http://127.0.0.1:5173/research>
- OpenAPI：<http://127.0.0.1:8000/docs>
- 就绪检查：<http://127.0.0.1:8000/api/v1/health/ready>

停止：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/stop.ps1
```

`dev.ps1` 只启动本地 Uvicorn 与 Vite，并把 PID 写入 `.run/`、日志写入 `logs/`。`stop.ps1` 会校验 PID、仓库路径和服务标识，只停止属于本项目的进程。

需要单独启动时：

```powershell
.\.venv\Scripts\python.exe -m uvicorn quant_lab.main:app `
  --app-dir backend/src --host 127.0.0.1 --port 8000

Set-Location frontend
npm.cmd run dev
```

## 测试

正式完整门禁：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/test.ps1
```

脚本按分片执行全部后端 pytest，然后执行 Ruff、严格 mypy、前端 Vitest、TypeScript 和 Vite 生产构建。Phase 5G 验收 runtime 和缓存均创建在 Windows system TEMP，不依赖用户历史 SQLite、已发布数据或 PAPER 账户。

分别执行：

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests -q
.\.venv\Scripts\python.exe -m ruff check backend/src backend/tests backend/alembic
.\.venv\Scripts\python.exe -m mypy backend/src

Set-Location frontend
npm.cmd run test:run
npm.cmd run build
```

## 配置

配置统一使用 `QUANT_LAB_` 前缀。主要默认值：

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

`QUANT_LAB_RUNTIME_ROOT` 为空时，相对路径以项目根目录解析；设置后，SQLite、DuckDB、日志、PID、导入暂存和发布目录都以该 runtime root 解析。配置切换不会自动移动或删除旧数据。

## 项目结构

```text
backend/src/quant_lab/
    datasets/       导入、发布与只读查询
    market_data/    日历、profile 与市场数据消费
    execution/      回测与 PAPER 共用的确定性执行内核
    backtest/       策略库与回测领域
    research/       实验、诊断、报告与日志
    paper/          PAPER 会话、风控、订单、持仓、账本与审计
    api/            FastAPI 路由与稳定 HTTP 契约
backend/alembic/    SQLite 迁移
backend/tests/      后端自动化测试
frontend/src/       React 页面、服务与测试
scripts/            Windows 安装、启动、停止和门禁脚本
```

详细边界见 [ARCHITECTURE.md](ARCHITECTURE.md)。

## 安全声明

WIL_QUANT 当前只允许研究、回测和 PAPER 模拟执行。任何未来真实交易设计都必须作为独立阶段重新审查，并具备进程隔离、资本授权、确定性风控、幂等、人工确认、Kill Switch、对账和追加式审计；这些能力目前均未实现。
