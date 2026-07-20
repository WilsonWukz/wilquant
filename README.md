# Personal A-Share Quant Lab

个人 A 股量化研究与交易终端的本地开发项目。它用于提出量化假设、检查数据、验证回测、限制风险和记录决策，不是券商交易软件，也不承诺任何收益。

当前仓库只完成 **Phase 0（设计）和 Phase 1（基础骨架）**。

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

## 当前限制

Phase 1 明确不包含：

- 行情导入、行情下载、K 线或真实数据源；
- 策略定义、信号、回测或绩效指标；
- OrderIntent、风险引擎、模拟成交或持仓；
- AI 辅助功能；
- QMT、XtQuant、券商账户或任何实盘能力。

数据导入将在 Phase 2 实现。当前系统状态页只验证基础设施，不提供交易功能。

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

命令创建本地 SQLite 文件 `data/quant_lab.db` 和最小的 `app_metadata` 表。重复执行 `upgrade head` 是安全的。

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
QUANT_LAB_SQLITE_PATH=data/quant_lab.db
QUANT_LAB_DUCKDB_PATH=data/analytics.duckdb
QUANT_LAB_LOG_PATH=logs/quant-lab.jsonl
QUANT_LAB_RUN_DIRECTORY=.run
QUANT_LAB_LOG_LEVEL=INFO
```

相对路径以 `QUANT_LAB_PROJECT_ROOT` 为基准。若项目位于 OneDrive 等同步目录，建议将 SQLite、DuckDB 和日志路径配置到不参与同步的本地目录，避免同步工具干扰文件锁和原子写入。

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
