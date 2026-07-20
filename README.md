# Personal A-Share Quant Lab

个人 A 股量化研究与交易终端的本地开发项目。它用于提出量化假设、检查数据、验证回测、限制风险和记录决策，不是券商交易软件，也不承诺任何收益。

当前仓库已完成 **Phase 0（设计）、Phase 1（基础骨架）和 Phase 2A（数据基础）**。

## Phase 1 已实现

- FastAPI 模块化单体后端；
- React + TypeScript + Vite 中文系统状态页；
- Pydantic 类型化配置和严格 `RESEARCH` 模式门禁；
- SQLite + SQLAlchemy + Alembic 首个迁移；
- DuckDB 本地连接与基础查询探针；
- JSON Lines 结构化日志；
- 存活检查与就绪检查；
- 后端 pytest、Ruff、mypy；
- 前端 Vitest 和生产构建；
- Windows 本地依赖、启动、测试和安全停止脚本。

## Phase 2A 已实现

- 受控 CSV/Parquet 上传暂存区，带扩展名、大小和 SHA-256 校验；
- 独立 `MarketDataProvider` 边界及 CSV、Parquet、合成数据 Provider；
- A 股标的、交易所、频率和复权口径的领域类型与规范化；
- OHLCV、成交额、重复、顺序、空文件和异常跳变的数据质量检查；
- 重复 preview 的事务性幂等持久化与数据库唯一约束；
- SQLite 导入批次、数据源、标的和质量问题元数据；
- Parquet 行情文件与 DuckDB 分析查询的独立数据平面边界；
- `/api/v1/data/imports` 检查、预览、批次和质量问题 API；
- `/data/import` 中文导入检查页，不包含发布、交易或券商连接能力。

## 当前限制

当前版本明确不包含：

- 在线行情下载或真实数据源客户端；
- 策略定义、信号、回测或绩效指标；
- OrderIntent、风险引擎、模拟成交或持仓；
- AI 辅助功能；
- QMT、XtQuant、券商账户或任何实盘能力。

Phase 2A 只提供本地文件的检查与预览；尚未发布规范化行情 Parquet，也不提供交易功能。

## 环境要求

- Windows 10/11；
- PowerShell 5.1 或更高；
- [uv](https://docs.astral.sh/uv/)；
- Node.js 22 或兼容版本；
- npm 10 或兼容版本。

项目不依赖全局 Python 包。`uv` 会在仓库根目录创建项目专用 `.venv`。

## 安装

在仓库根目录执行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/bootstrap.ps1
```

`-ExecutionPolicy Bypass` 只作用于这次 PowerShell 子进程，不修改系统或用户执行策略。脚本只安装项目内依赖：

- Python 依赖写入 `.venv`；
- uv 缓存写入 `.uv-cache`；
- 前端依赖写入 `frontend/node_modules`。

## 初始化数据库

```powershell
$env:QUANT_LAB_PROJECT_ROOT = (Get-Location).Path
.\.venv\Scripts\alembic.exe -c backend/alembic.ini upgrade head
```

命令创建本地 SQLite 文件 `data/quant_lab.db`、`app_metadata` 及 Phase 2A 的标的、数据源、导入批次和质量问题表。重复执行 `upgrade head` 是安全的。

DuckDB 文件在首次就绪检查时创建为 `data/analytics.duckdb`。当前不写入任何行情数据。

## 启动

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/dev.ps1
```

默认地址：

- 前端：<http://127.0.0.1:5173>
- 后端 OpenAPI：<http://127.0.0.1:8000/docs>
- 存活检查：<http://127.0.0.1:8000/api/v1/health/live>
- 就绪检查：<http://127.0.0.1:8000/api/v1/health/ready>

启动脚本会：

1. 检查 8000 和 5173 端口；
2. 直接启动项目 `.venv` 中的 Python 和本地 Vite；
3. 将实际服务 PID 写入 `.run/backend.pid` 和 `.run/frontend.pid`；
4. 将标准输出和错误写入 `logs/`；
5. 不启动 Docker、行情服务或券商客户端。

### 直接启动后端

```powershell
.\.venv\Scripts\python.exe -m uvicorn quant_lab.main:app `
  --app-dir backend/src --host 127.0.0.1 --port 8000
```

### 直接启动前端

```powershell
Set-Location frontend
npm.cmd run dev
```

Windows PowerShell 可能因执行策略拦截 `npm.ps1`，因此文档和脚本统一使用 `npm.cmd`，不会修改系统执行策略。

## 停止

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/stop.ps1
```

停止脚本不会使用 `taskkill /IM python.exe` 或 `taskkill /IM node.exe`。它会读取项目 PID，核验进程命令行包含当前仓库路径和预期服务标识，只停止匹配的精确 PID。身份无法确认时会拒绝停止。

## 测试

运行完整检查：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/test.ps1
```

该脚本依次执行：

1. PowerShell PID 安全助手测试；
2. 后端 pytest；
3. Ruff；
4. mypy；
5. 前端 Vitest；
6. TypeScript 与 Vite 生产构建。

也可以分别运行：

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests -q
.\.venv\Scripts\python.exe -m ruff check backend/src backend/tests backend/alembic
.\.venv\Scripts\python.exe -m mypy backend/src

Set-Location frontend
npm.cmd run test:run
npm.cmd run build
```

测试和状态页不访问真实行情、券商账户或外部交易接口。

## 健康检查

### Liveness

`GET /api/v1/health/live` 只确认 FastAPI 进程能够响应，不依赖数据库。

```json
{"status":"alive"}
```

### Readiness

`GET /api/v1/health/ready` 检查 SQLite 和 DuckDB。全部正常时返回 HTTP 200；任一依赖失败时返回 HTTP 503。响应只包含安全状态消息，不暴露完整文件路径、环境变量或异常文本。

## 配置

复制 `.env.example` 为本地 `.env` 后按需修改。真实 `.env` 已被 Git 忽略。

所有变量使用 `QUANT_LAB_` 前缀。默认配置：

```dotenv
QUANT_LAB_RUN_MODE=RESEARCH
QUANT_LAB_API_HOST=127.0.0.1
QUANT_LAB_API_PORT=8000
QUANT_LAB_FRONTEND_ORIGINS=["http://127.0.0.1:5173","http://localhost:5173"]
QUANT_LAB_RUNTIME_ROOT=
QUANT_LAB_SQLITE_PATH=data/quant_lab.db
QUANT_LAB_DUCKDB_PATH=data/analytics.duckdb
QUANT_LAB_LOG_PATH=logs/quant-lab.jsonl
QUANT_LAB_RUN_DIRECTORY=.run
QUANT_LAB_IMPORT_DIRECTORY=imports/staging
QUANT_LAB_IMPORT_MAX_BYTES=20971520
QUANT_LAB_IMPORT_PREVIEW_ROWS=100
QUANT_LAB_LOG_LEVEL=INFO
```

设置 `QUANT_LAB_RUNTIME_ROOT` 后，SQLite、DuckDB、日志、PID 和上传暂存区的相对路径都以该目录为基准；若该变量本身是相对路径，则它稳定地相对于项目根目录解析，与启动终端的当前目录无关。留空时仍以 `QUANT_LAB_PROJECT_ROOT` 为基准。当前主项目位于非 OneDrive 目录；若其他部署位于 OneDrive 等同步目录，建议将运行根目录设为不参与同步的位置（例如 `F:\\WIL_QUANT_RUNTIME` 或 `D:\\WIL_QUANT_RUNTIME`），避免同步工具干扰文件锁和原子写入。配置切换不会自动移动、删除或迁移旧运行文件，测试 fixtures 仍保留在仓库中。

## 数据导入与质量检查

打开 <http://127.0.0.1:5173/data/import> 可上传 `.csv` 或 `.parquet` 文件。后端先将请求流写入受控暂存区，再计算哈希并解析列；用户确认列映射后执行规范化与质量检查，并返回可接受样本和问题摘要。原始上传不会被改写，Phase 2A 也不会自动发布行情文件。

CSV 需要显式映射 `symbol`、`exchange`、`trade_date`、`open`、`high`、`low`、`close`、`volume` 和 `amount`。常见中英文列名会被自动建议；含义不明确的列必须显式映射。当前日线时间统一为北京时间收盘时刻，标的代码按沪深交易所规则规范化。

接口：

- `POST /api/v1/data/imports/inspect?filename=...`：流式暂存并检查文件；
- `POST /api/v1/data/imports/preview`：按列映射规范化和校验；
- `GET /api/v1/data/imports/{batch_id}`：查询批次状态和摘要；
- `GET /api/v1/data/imports/{batch_id}/issues`：查询结构化质量问题。

Phase 2A 的已知边界是仅做检查和预览，尚未把接受行发布为分区 Parquet，也未建立 DuckDB 视图；CSV 编码限定为 UTF-8/UTF-8 BOM，Parquet 解析依赖项目已有的 DuckDB。

## 运行模式与安全边界

- `RESEARCH`：Phase 1 唯一允许的模式；
- `PAPER`：已声明但在 Phase 5 前会被配置校验拒绝；
- `LIVE`：第一版不可用，配置校验会拒绝启动。

系统当前没有 `BrokerAdapter` 实现、券商凭据读取、账户连接或下单接口。AI、策略和前端都不存在绕过风控直接交易的路径。

## 项目结构

```text
backend/src/quant_lab/   FastAPI、配置、日志和数据库基础设施
backend/alembic/         SQLite迁移
backend/tests/           后端自动化测试
frontend/src/            React系统状态页与测试
scripts/                 Windows本地生命周期脚本
docs/superpowers/specs/  已批准设计
docs/superpowers/plans/  实施计划
```

总体边界见 [ARCHITECTURE.md](ARCHITECTURE.md)，完整 Phase 0–1 设计见 [设计规范](docs/superpowers/specs/2026-07-20-phase-0-1-foundation-design.md)。

## 安全声明

本项目用于学习和研究，不构成投资建议。Phase 1 完全没有实盘能力。未来即使接入券商官方接口，也必须保持确定性风控、订单预览、人工确认、幂等防护、Kill Switch 和追加式审计，任何策略或 AI 输出都不能直接提交订单。
