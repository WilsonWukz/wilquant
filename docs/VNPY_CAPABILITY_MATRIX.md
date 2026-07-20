# vn.py 能力矩阵

- 状态：Phase V0 候选审计基线；不代表运行时选型或实施批准
- 日期：2026-07-20
- 审计分支：`phase-2a-data-foundation`
- 审计提交：`39ded34eb459bde946b75f4f97247b2c4682d6cd`
- vn.py 候选版本：`4.4.0`（尚未安装、尚未验证）
- 选型边界：vn.py 不是唯一运行时；直接 QMT/XtQuant 或其他官方能力的独立 Adapter 仍保留
- 阶段边界：Phase 2B、Phase 2C 优先级不变，Phase V1 未获实施授权

## 1. 当前项目完成度

| 模块 | 当前状态 | 证据或边界 |
| --- | --- | --- |
| FastAPI 应用工厂 | 已完成 | `quant_lab.main.create_app` 支持 Settings 和健康服务注入 |
| React 状态页 | 已完成 | `/` 仅显示 SQLite、DuckDB 与 RESEARCH 状态 |
| RESEARCH 模式门禁 | 已完成 | PAPER、LIVE 在 Settings 校验阶段被拒绝 |
| SQLite/Alembic | 已完成 Phase 2A 控制面 | `app_metadata`、四张行情元数据表及 issue 幂等 revision，迁移头 `20260720_0003` |
| DuckDB | 已完成基础 | 仅有连接和 `SELECT 1` 探针 |
| JSON 结构化日志 | 已完成基础 | 字段白名单，尚无 Broker/vn.py 审计字段 |
| Windows 生命周期脚本 | 已完成 | 精确 PID 校验；支持独立 runtime root |
| Phase 2A 本地数据导入 | 已完成 | CSV、Parquet、Synthetic Provider、受控 staging、预览与质量问题 API |
| Instrument/Bar 领域模型 | 已完成 Phase 2A 范围 | 类型化模型与 Instrument SQLite 元数据表；Bar 不写 SQLite |
| BrokerAdapter/OMS | 尚未开始 | 仓库不存在实现 |
| OrderIntent/RiskDecision | 尚未开始 | 只存在长期架构文档中的概念 |
| 自有 A 股回测引擎 | 尚未开始 | 不存在实现 |
| MockBroker/PaperBroker | 尚未开始 | 不存在实现 |
| WebSocket | 尚未开始 | 当前仅 REST 健康检查 |
| AI | 尚未开始 | 不存在运行时代码 |
| QMT/XtQuant | 尚未开始 | 不存在包、配置、代码或常见安装目录 |

当前代码中没有 `send_order`、`cancel_order`、Gateway 连接或实盘入口，因此没有已暴露的交易执行路径。

## 2. 能力归属决策

| 能力 | 项目自有 | vn.py | 决策 | 目标阶段 |
| --- | --- | --- | --- | --- |
| Web 产品层 | 保留 | 不采用 Qt GUI | React/FastAPI 保持唯一产品入口 | 持续 |
| 领域实体 | 保留 | 对象仅作外部 DTO | 必须经集中 Mapper 转换 | V3+ |
| RESEARCH/PAPER/LIVE 门禁 | 保留 | 不信任其运行状态 | 项目门禁始终优先 | 持续 |
| 数据质量 | 保留 | 行情只能作为来源之一 | 所有 vn.py 行情进入统一质量管道 | V4 |
| 本地 CSV/Parquet Provider | 保留 | 不替换 | Phase 2A 独立于 vn.py 完成 | Phase 2A |
| EventEngine | 不重复实现 | 候选复用 | 若选用 vn.py，仅存在于隔离运行时进程 | V2 候选 |
| MainEngine | 不重复实现 | 候选复用 | 若选用 vn.py，不向 API、策略、AI 暴露 | V2 候选 |
| 实时 OMS | 保存业务快照/审计 | 运行期底层状态源 | 通过只读 Adapter 与对账同步 | V3 |
| Gateway | 安全注册与审批 | 承载外部连接 | 未明确授权前不安装或注册真实 Gateway | V6+ |
| MarketDataPort | 定义 Port | Adapter 实现 | 历史固化数据仍以 Parquet 为准 | V4 |
| OrderIntent | 保留 | 不替换 | 禁止策略直接产生 OrderRequest | 后续交易阶段 |
| 确定性风险引擎 | 保留 | Risk Manager 只能追加保护 | 项目风控是最终强制关卡 | 后续交易阶段 |
| 人工确认/Kill Switch | 保留 | 不委托 | 任何适配器均不可绕过 | 后续交易阶段 |
| A 股回测 | 自有引擎为主 | 仅可选对照 | 必须输出差异，不隐藏规则缺口 | V5 |
| MockBroker/PaperBroker | 自有实现 | 不替换 | 无 vn.py 环境也必须可运行 | 后续交易阶段 |
| 审计日志 | 保留追加式审计 | 运行时日志作为输入 | 日志事件需脱敏和映射 | V3 |
| AI | 保留建议层 | 不接触 MainEngine/Gateway | 依赖方向用架构测试固定 | 持续 |

## 3. 官方 4.4.0 兼容性矩阵

| 项目 | 当前环境/项目 | vn.py 4.4.0 | 评估 |
| --- | --- | --- | --- |
| 操作系统 | Windows 11，64 位 | 官方列出 Windows | 表面兼容，仍需隔离验证 |
| Python | 项目 `>=3.11,<3.14`；本机 3.13.0 | `>=3.10`，列出 3.13 | 版本范围兼容 |
| 依赖管理 | uv；核心项目使用项目级 `.venv` | 官方使用 `pyproject.toml` | 若评估必须另建隔离兼容性环境 |
| PySide6 | 未安装 | 固定 `6.8.2.1` 且为核心依赖 | 体积和 Qt 运行时冲突风险高 |
| TA-Lib | 未安装 | `>=0.6.4` 且为核心依赖 | Windows wheel/原生库需单独验证 |
| NumPy | 项目未声明；系统全局已安装 | `>=2.2.3` | 必须以锁文件验证，不能使用全局包 |
| pandas | 项目未声明；系统全局已安装 | `>=2.2.3` | 与 Phase 2A 数据栈需锁定兼容版本 |
| Polars | 未安装 | 仅 `alpha` extra 使用 | V0–V4 不安装 alpha extra |
| PyArrow | Phase 2A 未引入，Parquet 使用 DuckDB | 仅 `alpha` extra 声明 `>=19.0.1` | 不依赖 alpha extra |
| XtQuant/QMT | 未发现 | 不属于核心包 | 未授权前不安装、不连接 |
| 许可证 | 项目待补 notices | MIT | 引入依赖时补第三方声明 |

## 4. 最大兼容性风险

1. `MainEngine()` 构造时会启动 EventEngine，并调用 `os.chdir(TRADER_DIR)`；嵌入 FastAPI 会改变整个进程的当前目录。
2. PySide6、TA-Lib、NumPy、pandas 是 vn.py 核心依赖，而非可选 GUI 依赖；即使 headless 使用也会增加环境耦合。
3. Gateway 常含 Windows 原生库、专属 Python ABI 和账户单例限制，不能与 Web 后端默认环境混装。
4. OMS 只表示实时外部状态，不能替代项目的业务状态、幂等控制和追加式审计。
5. 当前 A 股数据领域已建立，但回测和 PaperBroker 尚未实现；不能以“迁移”为名让 vn.py 对象替代项目领域模型。

## 5. 官方依据

- [vn.py 4.4.0 PyPI 元数据](https://pypi.org/project/vnpy/4.4.0/)
- [vn.py 4.4.0 pyproject.toml](https://github.com/vnpy/vnpy/blob/4.4.0/pyproject.toml)
- [vn.py 4.4.0 MainEngine](https://github.com/vnpy/vnpy/blob/4.4.0/vnpy/trader/engine.py)
- [vn.py 4.4.0 EventEngine](https://github.com/vnpy/vnpy/blob/4.4.0/vnpy/event/engine.py)
- [vn.py MIT License](https://github.com/vnpy/vnpy/blob/4.4.0/LICENSE)
