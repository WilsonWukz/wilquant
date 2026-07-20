# Personal A-Share Quant Lab：Phase 0–1 基础设计

- 状态：已批准
- 日期：2026-07-20
- 范围：Phase 0 项目检查与设计、Phase 1 基础骨架

## 1. 项目状态

当前仓库是一个只有 `.git` 的空仓库，位于 Windows 的 OneDrive 同步目录中。仓库尚无提交，不存在需要兼容或保留的既有代码、项目文档、依赖清单或未提交修改。

已检测到以下工具：

- Git 2.47.0.windows.2；
- Node.js 22.20.0；
- npm 10.9.3；
- uv 0.9.28。

当前会话中的 `python` 命令指向不可执行的 Windows 占位符，因此 Phase 1 不依赖全局 `python` 命令，必须显式创建并使用项目级 `.venv`。PowerShell 执行策略会拦截 `npm.ps1`，Windows 脚本统一调用 `npm.cmd`，不修改系统执行策略。

## 2. 目标与非目标

项目采用模块化单体，为个人 A 股研究、回测、模拟交易、交易计划和复盘提供可运行、可测试、可解释的本地工作台。

本轮只交付 Phase 0 和 Phase 1。Phase 1 的目标是证明前端、后端、SQLite、Alembic、DuckDB、配置、日志和健康检查能够在本地可靠协作。

本轮不实现：

- 行情导入、行情下载或真实数据源；
- 策略、信号、回测或绩效计算；
- OrderIntent、风控、模拟成交或持仓；
- AI 辅助模块；
- QMT、XtQuant 或任何券商连接；
- PAPER 或 LIVE 运行能力。

系统优先级始终是：正确性、资金安全、可追溯性、可测试性、可解释性、易用性、界面美观、策略收益。

## 3. 方案选择

### 3.1 已选方案

采用单仓库、模块化单体和前后端分离开发：

- FastAPI 后端与 React 前端在开发时分别启动；
- 后端按领域边界组织，Phase 1 只建立基础设施模块；
- SQLite 作为事务与控制平面；
- Parquet + DuckDB 作为行情与分析平面；
- 后端使用 `uv`、项目级 `.venv`、`pyproject.toml` 和 `uv.lock`；
- 前端使用 `npm.cmd` 和 `package-lock.json`。

该方案比 FastAPI 直接托管前端更适合本地迭代，也比 Docker Compose 更符合个人 Windows 项目的轻量定位。未来可将前端构建产物交给后端托管，但这不是 Phase 1 的要求。

### 3.2 目录边界

```text
WIL_QUANT/
├── backend/
│   ├── src/
│   │   └── quant_lab/
│   │       ├── api/
│   │       ├── core/
│   │       ├── db/
│   │       └── main.py
│   ├── alembic/
│   ├── tests/
│   └── pyproject.toml
├── frontend/
│   ├── src/
│   │   ├── pages/
│   │   ├── components/
│   │   ├── services/
│   │   └── types/
│   └── package.json
├── config/
├── data/
├── docs/
├── logs/
├── scripts/
├── .env.example
├── .gitignore
├── ARCHITECTURE.md
└── README.md
```

Phase 1 不创建 Phase 2–7 的空壳模块。后续目录在对应垂直切片开始时增加。

## 4. Phase 1 架构

### 4.1 后端

- Python 包名：`quant_lab`；
- API 前缀：`/api/v1`；
- `core` 负责 Pydantic 配置、运行模式门禁、结构化日志和异常分类；
- `db` 分别管理 SQLite 和 DuckDB 的连接生命周期；
- API 层只调用应用服务，不直接修改数据库状态；
- 配置默认模式为 `RESEARCH`，Phase 1 请求 `PAPER` 或 `LIVE` 都必须明确失败；
- CORS 只允许配置中的本地开发源，不使用任意来源通配符。

### 4.2 健康检查

- `GET /api/v1/health/live`：只证明后端进程能够响应；
- `GET /api/v1/health/ready`：检查配置、SQLite 和 DuckDB；
- 就绪响应提供组件状态、应用版本和运行模式；
- 响应和日志不得暴露完整文件路径、环境变量值或凭据；
- 依赖组件异常时返回明确的非就绪状态，不静默吞掉异常。

### 4.3 SQLite 与 Alembic

Alembic 只管理 SQLite。首个迁移创建最小的 `app_metadata` 表，用于数据库初始化状态和非敏感应用元数据。Phase 1 不提前创建策略、订单或持仓表。

### 4.4 DuckDB

Phase 1 只初始化连接并执行轻量查询验证。DuckDB 不保存事务状态，也不导入真实行情。DuckDB 视图与 Parquet 布局将在 Phase 2 由数据模块管理。

### 4.5 日志

- 使用结构化 JSON 日志；
- 控制台和项目日志目录共享一致字段；
- 至少包含时间、级别、事件名、消息、应用版本和关联 ID；
- 异常必须分级并保留堆栈；
- 日志不得记录完整密钥、密码或敏感环境变量值。

### 4.6 前端

- React + TypeScript + Vite；
- 默认中文、浅色、桌面优先；
- Phase 1 只实现系统状态页；
- 页面通过类型化 API 客户端读取后端运行模式、SQLite 和 DuckDB 状态；
- 风险或不可用状态的视觉优先级高于普通成功信息；
- 页面不直接访问 SQLite 或 DuckDB。

### 4.7 Windows 脚本

- `scripts/bootstrap.ps1`：创建项目虚拟环境并安装项目内依赖；
- `scripts/dev.ps1`：检查端口后启动前后端，记录 PID；
- `scripts/test.ps1`：运行后端测试、前端测试和构建检查；
- `scripts/stop.ps1`：读取项目 PID，核验进程信息后只停止本项目进程。

默认后端端口为 8000，前端端口为 5173。脚本不修改系统环境变量，不安装全局包，不修改 PowerShell 执行策略，不使用按进程名批量终止命令。

## 5. 核心数据流

完整目标数据流为：

```text
配置与运行模式
    ↓
MarketDataProvider
    ↓
标准化与数据质量检查
    ├── 严重问题 → 阻止正式回测和订单意图
    └── 合格数据 → Parquet → DuckDB 查询
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
                  Journal + Audit
```

Phase 1 只贯通：

```text
环境配置 → FastAPI 启动 → SQLite/DuckDB 连接
         → 健康检查 API → React 状态页 → 结构化日志
```

## 6. 数据存储边界

### 6.1 SQLite 表规划

| 阶段 | 表组 | 用途 |
| --- | --- | --- |
| Phase 1 | `app_metadata` | 数据库版本、初始化状态等非敏感元数据 |
| Phase 2 | `data_sources`、`data_imports`、`data_quality_reports` | 数据来源、导入批次和质量摘要 |
| Phase 3 | `strategy_definitions`、`strategy_versions`、`backtest_runs`、`backtest_checks`、`signals` | 策略版本、回测和可信度结果 |
| Phase 5 | `order_intents`、`risk_decisions`、`broker_orders`、`order_events`、`fills` | 幂等订单链路和状态历史 |
| Phase 5 | `portfolio_snapshots`、`position_lots` | 资金、总持仓、可卖批次和 T+1 状态 |
| 跨阶段 | `journal_entries`、`audit_events` | 复盘记录和追加式审计轨迹 |
| 后续 | `ai_results` | AI 建议、Schema 校验和用户采纳情况 |

关键约束：

- 策略定义和策略版本分离，已运行版本不可覆盖；
- `OrderIntent`、`RiskDecision`、`BrokerOrder` 和 `Fill` 分别持久化；
- `order_intents.idempotency_key` 具有唯一约束；
- 订单状态变化追加到 `order_events`；
- T+1 由 `position_lots.sellable_date` 表达；
- 关键金额使用 Decimal 语义映射到定点数或字符串，不依赖二进制浮点；
- 时间保存为带时区的 ISO 8601 值，业务含义使用 `Asia/Shanghai`；
- 普通业务接口不能更新或删除审计事件。

### 6.2 Parquet + DuckDB 数据规划

```text
data/parquet/
├── instruments/
├── trading_calendar/
├── bars/
│   ├── daily/
│   └── intraday/
├── corporate_actions/
└── quality_issues/
```

- 行情按频率、标的和年份分区；
- 每批数据带 `source`、`ingestion_time`、`data_version` 和 `quality_status`；
- DuckDB 主要提供只读查询视图，不承担订单或持仓状态；
- 两个数据平面通过稳定的 `instrument_id`、`data_version` 和导入批次 ID 关联，不建立跨数据库外键；
- 测试数据放在 `data/fixtures/`，与真实数据严格分离。

## 7. Phase 1–5 实施顺序

### Phase 1：基础骨架

按测试先行依次建立配置与模式门禁、健康检查、SQLite/Alembic、DuckDB、结构化日志、React 状态页和 Windows 脚本。验收时运行后端测试、前端测试、生产构建并实际启动前后端验证健康检查。

### Phase 2：可信数据纵向切片

实现本地文件导入、标准化、质量检查、Parquet 发布、DuckDB 查询和最小导入/K 线页面。先支持 ETF 日线，再扩展其他标的和频率。

### Phase 3：事件驱动回测纵向切片

按“交易日历 → ETF 轮动信号 → 下一交易日订单 → 撮合 → 费用 → PositionLot/T+1 → 权益 → 指标 → 可信度报告”建立完整闭环。任何未实现规则必须显示为“未实现”，不能显示为“通过”。

### Phase 4：完整研究前端

围绕稳定后端用例实现今日工作台、策略实验室、回测中心、风险中心和交易复盘。所有页面只通过 API 访问数据。

### Phase 5：模拟交易

按“OrderIntent → 确定性风控 → 订单预览 → 人工确认 → MockBroker → PaperBroker → BrokerOrder 状态机 → Fill → PositionLot 对账 → Kill Switch”实现。先用 MockBroker 覆盖拒单、超时、重复回调和部分成交，再接 PaperBroker。

## 8. Phase 1 验收与测试边界

Phase 1 必须证明：

- 配置缺失或非法时明确失败；
- 默认模式为 `RESEARCH`；
- `PAPER` 在 Phase 5 前不可启用，`LIVE` 始终被拒绝；
- SQLite 迁移可以在空数据库执行；
- DuckDB 异常会使就绪检查失败，但不会泄露敏感信息；
- 后端 pytest、前端单元测试和前端生产构建通过；
- 前后端能够实际启动，健康检查可以访问；
- 所有测试和演示都不访问真实行情、券商或交易接口。

## 9. 主要风险与缓解措施

### 9.1 最大技术风险

SQLite、DuckDB 和 Parquet 的一致性，以及 OneDrive 同步对数据库文件锁和原子写入的影响。

缓解措施：

- SQLite 只保存事务状态；
- DuckDB 不保存订单状态；
- 数据导入使用不可变批次 ID 和 `data_version`；
- Parquet 先写临时文件，校验后原子发布；
- 同一实例保持单写者；
- 运行目录可配置到非同步本地磁盘；
- SQLite、DuckDB、Parquet、日志和 PID 文件不提交到 Git。

### 9.2 最大量化回测风险

未来数据泄漏和不现实的成交模型比普通指标计算错误更危险。

缓解措施：明确区分观察、信号、委托和成交时间；收盘信号最早下一交易日成交；保存数据版本、策略版本和成交假设；对停牌、无行情、涨跌停和成交量不足采取保守撮合；分别披露费用、滑点、复权和幸存者偏差；保证同版本、同数据、同配置可复现。

### 9.3 最大实盘安全风险

策略、AI 或普通 API 通过旁路直接访问 Broker。

缓解措施：Phase 0–5 不包含真实 Broker；策略只能产生 Signal 和 OrderIntent；AI 在依赖层面不能获得 BrokerAdapter；未来 LIVE 需要多层独立能力门禁；风控、人工确认、幂等键、Kill Switch 和追加式审计不可绕过；QMT 只在独立适配层按后续阶段逐步接入。

## 10. 文档归属

- 本文件记录 Phase 0–1 的已批准设计与决策依据；
- 根目录 `ARCHITECTURE.md` 保存长期有效的架构边界；
- Phase 1 详细实施计划写入 `docs/superpowers/plans/2026-07-20-phase-1-foundation-plan.md`；
- `README.md` 在 Phase 1 按实际可运行命令编写；
- 后续阶段需要的回测、风控、数据模型和 QMT 文档在相应阶段落实，不提前创建空文档。
