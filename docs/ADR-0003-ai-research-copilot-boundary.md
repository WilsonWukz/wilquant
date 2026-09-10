# ADR-0003：AI Research Copilot 信任与推理边界

- 状态：已批准；AI-1/AI-2 已验收，AI-3 已通过最终完整验收（详见 docs/ai-3-provider-acceptance.md）
- 日期：2026-08-27
- 决策范围：研究 AI 的证据、推理、权限、provider 隔离、记忆与动作边界
- 前置决策：ADR-0002 ExecutionGateway 与 Multi-Market 执行边界

## 背景

wilquant 已具备不可变行情与策略版本、回测、实验比较、诊断、研究报告、PAPER 确定性执行，以及 Phase 6A 设计的多市场与真实资金安全边界。最初制定本 ADR 时尚无 Provider runtime；2026-09-10 用户另行批准 AI-3 隔离实现，不授权 Copilot 或交易写入。

PA_Agent 展示了两阶段诊断/决策、校验重试、分析记录、增量分析、经验案例和分析后追问等有价值的产品模式。但它使用 AGPL-3.0-or-later，并且其领域语言、Prompt、决策树、文件记录和单机 GUI 结构不适合作为 wilquant 的实现基础。

本 ADR 只借鉴公开可观察的架构思想。具体实现必须 clean-room 独立完成：

> Inspired by architectural patterns observed in PA_Agent; implementation must be independent.

## 决策

采用“Core 控制面 + 隔离 AI Provider Host”的 evidence-first Research Copilot：

```text
wilquant Core
  ResearchCase / temporal cutoff
  EvidencePack / EvidenceRef
  Prompt + model config versions
  AIAnalysisRun / AIAnalysisAttempt / Trace / Usage
  deterministic validators + ResearchGate
  thesis / cases / conversation / drafts
             |
       versioned authenticated envelope
             v
isolated AI Provider Host
  provider SDK
  AI credential
  timeout/cancel/usage capture
  no database, no Broker, no Gateway
```

### 决策一：AI 是不可信建议者

AI 只能：

- 分析冻结的 ResearchCase/EvidencePack；
- 生成 ResearchDiagnosis；
- 在 deterministic ResearchGate 放行后生成 ResearchRecommendation；
- 参与锚定 case/run/thesis 的研究对话；
- 建议 allowlisted research drafts。

AI 永远不能：

- 创建 BrokerOrder、BrokerFill、PaperOrder 或 PaperFill；
- 创建或批准 ExecutionRequest/ExecutionApproval；
- 绕过或修改 RiskPolicy；
- 创建、增加或修改 CapitalAuthorization；
- 解冻、解除 kill、激活 LIVE；
- 读取 Broker credential；
- 直接调用 ExecutionGateway/BrokerAdapter；
- 以 confidence/stance/TradeThesis 改变资金或数量。

Strategy 与 AI 均不是资本授权 actor。用户在 conversation 中发出越权指令也不扩大 AI 权限。

### 决策二：Core 冻结事实，模型不取数

模型不能直接访问 Dataset、DuckDB、市场数据 provider、ResearchRepository、PaperRepository 或互联网。Core 先建立不可变 ResearchCase，再按 `as_of_utc` 和 market-local trade date 生成 EvidencePack。

每个 EvidenceRef 必须绑定 source entity/version、hash、locator、effective/known/captured time、instrument/market 和完整性状态。模型声明的 FACT 必须引用 pack 中存在且支持该陈述的 EvidenceRef。

历史与实时研究数据使用不同 provider port。实时数据也必须冻结 snapshot；两阶段之间不静默刷新。刷新意味着新 ResearchCase。

### 决策三：两阶段由 deterministic gate 分隔

```text
Stage 1 ResearchDiagnosis
 -> syntax/schema/semantic/grounding/temporal/immutable validation
 -> deterministic ResearchGate
 -> Stage 2 ResearchRecommendation only when PROCEED
```

Gate 结果为 `PROCEED`、`WAIT_FOR_EVIDENCE`、`ABSTAIN` 或 `REJECT`。模型无权自我放行。

Recommendation 中 stance/confidence 只描述研究判断。confidence 是 ordinal support，不是经过校准的概率、胜率或风险预算。

### 决策四：六层校验和有界重试

校验顺序固定为：syntax、schema、semantic、grounding、temporal、immutable facts。

- provider transient、syntax 和 schema 可在同一 input fingerprint 下有界重试；
- semantic 只允许严格受限的一次修复；
- grounding 默认不自动重试；
- temporal leak、immutable fact drift 和 unauthorized action 永不重试当前 run；
- 每次调用追加 AIAnalysisAttempt，绝不覆盖原响应；
- retry 不能改变 ResearchCase、EvidencePack、PromptTemplateVersion 或 ModelConfigVersion。

### 决策五：全链 provenance 与 append-only

每个 run 冻结并记录：

```text
ResearchCase fingerprint
EvidencePack fingerprint
retrieval snapshot fingerprint
PromptTemplateVersion + resolved prompt fingerprint
AIModelConfigVersion fingerprint
validator policy fingerprint
provider request/response fingerprints
normalized output fingerprint
attempt usage/latency/finish reason
append-only AnalysisTrace
```

accepted diagnosis/recommendation、attempt、trace、evidence、thesis revision、conversation turn 和 usage 必须 append-only。现有可编辑 ResearchJournal 不作为 AI 审计事实来源。

### 决策六：推理进程、transport 与密钥隔离

真实 provider SDK 仅装载在独立 AI Provider Host。Host：

- 接收一次冻结的 provider-neutral request envelope；
- 不直接访问 SQLite、Parquet 或文件系统证据；
- 不持有 Broker/Gateway client；
- 使用独立认证 secret/protocol；
- 不与 ExecutionGateway 共享进程、token、credential name 或 secret store namespace；
- 崩溃只使 AI run 失败。

AI secret 首选 Windows Credential Manager，DPAPI 文件仅作经测试 fallback。Core/Frontend/SQLite 只保存 `secret_ref` 和 configured 状态，不保存明文。

AI-3 的首个真实 adapter 为通用 `OpenAICompatibleProvider`，第一个真实验收 endpoint 优先使用 DeepSeek 官方/兼容接口，但领域层不出现厂商条件分支。Provider Host 使用独立的 127.0.0.1 HTTP/JSON、随机短期 secret、protocol version、request ID、timestamp/replay protection；绝不复用 Gateway process、port、bearer token、credential namespace 或 crash/kill state。当前不采用 Windows named pipe。

### 决策七：仅允许研究草稿

模型只能建议以下动作描述：

```text
CREATE_EXPERIMENT_DRAFT
CREATE_BACKTEST_DRAFT
COMPARE_RUNS_DRAFT
APPEND_THESIS_REVISION_DRAFT
ADD_RESEARCH_JOURNAL_DRAFT
REFRESH_RESEARCH_CASE_DRAFT
REVIEW_RESEARCH_JOURNAL
REVIEW_BACKTEST_RESULT
REVIEW_PAPER_SESSION
WAIT_FOR_USER_CONFIRMATION
```

Core 将描述重新构造成严格 DTO。草稿必须经 USER 显式确认后才能调用既有研究 service。不存在 arbitrary tool call 或 Paper/LIVE draft。

### 决策八：上下文 Copilot 与研究记忆

Copilot conversation 必须锚定 ResearchCase、AIAnalysisRun、Experiment、BacktestRun 或 ResearchThesisRevision，不提供无上下文通用聊天。

案例检索先执行 temporal/market/instrument/rules hard filter，再进行 structured + lexical + optional embedding hybrid ranking，并保存完整候选与分数 provenance。

ResearchThesis 使用稳定 identity 与 append-only revision。TradeThesis 只解释 WHY；它不是 Intent、RiskDecision、CapitalAuthorization 或 Approval。

ResearchJournal 与 ResearchThesis 保持分离：AI 只能生成 JournalDraft/ThesisRevisionDraft，用户确认后追加，不能改写历史内容。

### 决策九：Raw、retrieval、freshness 与 budget

- Raw content 是独立 artifact，可由用户删除内容但必须保留 hash/provenance 并追加 tombstone；reasoning 默认不保留；
- AI-2 retrieval 固定先 hard filters，再 structured score + SQLite FTS，不做 embedding；
- realtime research 等待 6B，先定义 `IMMUTABLE_HISTORICAL/EOD/DELAYED/REALTIME` freshness class；
- AI budget 同时有 soft warning 与 hard limit，AI-1 只记录 usage/cost provenance，AI-3 才执行 provider-call 前 hard stop；
- Raw UI 默认不显示 reasoning，Raw 和 reasoning 分两次显式展开并始终脱敏。

### 决策十：AI 与 LIVE 双轨

AI-1～AI-8 与 Phase 6B～6G 是独立路线。AI 可以消费稳定的 multi-market read-only contracts，但：

- AI 不阻塞 Phase 6；
- Phase 6 不要求 AI 可用；
- US AI evidence 必须等待 6B 的 US data/calendar/rules foundation；
- 任何 AI phase 都不批准 Automated LIVE；
- AI health 不成为 Data/Backtest/PAPER/LIVE readiness 的必要条件。

## 备选方案

### 现有 ResearchPage 增加通用聊天框

实现简单，但无法提供时间截断、证据引用、结构化校验、运行 provenance 和动作边界，否决。

### 外部自主 Agent 直接调用 FastAPI

工具权限过宽，难以证明不触达 PAPER/LIVE，也会把 provider 行为变成业务副作用，否决。

### LLM SDK 与 FastAPI Core 同进程

会让 provider SDK、网络阻塞、secret 和崩溃进入 Core failure domain，不满足 AI 故障不影响 PAPER/LIVE，否决为真实 provider 的最终形态。Fake provider 可在测试中进程内运行。

### AI 与 ExecutionGateway 共用进程或 IPC credential

会把推理与真实执行权限合并，破坏最小权限和 credential isolation，永久否决。

### 复制 PA_Agent 两阶段实现

许可证、领域耦合和 clean-room 要求均不允许。只采用独立抽象后的模式，否决复制。

## 后果

### 正面

- AI 输出可定位到当时可知的数据、Prompt、模型、校验和每次尝试；
- temporal leakage、伪造证据和事实漂移可 fail closed；
- provider 崩溃、缺 key 或输出异常不影响非 AI 业务；
- 与 Phase 6A 的资本、Gateway、UNKNOWN、reconciliation 和 credential 边界兼容；
- CN/US 共享同一 ResearchCase/Evidence/Recommendation 语言；
- 研究建议可以转为受控草稿，而不是隐式副作用。

### 代价

- 必须先建设 provenance/evidence，再得到可见的聊天与建议能力；
- 独立 Provider Host、版本化 Prompt、append-only 数据和六层校验增加实现量；
- 模型“回答成功”不等于 run 成功，严格 gate 会产生更多 abstain/reject；
- raw response、retention 和本地隐私需要独立政策；
- embedding、realtime data 和 provider adapter 必须分阶段引入。

## 实施顺序

```text
AI-1 Provenance Foundation
AI-2 Evidence + Temporal Cases
AI-3 Provider Host + Fake/First Provider
AI-4 Two Stage Diagnosis + Recommendation
AI-5 Thesis + Incremental Case Memory
AI-6 Context Copilot + Confirmed Drafts
AI-7 Research Copilot UI
AI-8 Final AI Acceptance
```

AI-2 将六层 deterministic validation、ResearchGate 与 `hard filters -> structured score -> SQLite FTS -> deterministic rank` 提前到 Provider 之前完成。`ResearchCaseDocument` 是 durable retrieval input，FTS 是可重建 derived index，`RetrievalSnapshot` 是 durable result；FTS rowid 或内部 bm25 状态不构成 provenance。

实施状态：AI-2 已于 2026-08-31 完成首轮实施，并于 2026-09-09 完成 evidence、concrete resolver、claim/schema 与 freshness 合同收口。最终完整门禁退出码 0：后端 734 项（AI 206 项）、前端 10 文件 / 48 项、Ruff、mypy、TypeScript/Vite 均通过。状态为 `AI-2 EVIDENCE & TEMPORAL VALIDATION STABLE`。详细合同与测试证据见 `docs/ai-2-contract-closure-acceptance.md`。停止在 AI-3 之前，本 ADR 不因此授权任何 Provider、模型调用、AI UI 或交易写操作。

## 本 ADR 不授权

- AI-3 授权限定为独立 Host/协议、Core 调用审计/预算、最小 0016、受限 secret store 和测试；不授权 AI-4；
- 真实 Provider smoke 仅用户显式人工确认后执行，不在自动门禁调用外网；
- 不授权读取 PA_Agent 源码进入 wilquant；
- 不授权任何 PAPER/LIVE/Broker 行为；
- 完成 AI-3 后停止，不自动进入 AI-4；
- 不授权用 AI confidence、stance 或 thesis 影响资本、风控或执行。

## AI-3 固定实施语义（2026-09-10）

共享 `ai_provider_protocol` 只依赖 stdlib/Pydantic；Core 和 Host 单向依赖它，Host 不导入既有 ORM contracts。共同协议族不等于行为完全一致，wire 参数、usage/reasoning 映射由冻结 capability 决定，不按厂商名称猜测。

复用 STARTED 与三个互斥终态：COMPLETED、FAILED、ABANDONED。未知结果采用 ABANDONED / PROVIDER_RESULT_UNKNOWN，不引入 UNKNOWN/DISPATCHING。0016 允许 token NULL，并新增以既有 attempt_id 为主键的不可变调用绑定，不新增 ProviderRun/ProfileVersion。发送前在事务内固定 request/config/prompt/evidence/gate 指纹及预算预留；未知结果保留保守预算，不自动 retry。

Windows token 私有 ACL 从创建时生效并读回验证；Credential Manager 不可用 fail closed，无明文或 DPAPI fallback。raw 独立有界脱敏，reasoning 默认移除；不产生 accepted output。详情见 AI-3 design 与 `docs/ai-3-provider-operations.md`。
