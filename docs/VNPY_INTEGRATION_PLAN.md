# vn.py 候选集成研究计划（未批准实施）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 如果未来明确选择 vn.py，在不破坏现有 FastAPI/React、数据存储和安全领域边界的前提下，将其作为可选、隔离、默认禁用的候选底层运行时。

**Architecture:** 核心项目继续拥有领域模型、A 股规则、风险、审计、数据质量和产品 UI。若采用 vn.py，其固定版本必须运行在独立本地进程中，仅通过项目内部 Port、Mapper 和版本化 IPC 协议提供候选 EventEngine、OMS 与 Gateway 能力。

**Tech Stack:** Python 3.11–3.13、FastAPI、Pydantic Settings、SQLAlchemy/SQLite、Parquet/DuckDB、React/TypeScript、uv；候选 vn.py 4.4.0；Windows 本地进程与后续版本化 IPC。

---

> 状态说明：本文仅是 Phase V0 候选研究材料，不是 vn.py 选型、依赖安装或 Phase V1 实施授权。vn.py 不是唯一运行时；直接 QMT/XtQuant 或其他官方能力的独立 Adapter 仍保留。Phase 2B、Phase 2C 优先级不变，当前系统仍只有 RESEARCH 模式。

## 1. Phase V0 审计结论

- 当前代码已完成 Phase 1 基础骨架和 Phase 2A 本地 CSV/Parquet 导入预览、标准化、质量检查与 SQLite 元数据。
- 不存在可迁移或替换的 BrokerAdapter、回测引擎、OrderIntent、RiskDecision、PaperBroker 或 vn.py 代码。
- 不存在 `send_order`、真实 Gateway、账户登录或订单 API。
- 当前核心项目环境未安装 vn.py、PySide6、TA-Lib、Polars 或 XtQuant。
- vn.py 4.4.0 是当前候选验证版本，不在 V0 安装，也不在未验证前写入核心依赖组。
- 由于 MainEngine 有线程启动和工作目录副作用，ADR-0001 规定：若选择 vn.py，只允许独立进程方案。

## 2. 文件归属

### Phase V1 建议创建

- `backend/src/quant_lab/integrations/vnpy/__init__.py`：不导入第三方包的集成命名空间。
- `backend/src/quant_lab/integrations/vnpy/compatibility.py`：通过包元数据发现安装状态和版本。
- `backend/src/quant_lab/integrations/vnpy/contracts.py`：运行时状态 DTO，不含 vn.py 对象。
- `backend/src/quant_lab/api/integrations.py`：只读集成状态 API。
- `backend/tests/integrations/vnpy/test_compatibility.py`：无 vn.py 和伪包元数据测试。
- `backend/tests/test_integration_api.py`：默认禁用、不泄露路径的 API 测试。
- `frontend/src/types/integrations.ts`：前端状态契约。
- `frontend/src/services/integrations.ts`：类型化状态请求。
- `frontend/src/components/VnpyRuntimeStatus.tsx`：明确显示未安装/未启用/交易禁用。
- `frontend/src/components/VnpyRuntimeStatus.test.tsx`：安全状态呈现测试。
- `THIRD_PARTY_NOTICES.md`：只有正式添加依赖后才登记实际使用版本。
- `docs/DEPENDENCY_LICENSES.md`：只有正式添加依赖后才记录锁定依赖许可证。

### Phase V1 建议修改

- `backend/pyproject.toml`：添加独立可选 extra，候选约束 `vnpy==4.4.0`；默认同步不安装。
- `backend/uv.lock`：只在授权的隔离兼容性验证成功后更新。
- `backend/src/quant_lab/core/config.py`：增加默认关闭的 vn.py 配置，不启动运行时。
- `backend/src/quant_lab/main.py`：只注入兼容性服务和只读路由，不构造 MainEngine。
- `backend/src/quant_lab/core/logging.py`：增加有限的 integration/runtime 审计字段白名单。
- `.env.example`：增加带 `QUANT_LAB_` 前缀的安全默认值。
- `frontend/src/pages/SystemStatusPage.tsx`：保留现有状态页，只增加运行时状态卡。
- `README.md`：说明 vn.py 是可选、默认禁用且尚无 Gateway/交易能力。
- `ARCHITECTURE.md`：链接 ADR，不重写现有架构。

### Phase V0/V1 完全不需要修改

- `backend/src/quant_lab/db/sqlite.py`
- `backend/src/quant_lab/db/duckdb.py`
- 现有 Alembic 迁移
- `frontend/src/services/health.ts`
- `frontend/src/types/health.ts`
- `scripts/stop.ps1` 的精确 PID 安全原则
- Phase 2A 的 CSV/Parquet Provider 和数据质量设计

## 3. Phase V1 候选计划（不得自动执行）

Phase V1 不是 Phase 2A 的自动后继阶段；只有在 Phase 2B、Phase 2C 的既定优先级得到保留且用户再次明确授权后，才可执行以下内容。

### Task 1：安全配置与无 vn.py 环境

**Files:**
- Modify: `backend/src/quant_lab/core/config.py`
- Modify: `.env.example`
- Test: `backend/tests/test_config.py`

- [ ] **Step 1: 写失败测试**

测试默认值必须为：enabled/auto-start/auto-connect/trading 全部 `False`，runtime mode 为 `process`，Gateway allowlist 为空；任何非 RESEARCH 模式继续失败。

- [ ] **Step 2: 验证 RED**

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/test_config.py -q`

Expected: 新 vn.py 配置字段尚不存在，测试失败。

- [ ] **Step 3: 最小实现**

在现有 Settings 中增加强类型配置；禁止 `auto_connect=True` 且 `enabled=False`，禁止 `trading_enabled=True`，V1 不提供绕过校验的配置组合。

- [ ] **Step 4: 验证 GREEN**

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/test_config.py -q`

Expected: 配置测试通过，PAPER/LIVE 仍被拒绝。

- [ ] **Step 5: 提交**

```powershell
git add .env.example backend/src/quant_lab/core/config.py backend/tests/test_config.py
git commit -m "feat: add disabled vnpy integration settings"
```

### Task 2：无副作用兼容性检测

**Files:**
- Create: `backend/src/quant_lab/integrations/vnpy/__init__.py`
- Create: `backend/src/quant_lab/integrations/vnpy/contracts.py`
- Create: `backend/src/quant_lab/integrations/vnpy/compatibility.py`
- Test: `backend/tests/integrations/vnpy/test_compatibility.py`

- [ ] **Step 1: 写失败测试**

覆盖未安装、安装 4.4.0、版本不匹配和元数据读取异常；测试必须断言检测过程不导入 `vnpy`、不创建线程、不改变 `Path.cwd()`。

- [ ] **Step 2: 验证 RED**

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/integrations/vnpy/test_compatibility.py -q`

Expected: 集成模块不存在。

- [ ] **Step 3: 最小实现**

使用 `importlib.util.find_spec("vnpy")` 与 `importlib.metadata.version("vnpy")` 返回冻结 DTO：`installed`、`version`、`compatible`、`enabled`、`runtime_state="not_started"`、`trading_enabled=False`。不得执行 `import vnpy`。

- [ ] **Step 4: 验证 GREEN 和架构搜索**

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/integrations/vnpy/test_compatibility.py -q
rg -n "^(from|import) vnpy" backend/src/quant_lab
```

Expected: 测试通过；直接导入搜索没有结果。

- [ ] **Step 5: 提交**

```powershell
git add backend/src/quant_lab/integrations backend/tests/integrations
git commit -m "feat: detect optional vnpy runtime safely"
```

### Task 3：只读状态 API

**Files:**
- Create: `backend/src/quant_lab/api/integrations.py`
- Create: `backend/tests/test_integration_api.py`
- Modify: `backend/src/quant_lab/main.py`

- [ ] **Step 1: 写失败 API 测试**

验证 `GET /api/v1/integrations/vnpy/status` 在无 vn.py 环境返回 HTTP 200、`installed=false`、`enabled=false`、`trading_enabled=false`，且不泄露 `site-packages` 或绝对路径。

- [ ] **Step 2: 验证 RED**

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/test_integration_api.py -q`

Expected: 路由返回 404。

- [ ] **Step 3: 最小实现**

新增 GET-only 路由，注入兼容性服务；不得把 vn.py 添加为 readiness 的硬依赖，不得构造 EventEngine/MainEngine。

- [ ] **Step 4: 验证 GREEN**

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/test_integration_api.py backend/tests/test_health_api.py -q`

Expected: 新旧 API 测试全部通过。

- [ ] **Step 5: 提交**

```powershell
git add backend/src/quant_lab/api/integrations.py backend/src/quant_lab/main.py backend/tests/test_integration_api.py
git commit -m "feat: expose disabled vnpy integration status"
```

### Task 4：系统状态页增量展示

**Files:**
- Create: `frontend/src/types/integrations.ts`
- Create: `frontend/src/services/integrations.ts`
- Create: `frontend/src/components/VnpyRuntimeStatus.tsx`
- Create: `frontend/src/components/VnpyRuntimeStatus.test.tsx`
- Modify: `frontend/src/pages/SystemStatusPage.tsx`

- [ ] **Step 1: 写失败组件测试**

覆盖“未安装”“已安装但未启用”和错误状态；所有状态都必须明确显示“交易能力：禁用”，不得出现连接或下单按钮。

- [ ] **Step 2: 验证 RED**

Run: `npm.cmd --prefix frontend run test:run -- VnpyRuntimeStatus.test.tsx`

Expected: 组件尚不存在。

- [ ] **Step 3: 最小实现**

新增独立类型化请求与状态卡，在现有页面下方组合，不改变 `/` 的健康检查语义，不显示服务器错误细节。

- [ ] **Step 4: 验证 GREEN 与构建**

```powershell
npm.cmd --prefix frontend run test:run
npm.cmd --prefix frontend run build
```

Expected: 全部前端测试和生产构建通过。

- [ ] **Step 5: 提交**

```powershell
git add frontend/src
git commit -m "feat: show disabled vnpy runtime status"
```

### Task 5：可选依赖验证与许可证

**Files:**
- Modify: `backend/pyproject.toml`
- Modify: `backend/uv.lock`
- Create: `THIRD_PARTY_NOTICES.md`
- Create: `docs/DEPENDENCY_LICENSES.md`
- Modify: `README.md`
- Modify: `ARCHITECTURE.md`

- [ ] **Step 1: 在独立临时环境解析候选依赖**

仅在用户批准安装后，在系统临时目录创建随机命名的兼容性目录，通过 `uv venv --python 3.13` 创建专用环境，并用 `uv pip install --python <临时环境Python> vnpy==4.4.0` 解析和安装候选版本。不得覆盖核心 `.venv`，不得使用全局 site-packages；验证结束后报告临时目录，由用户决定是否删除。

- [ ] **Step 2: 验证导入和版本，不启动 MainEngine**

验证 `importlib.metadata.version("vnpy") == "4.4.0"`、PySide6/TA-Lib 可导入、进程无线程和工作目录副作用；不得加载 Gateway。

- [ ] **Step 3: 固化验证结果并记录许可证**

只有 Step 1–2 成功后，才在 `backend/pyproject.toml` 添加独立可选 extra `vnpy = ["vnpy==4.4.0"]` 并更新锁文件。记录 vn.py 名称、4.4.0、官方仓库、MIT、未修改、使用范围，以及失败或冲突的精确版本。

- [ ] **Step 4: 完整验证**

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/test.ps1
git diff --check
git status --short
```

Expected: 核心与前端检查通过；没有数据库、日志、PID、缓存或凭据进入 Git。

- [ ] **Step 5: 提交**

```powershell
git add backend/pyproject.toml backend/uv.lock THIRD_PARTY_NOTICES.md docs README.md ARCHITECTURE.md
git commit -m "docs: record optional vnpy compatibility boundary"
```

## 4. 候选后续阶段门禁

| 阶段 | 可交付内容 | 明确禁止 | 开始条件 |
| --- | --- | --- | --- |
| V2 | 独立 headless runtime、假 MainEngine、启停与健康协议 | Gateway、Qt GUI、交易 | V1 验收且另行批准 |
| V3 | Fake EventBridge、只读 OMS DTO、去重、乱序与对账骨架 | 真实账户连接 | V2 验收且另行批准 |
| V4 | VnpyMarketDataProvider、Tick/Bar Mapper、统一质量管道 | 绕过固化数据运行回测 | Phase 2A 与 V3 已完成 |
| V5 | 可选回测对照 Adapter、BacktestParityReport | 替换自有 A 股引擎 | 自有回测先完成 |
| V6 | 单个固定版本只读 Gateway 评估 | 下单、自动登录、明文凭据 | 用户明确授权并完成 QMT/Gateway 评审 |
| V7 | 被禁用的执行 Adapter 与 OrderRequest Mapper | 调用真实 `send_order` | OrderIntent/风险/确认/Kill Switch 已完成 |
| V8 | 未来人工确认实盘 | 当前全部禁止 | 新的独立明确授权 |

每一阶段必须重新编写独立设计和实施计划，不能把本路线图当作跨阶段执行授权。

## 5. Phase 2A 的立即影响

Phase 2A 已按受控上传暂存区实现，并保持：

- 将 Provider 定义为项目内部接口，不导入 vn.py。
- 为 `data_source`、`source_batch_id`、`quality_status` 保留稳定语义。
- 不新增 VnpyMarketDataProvider、实时 Tick、Gateway 或交易代码。
- 让未来 V4 通过 Adapter 进入同一标准化和质量管道。
- 不为了未来 vn.py 使用 pandas DataFrame 作为领域边界。

## 6. V0 验收

- [x] 审计当前模块、依赖、Git 和运行环境。
- [x] 确认没有现有 vn.py/Broker/回测/订单实现需要迁移。
- [x] 确认没有真实交易路径。
- [x] 核验 vn.py 4.4.0 官方元数据、核心依赖和许可证。
- [x] 记录能力矩阵。
- [x] 提出运行时边界 ADR。
- [x] 给出 V1 详细计划和 V2–V8 门禁。
- [x] 用户仅批准 ADR-0001 的条件性独立进程边界。
- [ ] 用户批准 vn.py 运行时选型或 Phase V1 实施范围。
