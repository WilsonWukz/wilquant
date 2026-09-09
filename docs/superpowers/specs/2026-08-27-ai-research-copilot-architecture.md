# wilquant AI Research Copilot 架构设计

- 状态：已设计；AI-1 已稳定，AI-2 `EVIDENCE & TEMPORAL VALIDATION STABLE`，停止在 AI-3 之前
- 日期：2026-08-27
- 范围：AI 研究分析、证据追溯、案例记忆、研究论点、上下文 Copilot 与草稿动作
- 前置边界：Phase 5 PAPER、Phase 6A LIVE + Multi-Market Architecture、ADR-0002

## 1. 结论

wilquant 应建设一个以证据为中心、可追溯、时间安全、无执行权限的 AI Research Copilot，而不是通用聊天框，也不是自主交易 Agent。

采用以下总体结构：

```text
Immutable WIL Data / Backtest / Research / exported PAPER facts
                         |
                         v
                  ResearchCase
                  as_of + cutoff
                         |
                         v
              deterministic EvidencePack
                         |
                         v
          Core-owned AIAnalysisRun + fingerprints
                         |
          authenticated one-run request envelope
                         v
              isolated AI Provider Host
          provider SDK + AI secret, no database
                         |
                         v
              raw model response artifact
                         |
                         v
         Core-owned six-layer validation pipeline
                         |
              +----------+----------+
              |                     |
              v                     v
      Stage 1 Diagnosis       validation failure
              |
              v
       deterministic ResearchGate
              |
       PROCEED only
              v
      Stage 2 ResearchRecommendation
              |
              v
   Summary / Evidence / Trace / Cases / Conversation
              |
              v
      allowlisted Drafts -> explicit user confirmation

No path to RiskPolicy, CapitalAuthorization, ExecutionApproval,
ExecutionGateway, BrokerAdapter, Broker credential, BrokerOrder or Fill.
```

Core 掌握事实、时间截断、Prompt 版本、输入输出指纹、校验、审计、记忆和草稿确认；AI Provider Host 只完成无副作用推理。任何 AI 故障只会使对应 `AIAnalysisRun` 失败或中止，不能改变 Backtest、PAPER 或 LIVE 的状态。

> Inspired by architectural patterns observed in PA_Agent; implementation must be independent.

## 2. AI-1 / AI-2 实施边界

AI-1 Provenance Foundation 已按批准边界实现并通过完整质量门；AI-2 Evidence, Grounding & Temporal Validation 已实现，正在收口正式合同：

- 允许新增显式 EvidenceResolver、EvidencePack、ValidationResult、ResearchCaseDocument、RetrievalSnapshot、FTS5 derived index、deterministic validators 与 ResearchGate；
- 不安装 LLM SDK；
- 不创建空目录；
- 不配置或读取真实 AI API Key；
- 不修改 Phase 6A 的 LIVE state machine、ExecutionGateway、BrokerAdapter 或 Capital Authorization；
- 不实现 Provider Host、模型调用、chat、recommendation execution 或 UI；
- 不实现 embedding、跨市场检索或 PAPER/LIVE 写操作；
- 已停止，不进入 AI-3。

AI-2 详细合同见 `2026-08-30-ai-2-evidence-temporal-validation-design.md`。AI-3～AI-8 仍是后续独立实现草案。

### 2.1 Goals

- 把 AI 建成可引用确定性事实的研究诊断与建议层；
- 记录可复现的 case、evidence、Prompt、model、attempt、validation、trace 和 usage；
- 用 temporal cutoff 阻止历史研究看到未来数据或未来案例；
- 支持 CN A-share 与 US stocks/ETFs 的统一、market-neutral 研究契约；
- 支持两阶段诊断、ResearchGate、案例记忆、增量 thesis 和上下文 Copilot；
- 让所有有副作用的研究动作先成为草稿并由用户确认；
- 保持 AI 故障、credential 和权限与 PAPER/LIVE 完全隔离。

### 2.2 Non-Goals

- 不做 autonomous trading、order routing、position sizing 或 capital allocation；
- 不用 LLM 取代 MarketRules、RiskEngine、Comparison、Diagnostics 或 reconciliation；
- 不把 ResearchCase 当作事实数据库；
- 不把 model confidence 当作胜率；
- 不复制 PA_Agent 的代码、Prompt、决策树、文件 schema 或 GUI；
- 不在 AI-1 实现 Provider Host、模型分析、Copilot、case retrieval、draft execution 或 UI。

## 3. 术语与事实标签

AI 输出必须对可审计陈述使用下列标签：

| 标签 | 含义 | 允许来源 |
|---|---|---|
| `FACT` | 可由已绑定证据直接验证的事实 | `EvidenceRef` 指向的不可变数据或规则 |
| `INFERENCE` | 从一个或多个 FACT 推导的解释 | 必须引用证据并说明推导 |
| `HYPOTHESIS` | 尚待实验或新数据验证的假设 | 必须给出验证与失效条件 |

没有证据的陈述不能标记为 FACT。模型的自然语言、自报置信度或“常识”都不是系统事实。

## 4. PA_Agent 参考研究

### 4.1 研究范围

本次研究覆盖 PA_Agent 的 README、使用文档以及 `pa_agent/ai`、`orchestrator`、`records`、`data`、`security`、`gui`、`experience`、`prompt_engineering` 和 `config` 的公开内容。只研究架构模式，不复制源代码、Prompt 文本、策略文件、决策树或字段集合。

### 4.2 已观察事实

- `FACT`：PA_Agent 定位为读取 K 线后执行“市场诊断 → 交易决策”的两阶段 AI 辅助工具，并明确不连接券商、不执行下单。[README](https://github.com/rosemarycox5334-debug/PA_Agent#readme)
- `FACT`：其 `TwoStageOrchestrator` 组织 Prompt、模型调用、结构化校验、策略路由、经验加载、部分记录持久化和重试；当前文件约 1268 行。[two_stage.py](https://github.com/rosemarycox5334-debug/PA_Agent/blob/main/pa_agent/orchestrator/two_stage.py)
- `FACT`：`validation_retry` 会按错误分类决定重试，并检测重试后对未被反馈点名字段的可疑改写。[validation_retry.py](https://github.com/rosemarycox5334-debug/PA_Agent/blob/main/pa_agent/orchestrator/validation_retry.py)
- `FACT`：`JsonValidator` 区分语法、缺字段、非法值、纯文本和 provider 错误，并包含跨字段与行情约束。[json_validator.py](https://github.com/rosemarycox5334-debug/PA_Agent/blob/main/pa_agent/ai/json_validator.py)
- `FACT`：决策树、连续性检查和 UI trace 将模型结论变成可查看路径；gate 为 wait/unknown 时可短路第二阶段。[decision_tree.py](https://github.com/rosemarycox5334-debug/PA_Agent/blob/main/pa_agent/ai/decision_tree.py) [decision_continuity.py](https://github.com/rosemarycox5334-debug/PA_Agent/blob/main/pa_agent/ai/decision_continuity.py)
- `FACT`：分析记录包含 K 线、两阶段消息、原始响应、结构化结果、策略文件、经验条目、异常和用量；自由对话锚定已完成分析并写入 JSONL sidecar。[schema.py](https://github.com/rosemarycox5334-debug/PA_Agent/blob/main/pa_agent/records/schema.py) [free_chat.py](https://github.com/rosemarycox5334-debug/PA_Agent/blob/main/pa_agent/orchestrator/free_chat.py)
- `FACT`：增量分析按 symbol/timeframe 找最近成功文件记录，并以已收盘 K 线时间戳计算新增 bar。[analysis_history.py](https://github.com/rosemarycox5334-debug/PA_Agent/blob/main/pa_agent/records/analysis_history.py)
- `FACT`：`ExperienceReader` 先按周期目录读取 success/failure JSON，再以时间、方向和模式重排。[experience_reader.py](https://github.com/rosemarycox5334-debug/PA_Agent/blob/main/pa_agent/records/experience_reader.py)
- `FACT`：`TradeLogger` 把“订单机会”及图表输出到本地 CSV/图片；它是分析结果记录，不是 Broker order/fill execution，wilquant 不应借用其命名来模糊 PAPER/LIVE 边界。[trade_logger.py](https://github.com/rosemarycox5334-debug/PA_Agent/blob/main/pa_agent/records/trade_logger.py)
- `FACT`：`KlineFrame`/`DataSource` 提供数据源抽象，但标的上下文主要仍由 symbol、timeframe 和数据源表达。[data/base.py](https://github.com/rosemarycox5334-debug/PA_Agent/blob/main/pa_agent/data/base.py)
- `FACT`：`PromptAssembler`、config 与 PyQt GUI 分别承载大量 Prompt 组装、provider/settings 和界面编排职责；wilquant 只研究职责分层，不复制 Prompt 内容、配置 schema 或 GUI 实现。[prompt_assembler.py](https://github.com/rosemarycox5334-debug/PA_Agent/blob/main/pa_agent/prompt_engineering/prompt_assembler.py) [config](https://github.com/rosemarycox5334-debug/PA_Agent/tree/main/pa_agent/config) [gui](https://github.com/rosemarycox5334-debug/PA_Agent/tree/main/pa_agent/gui)
- `FACT`：公开使用文档宣称 Windows DPAPI 加密 API Key；但当前 `pa_agent/security` 目录只有 `__init__.py`，当前 `settings.py` 的持久化路径仍包含 `api_key` 字段，文档与当前源码存在需要维护者澄清的差异。[使用文档](https://github.com/rosemarycox5334-debug/PA_Agent/blob/main/PA_Agent%E4%BD%BF%E7%94%A8%E6%96%87%E6%A1%A3.md) [settings.py](https://github.com/rosemarycox5334-debug/PA_Agent/blob/main/pa_agent/config/settings.py)
- `FACT`：项目公开许可证为 AGPL-3.0-or-later。[LICENSE](https://github.com/rosemarycox5334-debug/PA_Agent/blob/main/LICENSE)

### 4.3 可借鉴矩阵

| PA_Agent 模式 | 借鉴价值 | wilquant 独立实现方式 | 不借用内容 |
|---|---|---|---|
| 两阶段诊断/决策 | 先理解再建议，降低一步生成混乱 | `ResearchDiagnosis -> ResearchGate -> ResearchRecommendation` | 类名、Prompt、字段、交易决策树 |
| 校验失败分类与重试 | 避免把所有模型错误当成同一种失败 | 六层 validator + retry class + immutable fact drift | category 字母、反馈文案、cheat 规则代码 |
| 决策路径可视化 | 提升可解释性 | Core 生成 `AnalysisTraceEvent` 与 validator results | PA 决策节点、节点编号、动画实现 |
| 分析记录全落盘 | 支持追溯和复盘 | 版本化表 + content-addressed artifacts + fingerprints | PA JSON 文件 schema 与文件名约定 |
| 增量分析 | 延续上下文并减少重复成本 | 新 `ResearchCase` 链接旧 run/thesis revision，仍保存完整新结果 | “最近文件”查找、K 序号语义 |
| 经验库 | 历史案例辅助判断 | 时间安全的结构化过滤 + lexical/embedding hybrid retrieval | 目录树、success/failure 文件格式 |
| 分析后追问 | 用户可对结论深挖 | 锚定 ResearchCase/Run 的 Copilot conversation | 通用聊天、原始消息拼装方式 |
| DataSource/KlineFrame | 隔离数据适配器 | 使用 wilquant DatasetVersion/MarketDataProfile/Instrument/MarketRules | symbol 作为身份、provider 直接喂模型 |
| Provider config | 支持多模型 | broker-neutral 风格的 `AIProvider` contract | provider-specific client 逻辑与配置文件 |

### 4.3.1 PA_Agent ↔ wilquant 完整对照矩阵

| 领域 | PA_Agent | wilquant 当前状态 | Gap | Recommendation | 分类 |
|---|---|---|---|---|---|
| Market Data | 多个实时/外部 K 线 adapter，统一为 KlineFrame | 不可变 DatasetVersion、Profile、Calendar、Parquet/DuckDB | 缺 realtime research snapshot contract | 历史/实时 provider 分离后只生成 EvidenceRef | `ADAPT` / `ALREADY SUPERIOR` |
| Data Versioning | 分析记录保存一次 K 线内容，版本 identity 较弱 | 数据、日历、策略、运行均有版本和 fingerprint | AI 尚未绑定这些版本 | ResearchCase/EvidencePack 冻结全部 version fingerprint | `ALREADY SUPERIOR IN WIL_QUANT` |
| Backtest | 不负责正式可复现回测 | 有确定性 BacktestEngine 和 artifacts | AI 尚不能解释 artifacts | 只读消费 run/metric/artifact hash | `ALREADY SUPERIOR IN WIL_QUANT` |
| Research | 以单次/增量价格行为分析为主 | Experiment、Comparison、Diagnostics、Report、Journal | 缺 AI diagnosis/recommendation | 在现有 Research Domain 上增设受限 AI 层 | `ADAPT` |
| PAPER | 不负责 broker execution；记录“交易机会” | 事务性 PaperSession/Order/Fill/Ledger/Audit | AI 尚无只读 PAPER evidence snapshot | 以后仅导出 read-only EvidenceRef，绝不写 PAPER | `DO NOT BORROW` / `ALREADY SUPERIOR` |
| Risk | Prompt/validator 中含交易约束 | 确定性 RiskEngine 和不可变 RiskDecision | AI 解释与风险事实尚无接口 | AI 只引用 RiskDecision，不参与计算/批准 | `ALREADY SUPERIOR IN WIL_QUANT` |
| Execution | 明确不连接 Broker、不发送订单 | Phase 6A 已设计资本、Gateway、UNKNOWN、reconciliation | AI 必须永久在授权线外 | 无 AI→Gateway 路径 | `DO NOT BORROW` |
| AI Analysis | 成熟两阶段、策略路由、流式结果 | 尚无 LLM runtime | 缺受证据约束的两阶段能力 | Diagnosis→deterministic Gate→Recommendation | `ADAPT` |
| Experience Memory | 周期目录 + success/failure JSON + 近期/标签排序 | 无正式 AI case memory | 缺 temporal-safe retrieval | 结构化 hard filters + lexical/optional embedding | `ADAPT` |
| Provenance | 保存 Prompt、raw、parsed、usage、follow-up 文件 | 已有版本/hash/audit 基础，但无 AI run | 缺 Prompt/model/attempt/trace provenance | append-only AIAnalysisRun 聚合 | `BORROW` concept / independent design |
| Validation | JSON、跨字段、语义、截断、分类重试 | 业务领域已有强确定性校验 | 缺模型输出 grounding/temporal 校验 | 六层 validator + fail closed retry policy | `ADAPT` |
| Incremental Analysis | 找最近成功记录并按新增 bar 延续 | 历史 runs 不漂移，但无 AI parent chain | 缺 thesis continuity/delta | 新 case/new run + parent link + full result | `ADAPT` |
| Decision Trace | gate/decision tree 与可视化路径 | 有 audit/diagnostic，但无 AI trace | 缺 AI 与 deterministic 分层展示 | TraceEvent + TraceNode，禁止照搬 PA 节点 | `ADAPT` |
| Conversation | 分析完成后锚定记录追问并落盘 | 无 Copilot | 缺证据引用和动作边界 | context snapshot + cited turns + draft only | `ADAPT` |
| UI | PyQt 分栏、决策树、raw/debug、conversation | React Research Workspace | 缺 AI 六 tab 与证据跳转 | 保持 React 体系，借 UX 信息层级不借 GUI | `DO NOT BORROW` implementation |
| Security | 文档宣称本地加密，但当前源码/文档有差异 | Phase 6A 已有 credential isolation 威胁模型 | 缺 AI secret store | AI/Broker secret 分进程、分 namespace、独立验收 | `DO NOT BORROW` implementation |

### 4.4 优点与局限

PA_Agent 的优点：

- 两阶段工作流、短路 gate、增量追踪和分析后追问形成完整研究体验；
- 有结构化输出、校验、重试、连续性检查和 trace，而非只展示自然语言；
- 记录原始输入输出和 token 用量，便于问题定位；
- tests 按 unit/property/integration/e2e 组织，重视模型边界的确定性测试。

wilquant 不应继承的局限：

- `INFERENCE`：超大 orchestrator、validator 和 prompt assembler 将 UI 流、领域规则、Prompt、provider 和持久化耦合，后续演化风险高；
- `INFERENCE`：按 symbol/timeframe 和最近文件检索历史，无法满足 wilquant 的 multi-market identity、不可变版本和严格 temporal cutoff；
- `INFERENCE`：经验检索以最近文件和少量标签为主，缺少数据版本、规则版本、可比性和未来信息泄漏控制；
- `INFERENCE`：交易倾向与置信度门槛紧邻“订单机会”表达，不适合带真实资金边界的 wilquant；
- `FACT`：密钥文档与当前源码表现不一致，因此 wilquant 必须对 secret storage 自行设计、测试和验收，不能把文档声明当成安全事实。

### 4.5 wilquant 当前更强的基础

wilquant 已经优于该参考项目的部分是：不可变 DatasetVersion/StrategyVersion、MarketDataProfile 与交易日历绑定、artifact hash、回测可比性、确定性 ExecutionKernel、事务性 PAPER、追加式资金审计，以及 Phase 6A 的多市场、资本授权、UNKNOWN、reconciliation、Gateway 隔离和 mapping 设计。

AI 架构必须消费这些既有事实，不能用 Prompt 或模型输出重新定义它们。

## 5. 方案选择

### 方案 A：现有 ResearchPage 增加通用聊天框

优点是快；缺点是没有 EvidencePack、时间截断、结构化校验、运行 provenance 和受控动作。否决。

### 方案 B：外部自主 Agent 直接调用 wilquant API

可扩展，但工具权限与真实资金边界难以静态证明，provider 故障会放大为业务副作用。否决。

### 方案 C：Core 控制面 + 隔离 AI Provider Host

采用。Core 冻结证据、Prompt、模型配置、校验和动作白名单；Provider Host 只有 AI inference 能力。它保留多 provider 能力，又让 AI 故障和密钥与 Backtest/PAPER/LIVE 隔离。

## 6. 信任边界与权限

### 6.1 Actor 能力矩阵

| 能力 | USER | Research Core | AI/Strategy | RiskEngine | ExecutionGateway |
|---|---:|---:|---:|---:|---:|
| 创建 ResearchCase | 是 | 代用户编排 | 否 | 否 | 否 |
| 生成诊断/建议 | 可请求 | 校验/保存 | 是，仅建议 | 否 | 否 |
| 创建 ExperimentDraft | 确认 | 是 | 仅可建议草稿 | 否 | 否 |
| 创建 BrokerOrder/Fill | 否，须走 LIVE 链 | 否 | **永不允许** | 否 | 仅按有效 Approval dispatch |
| 修改 RiskPolicy | 按既有权限 | 否 | **永不允许** | 只能执行既有版本 | 否 |
| 增加 CapitalAuthorization | 仅 USER | 否 | **永不允许** | 否 | 否 |
| 解冻/解除 kill | 仅既有 USER 恢复流程 | 否 | **永不允许** | 否 | Gateway 不能替 Core 解冻 |
| 激活 LIVE | 仅既有 USER 流程 | 否 | **永不允许** | 否 | 否 |
| 读取 Broker credential | 否 | 否 | **永不允许** | 否 | 仅 Broker secret namespace |

### 6.2 不可跨越规则

1. `ResearchRecommendation`、confidence、stance、TradeThesis 都不是授权。
2. AI 不能构造或提交 `ExecutionRequest`/`ExecutionApproval`。
3. AI module 不导入 Gateway client、BrokerAdapter、LIVE state mutation service 或 Broker secret store。
4. AI 可以读取显式导出的只读研究证据，但不能持有 PaperRepository/LiveRepository 写句柄。
5. AI 输出永远不能改变资本额度、风险版本、冻结、kill 或 reconciliation state。
6. 即使用户在 Conversation 中要求下单，Copilot 也只能解释边界或创建允许的研究草稿。

## 7. 模块边界

后续独立实现建议使用以下职责，不在本轮创建目录：

```text
backend/src/quant_lab/ai/
    domain.py              enums/value objects, no I/O
    schemas.py             provider-neutral structured contracts
    fingerprints.py        canonicalization and SHA-256
    cases.py               ResearchCase service and temporal cutoff
    evidence.py            EvidencePack assembly and EvidenceRef
    provenance.py          AIAnalysisRun / AIAnalysisAttempt / Trace services
    orchestration.py       stage transitions only
    gates.py               deterministic ResearchGate
    validation/            six focused validators + retry policy
    retrieval.py           temporal-safe case retrieval
    theses.py              append-only thesis lifecycle
    copilot.py             context-bound conversation
    drafts.py              allowlisted draft creation/confirmation
    providers/             AIProvider port, fake, IPC client
    security.py            AI secret references/status, no Broker secret

backend/src/quant_lab/ai_provider_host/
    main.py                separate process entrypoint
    protocol.py            versioned request/response envelope
    runtime.py             SDK lifecycle/timeouts/cancellation
    secrets.py             Windows Credential Manager/DPAPI adapter

backend/src/quant_lab/api/
    ai_research.py         HTTP DTO only
```

每个文件只承担一种职责。不得重建 PA_Agent 式单个千行 orchestrator 或 prompt assembler。

## 8. ResearchCase 与时间截断

`ResearchCase` 是所有 AI 分析的不可变根输入：

```text
ResearchCase
  case_id
  case_schema_version
  purpose
  market
  exchange
  symbol
  instrument_id
  asset_type
  currency
  timeframe
  session_type
  universe_id / universe_fingerprint
  time_range_start / time_range_end
  as_of_utc
  market_local_trade_date
  temporal_cutoff_policy
  market_data_profile_id/version fingerprint
  dataset_version_ids/fingerprints
  trading_calendar_version_id/fingerprint
  market_rules_version_id/fingerprint
  strategy_version_ids/fingerprints
  backtest_run_ids/input fingerprints
  research_experiment_id/version
  paper_session_snapshot_id/fingerprint?
  feature_signature
  market_regime?
  outcome_metrics?
  diagnosis_summary?
  success_factors[] / failure_factors[]
  case_type
  valid_from / case_end_at
  previous_case_id?
  previous_analysis_run_id?
  thesis_revision_id?
  case_fingerprint
  created_by
  created_at_utc
```

### 8.1 Temporal cutoff

- 证据必须同时记录 `effective_at`、`known_at`、`captured_at` 和 source version；
- 历史研究只能纳入 `known_at <= as_of_utc` 的信息；
- bar 必须已关闭，且 market-local session close 不晚于 cutoff；
- 案例检索必须先做 cutoff 过滤，再做相似度排序；
- 任何 backtest artifact 都需验证 run 的 data range 不越过 case cutoff；
- current/realtime case 也必须冻结一次 snapshot，禁止模型在两阶段之间自行刷新数据；
- 若用户要刷新，创建新 ResearchCase，旧 run 不漂移。

## 9. EvidenceRef 与 EvidencePack

`EvidenceRef` 是可验证引用，不是任意 URL：

```text
EvidenceRef
  evidence_ref_id
  evidence_type
  source_entity_type / source_entity_id
  source_version_id
  content_sha256
  locator              # row range, artifact section, metric key, rule key
  effective_at
  known_at
  captured_at
  market / instrument_id / currency
  temporal_status      # ELIGIBLE / FUTURE / STALE / CONFLICT
  integrity_status
  excerpt              # bounded, optional, derived
```

`EvidencePack` 保存有序 EvidenceRef、确定性派生 facts、检索快照与 canonical fingerprint。模型只能引用 pack 中存在的 ref；不得直接访问 Dataset、DuckDB、网络行情或文件系统。

证据类型第一版包括：

- Instrument identity 与 MarketRules；
- DatasetVersion/MarketDataProfile/TradingCalendarVersion；
- 受 cutoff 约束的 OHLCV/coverage/quality facts；
- BacktestRun input、metrics、artifact hashes、comparison 与 diagnostics；
- ResearchExperiment、journal snapshot、ResearchThesis revision；
- Comparison、Diagnostic、ResearchReport；
- 后续显式导出的 PaperSession、RiskDecision、EquitySnapshot、order/fill observation snapshot；
- 结构化 case retrieval results。

## 10. 历史与实时数据 Provider 分离

```text
HistoricalResearchDataProvider
  immutable DatasetVersion only
  reproducible range query
  strict as_of cutoff

RealtimeResearchDataProvider
  current observation only
  captured snapshot ID + source timestamp + freshness
  never used to rewrite historical runs
```

二者返回相同的证据 DTO，但 provenance 和 freshness 规则不同。Realtime provider 的数据如果无法证明时间、标的 mapping 或完整性，标记 `UNVERIFIED` 并使 ResearchGate abstain，不能由模型“看起来合理”而升级为 FACT。

`MarketDataFreshnessClass` 正式定义为 `IMMUTABLE_HISTORICAL / EOD / DELAYED / REALTIME`。每个未来的 `AIAnalysisContext` 必须保存 `source`、`observed_at`、`market_timestamp`、`freshness_class`、`known_delay_seconds` 与 `snapshot_fingerprint`。ResearchGate 按 analysis type 判断 freshness 是否足够；第一版 REALTIME research 建议要求 snapshot age 不超过 30 秒，超过返回 `STALE_MARKET_DATA`。

已知 15 分钟延迟源必须标记 `DELAYED`，只能用于允许延迟数据的研究任务。yfinance 等来源只可按经过验证的能力用于 historical/EOD/delayed research，不得默认视作 LIVE execution-quality market state。AI research freshness 与 Phase 6 broker/account snapshot freshness 是两个独立指标，绝不复用阈值或状态。

## 11. 两阶段分析与 ResearchGate

### 11.1 Stage 1：ResearchDiagnosis

Stage 1 只做研究诊断：

```text
ResearchDiagnosis
  diagnosis_schema_version
  fact_statements[]           # FACT + EvidenceRef
  inference_statements[]      # INFERENCE + supporting refs
  hypotheses[]                # HYPOTHESIS + test/invalidation
  observed_regime
  trend_assessment
  volatility_regime
  cross_sectional_dispersion
  breadth_assessment
  liquidity_assessment
  factor_regime
  market_stress
  portfolio_concentration
  recent_strategy_degradation
  data_quality_assessment
  conflicting_evidence[]
  missing_evidence[]
  uncertainty_factors[]
  market_context
  diagnosis_summary
```

Stage 1 不能输出订单、仓位、资金分配或 CapitalAuthorization 建议。

### 11.2 ResearchGate

ResearchGate 由 Core 的确定性规则计算，模型不能自我放行：

| 结果 | 含义 | Stage 2 |
|---|---|---|
| `PROCEED` | 证据、时间、完整性和 Stage 1 校验均通过 | 允许 |
| `WAIT_FOR_EVIDENCE` | 数据未闭合、过旧或缺少必要证据 | 禁止 |
| `ABSTAIN` | 冲突或不确定性超过 policy | 禁止 |
| `REJECT` | temporal leak、integrity failure、immutable drift 或越权输出 | 禁止 |

Gate 同时输出确定性 `reason_codes`，第一版至少包括：

```text
INSUFFICIENT_DATA
NOT_COMPARABLE
STALE_MARKET_DATA
NO_RELEVANT_CASES
LOW_EVIDENCE_QUALITY
RECONCILIATION_PENDING
TEMPORAL_LEAKAGE
INTEGRITY_FAILURE
IMMUTABLE_FACT_DRIFT
UNAUTHORIZED_CAPABILITY
PROCEED
```

`RECONCILIATION_PENDING` 只是读取已有事实后阻止“readiness”类强建议；AI 不能运行或改变 reconciliation。

Gate 输入与输出全部写入 trace，并绑定 validator policy fingerprint。

### 11.3 Stage 2：ResearchRecommendation

```text
ResearchRecommendation
  recommendation_schema_version
  diagnosis_run_id
  recommendation_summary
  stance                    # BULLISH/BEARISH/NEUTRAL/NO_VIEW
  confidence_level          # LOW/MEDIUM/HIGH, ordinal only
  confidence_score?         # optional 0..100 ordinal, not probability
  key_factors[]             # EvidenceRef required
  alternative_explanations[]
  risks[]
  invalidation_conditions[]
  watch_items[]
  suggested_actions[]       # allowlisted draft descriptors only
```

confidence 表示“在当前 evidence pack 下结论的相对支持程度”，不是经校准的胜率、收益概率或风险预算。UI 必须显示这一语义。stance/confidence 不得进入 RiskEngine 或 CapitalAuthorization 计算。

若未来新增 `predicted_win_probability`，必须先经过 historical calibration、out-of-sample validation、reliability curve 和 Brier score 验收，并与 LLM self-assessment 分表/分字段；在此之前禁止展示为概率。

若未来提供 conservative/balanced/aggressive 等 stance，它最多影响建议措辞、hypothesis breadth 和 research exploration threshold，绝不能影响 RiskPolicy、CapitalAuthorization、max order notional、LIVE activation 或 quantity。

### 11.4 Suggested action allowlist

仅允许：

```text
CREATE_EXPERIMENT_DRAFT
CREATE_BACKTEST_DRAFT
COMPARE_RUNS_DRAFT
APPEND_THESIS_REVISION_DRAFT
ADD_RESEARCH_JOURNAL_DRAFT
REFRESH_RESEARCH_CASE_DRAFT
REVIEW_STRATEGY
WAIT_FOR_MORE_DATA
REVIEW_PAPER_RESULTS
```

不允许任意 tool name、URL、SQL、Python、Paper/LIVE action 或自由参数。每个 descriptor 先通过 schema/semantic validation，再由 Core 创建 `ExperimentDraft` 等草稿。只有 USER 显式确认后，既有 service 才执行对应研究动作。

## 12. 六层校验体系

校验按顺序执行，任何一层失败都不能被后一层“修正通过”：

1. **Syntax**：JSON/transport 完整、字符与大小限制、无多余 payload。
2. **Schema**：版本化 DTO、required/enum/type/additionalProperties。
3. **Semantic**：跨字段约束、FACT/INFERENCE/HYPOTHESIS 语义、action allowlist、gate/stage 一致性。
4. **Grounding**：所有 FACT 与关键因素引用有效 EvidenceRef，引用内容支持陈述，不能伪造 locator。
5. **Temporal**：EvidenceRef 未越过 as_of，bar 已关闭，retrieval case 当时可知，无未来 artifact。
6. **Immutable facts**：instrument、market、currency、rules、versions、cutoff、指标值等与冻结输入完全一致。

### 12.1 Retry 分类

| 失败 | 是否可自动 retry | 规则 |
|---|---|---|
| provider timeout/429/5xx | 有界重试 | 同一 input fingerprint，新 Attempt，指数退避 |
| syntax/truncation | 有界重试 | 不允许修改事实包或模板版本 |
| schema 缺字段 | 有界重试 | feedback 只指出 schema path |
| 可修复 semantic | 最多一次 | 不能重写未被反馈涉及的不可变字段 |
| grounding failure | 默认不重试 | 需要新 run 或人工检查证据 |
| temporal violation | 永不重试当前 run | `REJECTED_TEMPORAL` |
| immutable fact drift | 永不重试当前 run | `REJECTED_FACT_DRIFT` |
| unauthorized action | 永不重试当前 run | `REJECTED_CAPABILITY` |

每次模型调用产生独立 `AIAnalysisAttempt`。重试不能覆盖原响应；成功也不能删除失败 attempt。若任何输出试图改变冻结事实，整个 run fail closed。

## 13. Provenance 与 AnalysisTrace

### 13.1 PromptTemplateVersion

Prompt 不以可变文件名作为身份。每个模板版本保存：

```text
template_version_id
template_name
stage
schema_version
content_sha256
variable_contract_sha256
validator_policy_version
created_at / created_by
status
```

运行时额外保存 resolved prompt hash、EvidencePack hash、ResearchCase hash 和完整 request envelope hash。模板发布后不可更新，只能发布新版本。

### 13.2 Model config provenance

`AIModelConfigVersion` 至少冻结 provider kind、model identifier、ProviderProfile identity、temperature/top_p、max output、timeout、reasoning setting、structured output mode、tool configuration 和 compatibility flags。`ProviderProfile` 冻结 `provider_id`、`base_url_identity`、model、supported capabilities、reasoning mode、JSON/schema capability 与 streaming capability。system prompt 通过 PromptTemplateVersion 独立冻结；早期 tool configuration 固定为 `NONE`。secret 只保存 `secret_ref` 与 configured 状态，绝不进入版本内容、日志或 fingerprint。

### 13.3 AIAnalysisRun

```text
run_id / run_schema_version
case_id / case_fingerprint
analysis_type / stage
analysis_mode                 # FULL / INCREMENTAL
status                        # CREATED/RUNNING/VALIDATING/COMPLETED/REJECTED/FAILED/CANCELLED
parent_run_id?
as_of_utc
dataset/calendar/market-data-snapshot fingerprints
experiment_id? / backtest_run_ids[] / paper_session_snapshot_id?
prompt_template_version_id
prompt_template_fingerprint
resolved_prompt_fingerprint
evidence_pack_id / fingerprint
model_config_version_id / fingerprint
validator_policy_version / fingerprint
retrieval_snapshot_id / fingerprint
input_envelope_fingerprint
raw_response_artifact_sha256?
parsed_output_json/artifact_sha256?
normalized_output_fingerprint?
validation_status / validation_result_json
started_at / completed_at
failure_code / safe_failure_message
```

### 13.4 AIAnalysisAttempt 与 AIUsage

每次调用保存 provider request ID、attempt number、input/output hash、latency、finish reason、prompt/cached/completion/total tokens、provider-reported cost（若有）、本地估算成本、currency 和 estimation flag。用量可按 Experiment、AnalysisRun、Month 和 Model 聚合；仅供审计和研究预算提示，不影响资本。

### 13.5 AnalysisTrace

Trace 是 append-only 事件流：

```text
CASE_FROZEN
EVIDENCE_ASSEMBLED
RETRIEVAL_COMPLETED
PROMPT_RESOLVED
PROVIDER_ATTEMPT_STARTED/FAILED/COMPLETED
VALIDATION_LAYER_PASSED/FAILED
RETRY_CLASSIFIED
DIAGNOSIS_ACCEPTED
RESEARCH_GATE_DECIDED
RECOMMENDATION_ACCEPTED
DRAFT_PROPOSED/CONFIRMED/REJECTED
RUN_CANCELLED/FAILED/COMPLETED
```

UI Raw 只显示 provider 实际返回且已脱敏的 payload、结构化输出、Prompt 元数据和 hash。系统不要求、推断或伪造隐藏 chain-of-thought；若 provider 不返回 reasoning，则 Raw 不显示。

面向用户解释路径的 `AnalysisTraceNode` 与基础事件分开，至少包含：

```text
node_id
category                  # DATA_GATE/MARKET_REGIME/STRATEGY_ELIGIBILITY/
                          # CASE_RETRIEVAL/RISK_OBSERVATION/RECOMMENDATION
question
evidence_refs[]
result
reason
next_node?
source                    # DETERMINISTIC / AI_VALIDATED
```

TraceNode 不采用 PA_Agent 的 Price Action 节点、编号或决策树内容。

## 14. 记忆、案例检索与增量分析

### 14.1 Temporal-safe retrieval

检索顺序必须固定：

1. hard temporal filter；
2. market/asset/instrument/timeframe/rules compatibility filter；
3. structured similarity（regime、diagnostic、strategy、data quality）；
4. lexical similarity；
5. 可选 embedding similarity；
6. diversity 与 max-per-source 限制；
7. 保存候选、分数分解、排除原因和 retrieval fingerprint。

向量检索不能绕过 hard filters。AI-2 第一版固定为 `hard filters -> deterministic structured similarity -> SQLite FTS lexical score -> rank`，不实现 embedding。hard filters 至少覆盖 market、asset_type、market-data/knowledge cutoffs、universe compatibility，以及仅在分析需要时启用的 MarketRules compatibility。strategy family 是高权重 structured score，不是默认 hard filter。Embedding 延后到独立阶段，并且永远不能绕过 hard filters。

ResearchCase 是 retrieval memory，不是 source of truth。它只能引用 DatasetVersion、BacktestRun、Experiment、Paper records 等事实；case 中的总结、标签或结果不能反过来覆盖源事实。

默认 `cross_market=false`。CN 与 US 案例不能跨市场进入高权重候选；未来只有显式设计 `cross_market=true`、规则兼容性和独立验收后才允许跨市场弱参考。

### 14.2 增量分析

增量不是修改旧 run：

```text
old ResearchCase + accepted run + thesis revision
                    |
          new immutable evidence/cutoff
                    v
             new ResearchCase
                    |
          new full diagnosis/recommendation
                    |
         delta summary links both runs
```

run 必须显式记录 `AnalysisMode=FULL|INCREMENTAL`。增量输出除完整新诊断/建议外，还必须包含：

```text
what_changed[]
what_did_not_change[]
previous_thesis_status
thesis_change = UNCHANGED | WEAKENED | STRENGTHENED | INVALIDATED
change_trigger_evidence_refs[]
```

旧结论只能作为标记为 historical context 的 EvidenceRef；新 run 必须重新验证全部事实、时间和规则。任何新增数据、MarketRulesVersion 或 instrument mapping 变化都会形成新 case fingerprint。

## 15. ResearchThesis 与 TradeThesis

### 15.1 ResearchThesis lifecycle

```text
PROPOSED -> ACTIVE -> CLOSED
                  -> INVALIDATED
                  -> SUPERSEDED
                  -> ARCHIVED
```

Thesis header 保存稳定 `thesis_id`；内容只存在于不可变 `ResearchThesisRevision`。新观点追加 revision，不能 UPDATE/DELETE 旧 revision。每个 revision 绑定 case/run/evidence、FACT/INFERENCE/HYPOTHESIS、支持与反对证据、失效条件、`UNCHANGED/WEAKENED/STRENGTHENED/INVALIDATED` 变化类型和作者（USER/AI_DRAFT）。只有 USER 可激活 AI 草稿。

`ResearchJournal` 与 `ResearchThesis` 永久分离。Journal 是 append-oriented 的用户/研究人员便笺，可承载 observation、hypothesis note、decision、todo 与 conclusion；Thesis 是具有 stable identity、immutable revisions、lifecycle、explicit evidence 与 invalidation condition 的结构化研究对象。AI 只能生成 `JournalDraft` 或 `ThesisRevisionDraft`，不能修改历史 Journal 或原地修改 Thesis revision；用户确认后只能追加新记录/新 revision，Journal 不迁移为 Thesis storage。

### 15.2 TradeThesis 的边界

`TradeThesis` 只解释 WHY：为什么某个策略/用户 Intent 值得研究、依赖哪些证据、何时失效。它不是：

- OrderIntent；
- RiskDecision；
- CapitalAuthorization；
- ExecutionRequest/Approval；
- position size 或资金授权。

候选字段至少为 `thesis_id`、`source_analysis_run_id`、`instrument_id`、`direction`、`thesis_summary`、`entry_rationale`、`risk_factors`、`invalidation_condition`、`evidence_refs` 和 `created_at`。

未来允许将已确认 TradeThesis ID 作为可选审计引用附到 Intent，但执行链完全忽略其 stance/confidence，不能因 AI 表述更强而增加数量或资本。

## 16. 上下文 Research Copilot

Copilot 不是首页通用聊天。每个 conversation 必须绑定一个或多个明确上下文：ResearchCase、AIAnalysisRun、Experiment、BacktestRun、StrategyVersion、DatasetVersion、ResearchReport、ResearchJournal snapshot、PaperSession snapshot、ResearchThesisRevision。

每轮：

1. 冻结 conversation context snapshot；
2. 只装载允许且时间合格的 EvidenceRef；
3. 保存用户消息、context hash、Prompt/model fingerprints；
4. 要求回答中的事实引用 EvidenceRef；
5. 保存独立 attempt、usage、validation 和 trace；
6. 若问题需要新行情，建议 `REFRESH_RESEARCH_CASE_DRAFT`，不静默刷新；
7. 若请求越权，返回 capability denial 并记录 `UNAUTHORIZED_ACTION_REQUESTED`。

Conversation 不能把旧回答当 FACT；旧回答只能作为 `PRIOR_AI_OUTPUT`，必须重新引用底层证据。

## 17. Multi-Market 兼容

AI 不定义市场规则。EvidencePack 必须显式包含：

```text
instrument_id
market / exchange / symbol / currency / asset_type
TradingCalendarVersion + market timezone + market-local trade date
MarketRulesVersion
quantity_step / minimum_quantity / minimum_notional / price_tick / round_lot
fractional_allowed
SettlementPolicy / SellabilityPolicy / CashAvailabilityPolicy
```

CN A-share 与 US stocks/ETFs 使用同一 ResearchCase/Diagnosis/Recommendation 契约。模型不能仅根据 symbol 猜 market，也不能用 “T+1” 单一布尔解释中美规则。US Data → Backtest → PAPER 的确定性事实完成后，AI 才能把对应版本纳入 US EvidencePack；AI track 不得以模型常识替代 Phase 6B foundation。

AIAnalysisContext 还必须显式包含 timezone、currency、asset_type 和 session_type。MarketRules 是 `DETERMINISTIC FACT`：AI 只能引用，不能自行解释、补全或猜测 A 股 T+1、涨跌停、round lot、美股 regular hours 等规则。

## 18. AIProvider 与 secret storage

### 18.1 Provider-neutral contract

```text
AIProviderCapabilities
  structured_output
  streaming
  reasoning_mode
  max_context_tokens
  usage_reporting
  request_id_reporting
  cancellation

AIModelRequestEnvelope
  protocol_version
  run_id / attempt_id
  model_config_snapshot
  messages_or_structured_input
  input_fingerprint
  deadline_utc

AIModelResponseEnvelope
  protocol_version
  provider_request_id
  raw_content
  finish_reason
  usage
  provider_metadata_allowlist
  output_fingerprint
```

Core 不依赖具体 SDK；FakeAIProvider 必须先于真实 adapter。Provider Host 无权访问 wilquant SQLite、Parquet、Gateway 或 Broker network endpoints。

首个真实 adapter 是通用 `OpenAICompatibleProvider`，由 `ProviderProfile` 描述 endpoint/model/capabilities；第一个真实验收对象优先使用 DeepSeek 官方或兼容 endpoint，但领域层禁止出现 `if provider == "deepseek"`。Claude 原生 Messages API 等非兼容协议以后增加独立 adapter，不改变 `AIProvider` domain contract。

### 18.2 AI secret

- 首选 Windows Credential Manager；
- DPAPI 加密文件仅作经过测试的 fallback；
- secret namespace 使用 `wilquant/ai/<provider>/<profile>`；
- Broker secret namespace 永远分离，不能复用 store、credential name 或进程；
- Core/Frontend/SQLite 只保存不敏感 `secret_ref` 和 `configured=true/false`；
- 不回显、不记录、不进入 Prompt、artifact、exception、trace 或 support bundle；
- Provider Host 启动时按 Windows 用户身份读取，内存中短时使用，错误信息脱敏；
- secret rotation 不修改历史 model config fingerprint，历史只记录 profile version。

### 18.3 Provider Host transport

AI-3 使用只绑定 `127.0.0.1` 的 HTTP/JSON 独立 AI Provider Host。可复用未来抽象出的 localhost authenticated transport 工具与思想，但不复用 ExecutionGateway process、port、bearer token、Broker credential namespace、crash state 或 kill state；Gateway 与 Provider Host 互相不得调用。

协议必须包含独立随机短期 secret、protocol version、request ID、timestamp 与 replay protection；secret 不进入日志、命令行或 audit。未来可替换 transport 而不改变 AI domain contract。当前不采用 Windows named pipe。

### 18.4 Raw response、reasoning 与删除语义

永久且不可变地保存 normalized accepted output、parsed structured output、validation、EvidenceRef、Prompt/model fingerprints、provider metadata、usage、finish reason 和 raw artifact hash。Raw provider content 默认保存为独立 artifact，不塞入普通业务表；用户显式删除内容时保留 run/hash/provenance，并追加 `RAW_ARTIFACT_DELETED` tombstone。

`reasoning_content` 默认 `NOT_RETAINED`。只有用户显式启用 `debug_reasoning_retention` 才能单独保存，且必须与普通 response 分离、经 secret/redaction pipeline、默认 UI 隐藏、默认 export 排除。AI-1 没有 provider call，因此只冻结 hash/provenance 字段，不创建 raw artifact 或 tombstone service。

### 18.5 AI research cost budget

预算同时支持 soft warning 与 hard limit，至少分为 per-run、per-provider-profile、daily/monthly research budget。80% 产生 warning；100% 必须在 provider call 前以 `AI_BUDGET_EXCEEDED` hard stop。Retry token/cost 计入同一 run，不得自动切换更昂贵模型、静默突破或用 reasoning retry 绕过预算。

预算只约束 AI research，不影响 Backtest、PAPER、RiskEngine、LIVE safety 或 ExecutionGateway。AI-1 只实现 usage/cost provenance contract；真正 enforcement 在 AI-3 Provider Host 阶段落地。

## 19. 失败语义与隔离

| 失败 | AI run | Backtest/PAPER/LIVE |
|---|---|---|
| Provider Host down | `FAILED_PROVIDER_UNAVAILABLE` | 无变化 |
| timeout/rate limit | 有界 retry 后失败 | 无变化 |
| invalid output | validation failed | 无变化 |
| temporal leak/fact drift | `REJECTED_*` | 无变化 |
| database write failure | run transaction rollback/failed audit | PAPER/LIVE 事务不参与 |
| AI secret missing | provider profile unavailable | Broker secret/状态无变化 |
| AI budget hard limit | `AI_BUDGET_EXCEEDED`，provider call 前停止 | 无变化 |
| process crash/restart | incomplete attempt recovered as failed/abandoned | 不触发 Gateway recovery |

AI health 不能成为 `/health/ready` 对 Data/Backtest/PAPER/LIVE 的必需条件。应提供独立 optional component status；AI 不可用时，非 AI 研究功能继续工作。

## 20. Schema 状态

AI-1 migration `20260827_0014` 与 AI-2 线性后继 `20260830_0015` 已实现：

| 表/聚合 | 关键用途 | 可变性 | 状态 |
|---|---|---|---|
| `ai_model_config_versions` | provider/model 参数 provenance | immutable | AI-1 implemented |
| `ai_prompt_template_versions` | Prompt 与变量契约 | immutable | AI-1 implemented |
| `ai_research_cases` | 时间截断根输入 | immutable | AI-1 implemented |
| `ai_evidence_packs` | case 的证据集合与 fingerprint | append-only | AI-2 implemented |
| `ai_evidence_refs` | 可验证证据引用 | immutable | AI-1 minimal implemented |
| `ai_analysis_runs` | run 状态与 provenance | 状态受控，终态 immutable | AI-1 implemented |
| `ai_analysis_attempts` | 每次 provider call | 一次终态收敛后 immutable | AI-1 implemented |
| `ai_analysis_trace_events` | 分析事件 | append-only | AI-1 implemented |
| `ai_validation_results` | 六层校验、gate 与 retry consistency provenance | append-only | AI-2 implemented |
| `ai_research_case_documents` | canonical durable retrieval input | append-only | AI-2 implemented |
| `ai_research_case_fts` | 从 case documents 重建的 FTS5 索引 | derived/disposable | AI-2 implemented |
| `research_diagnoses` | Stage 1 accepted result | immutable | AI-4 planned |
| `research_recommendations` | Stage 2 accepted result | immutable | AI-4 planned |
| `ai_retrieval_snapshots` | 候选、文档 fingerprint 与业务级排名分解 | append-only | AI-2 implemented |
| `research_theses` | 稳定 identity/current projection | 受控 projection | AI-5 planned |
| `research_thesis_revisions` | thesis 内容 | append-only | AI-5 planned |
| `copilot_conversations` | 上下文 identity | 受控关闭 | AI-6 planned |
| `copilot_turns` | 用户/AI turn + provenance | append-only | AI-6 planned |
| `research_action_drafts` | allowlisted draft | 状态受控，payload immutable | AI-6 planned |
| `ai_usage_ledger` | token/cost usage | append-only | AI-1 implemented |

数据库 trigger/约束应禁止 accepted outputs、attempts、trace、evidence、revisions 和 usage 的 UPDATE/DELETE。现有可编辑/可删除 ResearchJournal 不能直接充当 AI 审计记忆；AI 内容应先进入 append-only draft/revision 体系。

## 21. API 草案

AI-1 已实现 Case/Run 创建及 Case/Run/Trace/Usage 查询；AI-2 已新增 EvidencePack、ValidationResult、RetrievalSnapshot 的只读查询。resolver、validation mutation、cancel、raw、conversation、draft 和 secret API 仍不开放。

```text
POST /api/v1/research-cases
GET  /api/v1/research-cases/{case_id}
GET  /api/v1/research-cases/{case_id}/evidence

POST /api/v1/ai-analysis-runs
GET  /api/v1/ai-analysis-runs/{run_id}
POST /api/v1/ai-analysis-runs/{run_id}/cancel
GET  /api/v1/ai-analysis-runs/{run_id}/trace
GET  /api/v1/ai-analysis-runs/{run_id}/raw

GET  /api/v1/research-theses/{thesis_id}
POST /api/v1/research-theses/{thesis_id}/revision-drafts
POST /api/v1/research-thesis-revision-drafts/{draft_id}/confirm

POST /api/v1/research-cases/{case_id}/conversations
POST /api/v1/copilot-conversations/{conversation_id}/turns

POST /api/v1/research-action-drafts/{draft_id}/confirm
POST /api/v1/research-action-drafts/{draft_id}/reject

GET  /api/v1/ai-provider-profiles
PUT  /api/v1/ai-provider-profiles/{profile_id}/secret
DELETE /api/v1/ai-provider-profiles/{profile_id}/secret
```

Secret API 只接受写入，不返回 secret。不存在任何 `/ai/.../execute-order`、`activate-live`、`authorize-capital`、`unfreeze` 或 Gateway proxy endpoint。

## 22. UI 概念

Research Copilot 作为现有 Research Workspace 的上下文面板/详情页，首版固定六个 tab：

| Tab | 内容 |
|---|---|
| Summary | 诊断、建议、FACT/INFERENCE/HYPOTHESIS、confidence 解释、gate 状态 |
| Evidence | EvidenceRef、source version、时间、完整性、stale/conflict |
| Decision Trace | stage、validator、gate、retry 和 draft 事件，不伪造隐藏思维 |
| Cases | 检索候选、相似度分解、当时结果、支持/反对案例 |
| Raw | 已脱敏 Prompt/response/DTO/hash/provider metadata |
| Conversation | 锚定当前 case/run 的追问与引用 |

草稿动作必须显示：动作类型、将创建的研究对象、冻结 input hash、差异预览和“需要用户确认”。AI 页面不出现 LIVE 激活、资本增加、解冻、kill reset 或真实下单按钮。

Raw/Debug 为高级模式，默认显示 model/provider、Prompt fingerprint、response status、parsed output、validation、token usage、latency、retrieved cases 与 error category。Raw response 需要高级展开；reasoning 需要再次显式展开，并显示“模型内部推理文本不属于确定性证据”。所有内容必须脱敏，不使用 `dangerouslySetInnerHTML`，默认不进入 export、不默认复制到 clipboard，credential/auth header 永不展示。

## 23. Prompt injection 与内容安全

- Dataset、journal、case、外部文本全部视为不可信 data，不视为 system instruction；
- Evidence serialization 使用结构化边界和长度限制；
- 模型不能选择工具名或 endpoint；
- URL 不自动访问，文件路径不自动读取；
- 输出 HTML/Markdown 在 UI 严格转义/清洗；
- raw payload 下载前脱敏并显示敏感性提示；
- action payload 重新由 Core DTO 构造，不复用模型任意 JSON；
- PromptTemplateVersion 发布需 reviewer 与 fingerprint；
- provider metadata 采用 allowlist，header/request body 不原样落盘。

## 24. 测试策略

### 24.1 确定性单元/属性测试

- canonical fingerprint 与字段顺序无关；
- EvidenceRef integrity、locator 和 cutoff；
- CN/US timezone、DST、market-local trade date；
- 六层 validator 的正反例；
- immutable fact drift 和 unauthorized action 永不 retry；
- confidence/stance 不进入 capital/risk DTO；
- hybrid retrieval hard filter 先于 similarity；
- thesis revision append-only state transitions。

### 24.2 Contract/integration

- FakeAIProvider 正常、截断、缺字段、幻觉引用、future data、timeout、429、5xx；
- Provider Host protocol version/auth/timeout/cancel/restart；
- secret 写入、读取权限、轮换、日志脱敏、Broker namespace separation；
- migration trigger 阻止 immutable row UPDATE/DELETE；
- Core 重启恢复 incomplete runs，不重放已完成 attempt；
- AI optional health 失败时 Backtest/PAPER APIs 仍通过。

### 24.3 Adversarial/eval

- evidence 中含“忽略系统规则/下单/泄露 key”；
- 用户要求提高资本、激活 LIVE、解除 kill 或直接下单；
- 伪造 EvidenceRef、symbol 混市场、货币错配；
- historical case 注入未来 earnings/bar；
- retry 时偷改 instrument/rules/cutoff/metric；
- confidence 伪装为胜率；
- retrieval 中近似但不可比案例；
- CN/US 同 symbol 与 DST 边界。

模型质量 eval 评估 grounding coverage、abstention、引用准确率、事实漂移率和建议可操作性；不把固定自然语言 golden string 当正确性来源。

## 25. AI 与 LIVE 双轨路线

```text
AI TRACK                              LIVE / MULTI-MARKET TRACK
AI-1 Provenance Foundation            6B Multi-Market Foundation
AI-2 Evidence + Temporal Cases         6C Capital + LIVE State
AI-3 Provider Host + Fake Provider     6D Gateway + Fake Broker
AI-4 Two Stage + Validation            6E First US Broker Adapter
AI-5 Thesis + Case Memory               6F LIVE UI
AI-6 Context Copilot + Drafts           6G LIVE Acceptance
AI-7 Research Copilot UI
AI-8 AI Acceptance / Security / Evals
```

两条轨道可以并行开发，但只有通过稳定、只读、版本化 DTO 交汇：

- AI-1 可在 6B 前开始；
- US AI case 必须等待 6B 的 US Instrument/Calendar/MarketRules/Data contracts；
- AI 不阻塞 6B–6G；
- 6C–6G 不要求 AI 可用；
- 任何 AI 阶段都不批准 Automated LIVE；
- AI 建议永远不能成为 ExecutionApproval 或 CapitalAuthorization 输入。

## 26. 实施阶段与验收

### AI-1 Provenance Foundation

状态：implemented。已完成版本化 Prompt/Model config、ResearchCase identity、最小 EvidenceRef registry、AIAnalysisRun/AIAnalysisAttempt/Trace/Usage、canonical fingerprint、append-only persistence 与安全 API；不调用模型。

### AI-2 Evidence & Temporal Foundation

状态：stable。已实现显式 Resolver allowlist、EvidencePack、双 cutoff、structured claims、六层 deterministic validators、ResearchGate、SQLite FTS retrieval、RetrievalSnapshot、CN/US isolation、append-only validation provenance、restart recovery 与 adversarial tests，并通过完整 `scripts/test.ps1`；FTS 只是可重建 derived index。本阶段仍无 Provider。

### AI-3 Provider Isolation

AIProvider contract、独立 Provider Host、127.0.0.1 authenticated HTTP/JSON、Windows Credential Manager/DPAPI fallback、Fake provider fault injection、通用 OpenAI-compatible adapter、usage budget enforcement 与首个真实 endpoint 验收；仍不实现业务 recommendation。

### AI-4 Two-Stage Analysis

ResearchDiagnosis、ResearchRecommendation、retry orchestration 与 fake-model acceptance；直接复用 AI-2 已验收的六层 validators 和 ResearchGate，不重造事实边界。

### AI-5 Research Memory

ResearchThesis revisions、incremental case chain、delta summary、后续 memory evolution 与 temporal-safe case UI API；基础 hard-filter + structured score + FTS retrieval 已在 AI-2 完成。

### AI-6 Context Copilot & Drafts

Conversation provenance、grounded citations、allowlisted ResearchActionDraft、user confirmation、TradeThesis WHY boundary。

### AI-7 UI

Summary/Evidence/Decision Trace/Cases/Raw/Conversation、status/error/stale/abstain UX、draft diff confirmation、secret configured status。

### AI-8 Final Acceptance

provider outage、prompt injection、temporal leakage、fact drift、secret leakage、process crash、CN/US/DST、non-interference with PAPER/LIVE 和完整质量门禁。

## 27. 优先级

### P0：先建立可信事实基础

- trust boundary 与 compile/import dependency guard；
- ResearchCase、EvidenceRef、cutoff、fingerprints；
- append-only provenance、Attempt/Trace/Usage；
- EvidencePack、deterministic validators、ResearchGate 与 retrieval snapshot；
- AI secret 与 Broker secret 物理/命名空间隔离。

### P1：再增加模型能力

- Provider Host；
- FakeAIProvider、two-stage diagnosis/recommendation；
- failure isolation 与 bounded retry。

### P2：最后增加体验与记忆

- hybrid cases；
- thesis/incremental；
- contextual Copilot；
- drafts 和六 tab UI；
- eval dashboard/cost views。

### DO LATER

- embedding ranker 与跨市场弱参考；
- realtime research provider；
- PAPER read-only thesis association；
- 经过校准的概率模型与 reliability dashboard；
- raw artifact retention/archival automation。

### DO NOT BUILD

- autonomous order/capital/risk agent；
- AI→ExecutionGateway/BrokerAdapter 通道；
- aggressive mode 提升资金权限；
- 未校准 LLM win rate；
- 允许任意 tool/SQL/Python 的 Copilot；
- 用 case memory 覆盖 deterministic facts。

## 28. DO NOT BORROW

从 PA_Agent 明确禁止复制或近似移植：

- 任何源代码、函数体、class 结构或测试 fixture；
- 大段 system/user Prompt、语言规则、角色设定；
- `prompt_engineering` 中策略文本、检查单和知识库；
- 二元决策树文本、节点编号、路径、trace schema 和可视化资产；
- JSON 输出字段集合、错误 category 字母、retry feedback 文案；
- experience 目录结构、文件名、success/failure JSON schema；
- GUI 布局、样式、动画、图标和截图；
- trade logger CSV 字段、图表实现和机会判断；
- provider compatibility/client 实现；
- secret storage 实现或其安全声明。
- AI 直接生成实际 Broker execution 事实；
- AI confidence/estimated win rate 直接进入 RiskEngine 或资金管理；
- aggressive mode 扩大 capital/order notional；
- file-folder experience 作为 production memory/source of truth；
- huge orchestrator monolith；
- PyQt 架构迁移到当前 React/FastAPI 系统；
- AI 输出覆盖确定性系统事实；
- AI 获得任何 LIVE 权限。

独立实现必须从 wilquant 既有领域语言、本文契约和自行编写的 tests 出发。若未来开发者直接阅读 PA_Agent 源码后实现同一组件，应保留 clean-room 设计记录并由未接触原实现的 reviewer 检查相似性。

## 29. PA_Agent License Considerations

- PA_Agent 采用 `AGPL-3.0-or-later`；
- 本次只研究公开架构思想、行为与 UX 分类；
- wilquant 后续代码、tests、Prompt、schema、decision trace 和 UI 必须独立开发；
- 不把 PA_Agent 源码、Prompt、决策树、经验文件或资产放入 wilquant；
- 若未来确实希望引用其任何代码或实质性文本，必须立即暂停实现并进行单独 license review，不能沿用本 ADR 的“概念研究”结论。

## 30. 二十个关键问题的明确答案

1. **最值得借什么？** 两阶段分工、gate、结构化校验/重试、完整 provenance、增量 continuity、案例和分析后追问的架构模式。
2. **什么不该借？** 代码/Prompt/决策树/GUI/文件 schema，以及 monolith、symbol identity、目录 memory 和交易机会语义。
3. **AI 权力边界？** 只分析、解释、建议和创建研究草稿；没有资金、风险或执行权。
4. **如何访问事实？** Core 按 ResearchCase/cutoff 生成 EvidencePack；模型只收到 EvidenceRef 和 bounded content。
5. **如何防编造指标？** Grounding validator 将 claim 与 metric locator/source hash 对照，不一致即拒绝。
6. **如何防未来泄漏？** `known_at/effective_at/case_end_at <= as_of` hard filter 在相似度前执行。
7. **输出如何验证？** Syntax→Schema→Semantic→Grounding→Temporal→Immutable facts。
8. **retry 哪些字段不能改？** case、instrument、market/currency、cutoff、所有 version/fingerprint、deterministic metrics/rules/risk/fill/equity facts。
9. **Experience 如何升级？** 变成只引用源事实的 ResearchCase + retrieval snapshot，不使用目录 JSON 作为事实库。
10. **如何持续 thesis？** 新 case/new run 链接 parent，输出 change set 和 revision，旧 revision 永不改写。
11. **如何连接 Experiment？** 读取 experiment/comparison/diagnostics，建议 `ExperimentDraft`，用户确认后调用既有 service。
12. **Recommendation 何时能变 OrderIntent？** AI 自己永远不能转换；未来只有用户在独立受控 UI 明确接受后，才能由非 AI application service 创建新 Intent。
13. **谁负责转换？** USER 是授权 actor；Core 的确定性 command handler 执行，仍需 Risk/Capital/User Approval 链。
14. **AI 能影响 Risk/Capital 吗？** 不能，confidence/stance/thesis 也不能成为计算输入。
15. **如何避免跨市场混淆？** stable instrument identity、MarketRulesVersion、market/timezone/currency/asset/session facts 和默认 cross-market 禁止。
16. **如何保存 provenance？** Case/Evidence/Prompt/Model/Retrieval/Input/Output/Validator fingerprints + attempts/trace/usage/raw artifact。
17. **换模型后如何复现？** 历史 run 冻结 ModelConfigVersion/PromptTemplateVersion 和输入证据；可复核当时输入与结果，但第三方模型本身不承诺字节级重放。
18. **provider 失败影响 PAPER/LIVE 吗？** 不影响；AI optional health 与事务、Gateway readiness 分离。
19. **AI secret 在哪里？** Windows Credential Manager 优先，DPAPI fallback；Provider Host 独享，与 Broker secret 分 namespace/进程。
20. **第一轮实现？** AI-1 Provenance Foundation：先做最小 EvidenceRef、版本、指纹、run/attempt/trace/usage 和 append-only，不接模型。

## 31. 已确认后续设计决定

此前八个开放问题已一次性关闭：首个真实实现采用通用 OpenAI-compatible adapter；AI Host 使用独立 127.0.0.1 authenticated HTTP/JSON；Raw 使用独立 artifact + 可删除内容/保留 tombstone，reasoning 默认不保留；AI-2 使用 hard filters + structured score + SQLite FTS；realtime provider 等待 6B，先冻结 freshness contract；Journal/Thesis 分离；预算同时 soft warning + hard limit；Raw/Reasoning 分层显式展开与脱敏。

AI-1 现在可独立于 6B 开始；AI-1/AI-2/AI-3 基础设施与 Phase 6 并行，US-specific realtime diagnosis、US MarketRules evidence、US session-aware analysis 与 US cross-market cases 等待 6B。首批真实能力仍只定位为 `RESEARCH COPILOT`，输出只允许 `ResearchRecommendation / ExperimentDraft / JournalDraft / ThesisRevisionDraft`，永不新增或修改执行授权对象。

## 32. 完成边界

AI-1 Provenance Foundation 已稳定。AI-2 已按授权实现 EvidencePack、grounding/temporal/immutable validation、ResearchGate、hard filters + structured score + SQLite FTS retrieval 与不可变 snapshots，并完成五类合同核对及最终完整门禁（后端 734 / AI 206，前端 48，退出码 0）。详细证据见 `docs/ai-2-contract-closure-acceptance.md`。未调用 provider、未安装 LLM SDK、未做 chat/UI/recommendation execution，不进入 AI-3。

预期状态：

```text
AI RESEARCH COPILOT ARCHITECTURE DESIGNED
AI-1 PROVENANCE FOUNDATION STABLE
AI-2 EVIDENCE & TEMPORAL VALIDATION STABLE
STOP BEFORE AI-3
```
