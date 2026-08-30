# AI-2 Evidence, Grounding & Temporal Validation Design

**状态：** approved for implementation（2026-08-30）  
**基线：** `dev@6cb0b25e61d70afd369172b46209462feace8860`  
**前置能力：** AI-1 Provenance Foundation，Alembic `20260827_0014`  
**范围终点：** AI-2 完成后停止，不进入 AI-3 Provider Isolation

## 1. 目标与边界

AI-2 在不调用模型的前提下建立确定性研究事实边界：

```text
Domain facts
    -> explicit EvidenceResolver
    -> CanonicalEvidenceItem
    -> immutable EvidencePack
    -> deterministic ResearchGate
    -> structured candidate payload
    -> Syntax / Schema / Semantic / Grounding / Temporal / Immutable Fact
    -> ACCEPT / REJECT
```

本阶段实现显式 resolver、typed evidence、EvidencePack、双时间校验、structured claims、六层 validation、ResearchGate、SQLite FTS5 retrieval、RetrievalSnapshot、restart recovery、CN/US 隔离和 authority escalation 拒绝。

本阶段明确不实现 Provider、LLM SDK、Provider Host、真实模型调用、chat、AI UI、embedding、跨市场检索、任意 resolver API、PAPER/LIVE 写操作，以及 Phase 6B 的正式 MarketRulesVersion resolver 或 US realtime/session-aware evidence。

## 2. 核心架构决策

采用紧凑 provenance + 显式 Resolver 方案。新增四张普通历史表与一个 derived FTS virtual table：

```text
ai_evidence_packs
ai_validation_results
ai_research_case_documents
ai_retrieval_snapshots

ai_research_case_fts       # derived/disposable index
```

EvidencePack 使用 canonical `items_json`，不建立独立 pack-item 表。Pack 在单事务中一次写入，任何解析、校验或大小检查失败都不能留下半包。

### 2.1 FTS 不是历史事实

```text
ResearchCaseDocument = durable retrieval input
FTS                  = disposable derived index
RetrievalSnapshot    = durable retrieval result
```

- `ai_research_case_documents` 保存受控、可审计、不可变的检索文档和 document fingerprint；
- `ai_research_case_fts` 只保存可重建索引，不是 provenance 或 source of truth；
- RetrievalSnapshot 保存 ResearchCase/document identities、fingerprints、业务级 normalized score 和最终排序；
- snapshot 不保存或依赖 FTS rowid，SQLite 内部 `bm25` 状态不成为历史事实；
- FTS rebuild 从 canonical ResearchCaseDocument 重建；
- lexical score 按 RetrievalPolicy 量化为固定整数 bucket，再与结构分合成业务分；
- 同分使用 `score DESC -> case_end_at DESC -> case_id ASC`；
- 相同 policy、query 和 document corpus 在 rebuild 前后产生相同业务排序；
- 已冻结 RetrievalSnapshot 永远不因 FTS rebuild 或新增 case 改变。

### 2.2 ResearchCase 双时间事实

AI-1 现有字段直接承担稳定语义：

```text
ResearchCase.created_at = known_at
ResearchCase.as_of_utc  = case_end_at
```

`created_at` 必须由 server 生成、不可变、API 不接受客户端输入，也不允许历史导入回填。2026 年创建但描述 2023 市场的 case，其 `case_end_at` 可以是 2023，`known_at` 仍是 2026，不能进入 2024 historical knowledge context。

未来外部历史研究导入必须新增 `source_known_at / ingested_at` 设计，不能修改 `created_at` 绕过 cutoff。

### 2.3 MarketRules 按分析需要校验

`market_rules_version` 在 AI-2 contract 中允许为 `null`。`AnalysisRequirements` 保存 `requires_market_rules` 和受控 `required_rule_topics[]`。

不依赖交易规则的研究可以在 MarketRulesVersion 缺失时正常 `PROCEED`。涉及 T+1、same-day sell、lot size、price limit、fractional quantity、trading session、settlement 或 sellability 时，缺失规则返回 `WAIT_FOR_EVIDENCE / MISSING_MARKET_RULES`。模型不能补写规则。

## 3. 模块边界

AI-2 在 `quant_lab.ai` 内按职责拆分：

```text
contracts.py          enums、TemporalContext、EvidenceContext、claim/finding/gate DTO
resolvers.py          EvidenceResolver protocol、registry、CanonicalEvidenceItem
source_resolvers.py   现有领域对象的显式 resolver
packs.py              pack assembly、size/security checks、fingerprint
validation.py         六层 pipeline、grounding、temporal、immutable facts
gates.py              deterministic ResearchGate
retrieval.py          documents、hard filters、structured score、FTS rank
persistence.py        AI-1 + AI-2 ORM models
repository.py         AI-1 + AI-2 persistence boundary
```

Provider Host 未来只能接收序列化后的 EvidencePack；不得持有 SQLAlchemy session、数据库路径、ResearchRepository、PaperRepository、DuckDB 或 artifact filesystem 权限。

## 4. Evidence contracts

### 4.1 TemporalContext

```text
market_data_cutoff: aware UTC datetime
knowledge_cutoff: aware UTC datetime
market: CN_A_SHARE | US_EQUITY
timezone: IANA timezone
asset_type: EQUITY | ETF
analysis_mode: CURRENT_RESEARCH | HISTORICAL_REPLAY
```

所有时间必须 timezone-aware，并在 canonical payload 中归一化为 UTC。market-local trade date 仍保留为 date，不伪装成 UTC timestamp。

### 4.2 EvidenceContext

```text
market
exchange?
instrument_id
currency?
asset_type
timezone
market_rules_version?
```

Resolver 不允许从 symbol 推断 market、exchange、currency 或 instrument identity。

### 4.3 CanonicalEvidenceItem

每个 item 至少包含：

```text
ref_id
source_type
source_id
field_path
semantic_type
classification             # FACT / USER_NOTE / DERIVED_METRIC / SYSTEM_STATE
source_fingerprint
canonical_value
value_fingerprint
observed_at?
effective_at?
known_at?
market_timestamp?
freshness_class?           # IMMUTABLE_HISTORICAL / EOD / DELAYED / REALTIME
known_delay_seconds?
context
resolver_policy_version
```

`AI_INFERENCE` 不是 evidence classification。AI 输出不能成为自身或其他 run 的 Evidence source。`ref_id` 由 source identity、field path、fingerprints 和 temporal metadata 派生，调用方不能指定。

### 4.4 field_path allowlist

每个 Resolver 公开固定 allowlist，并用显式映射函数取值。禁止 dynamic table/column、SQL、Python expression、JSONPath、`../` 和任意 nested reflection。非法字段返回 `EVIDENCE_FIELD_NOT_ALLOWED`；非法来源返回 `EVIDENCE_SOURCE_UNSUPPORTED`。

## 5. Resolver registry 与来源范围

`EvidenceResolverRegistry` 只接受显式注册的 `EvidenceResolver`。Resolver 输入为 source id、requested fields、TemporalContext 和 EvidenceContext，输出纯 CanonicalEvidenceItem，不返回 ORM。

### 5.1 SUPPORTED

| Source | 稳定 identity/fingerprint | effective_at | known_at | 主要 classification |
|---|---|---|---|---|
| `DATASET_VERSION` | publication fingerprint | `max_timestamp` | `published_at` | counts、time range、quality、schema；FACT |
| `MARKET_DATA_SNAPSHOT` | snapshot fingerprint | dataset `max_timestamp` | max(profile updated、dataset/calendar published) | versions/fingerprints/quality；FACT/SYSTEM_STATE |
| `STRATEGY_VERSION` | strategy fingerprint | `created_at` | `created_at` | type/version/fingerprint/spec；FACT/USER_NOTE |
| `BACKTEST_RUN` | run input + artifact hashes | dataset max timestamp | `completed_at` | status/config identity/metrics；FACT/DERIVED_METRIC |
| `RESEARCH_EXPERIMENT` | canonical current snapshot | latest linked cutoff或 updated time | `updated_at` | status/tags 为 SYSTEM_STATE，hypothesis 为 USER_NOTE |
| `RESEARCH_COMPARISON` | inputs + resolver policy | max linked cutoff | max linked run/experiment known time | comparability/deltas；DERIVED_METRIC |
| `RESEARCH_DIAGNOSTIC` | run/artifacts + policy | run dataset cutoff | run/artifact known time | bounded counts/ratios；DERIVED_METRIC |
| `RESEARCH_REPORT` | bounded projection fingerprint | underlying cutoff | max underlying known time | metrics/diagnostics 为 DERIVED_METRIC，prose 为 USER_NOTE |
| `PAPER_SESSION` | canonical observed snapshot | `updated_at` | `updated_at` | status/session/config identity；SYSTEM_STATE |
| `PAPER_ACCOUNT_SNAPSHOT` | canonical row fingerprint | `created_at` | `created_at` | cash/equity/exposure/PnL；FACT/SYSTEM_STATE |
| `RISK_DECISION` | decision + policy/input snapshot | `evaluated_at` | `evaluated_at` | decision/reasons/policy；FACT/SYSTEM_STATE |

ResearchExperiment hypothesis、ResearchReport prose 和其他研究文字始终为 `USER_NOTE`，不能支持 FACT claim。

### 5.2 DEFERRED

- mutable `MARKET_DATA_PROFILE` 直接 evidence；AI-2 只冻结 snapshot；
- ResearchJournal evidence；现有 entry 可 update/delete；
- Phase 6B 正式 MarketRulesVersion resolver；
- US realtime/session-aware evidence；
- embedding、Provider/SDK、chat、AI UI 和 PAPER/LIVE 写入。

## 6. EvidencePack

`ai_evidence_packs` 保存：

```text
id / analysis_run_id?
market / exchange? / instrument_id / asset_type / currency? / timezone
market_rules_version?
market_data_cutoff / knowledge_cutoff / analysis_mode
requirements_json / evidence_policy_version
items_json / item_count / serialized_size_bytes
fingerprint / created_at
```

fingerprint 依赖 policy、双 cutoff、market context、requirements 和按稳定 key 排序后的 items；不包含 id、created_at 或插入顺序。

`EvidencePolicyVersion=1` 固定 `max_items=128`、`max_total_serialized_bytes=262144`、`max_case_count=20`，并执行 sensitive-field scan、ref 唯一性与 fingerprint 完整性检查。超限返回 `EVIDENCE_PACK_TOO_LARGE`，不写数据库。

敏感字段扫描在 Core evidence 层完成，覆盖大小写、snake/camel/kebab 变体和嵌套对象，包括 api key、client secret、access/refresh/bearer token、authorization、password、broker credential 与 gateway secret。

## 7. Temporal validation

`TemporalValidator` 是纯函数，稳定 findings 包括：

- `MARKET_DATA_AFTER_CUTOFF`；
- `KNOWLEDGE_AFTER_CUTOFF`；
- `CASE_AFTER_CUTOFF`；
- `MARKET_MISMATCH`；
- `ASSET_TYPE_MISMATCH`；
- `MARKET_RULES_MISMATCH`；
- `MISSING_MARKET_RULES`；
- `TEMPORAL_METADATA_UNAVAILABLE`；
- `STALE_MARKET_DATA`。

cutoff 边界使用 `<=`，等于 cutoff 合法。不能用 1970、now 或 market-local midnight 代替缺失时间。`REALTIME` 的 30 秒上限属于 ResearchGatePolicy，不硬编码到 domain enum；`IMMUTABLE_HISTORICAL` 不受当前 30 秒规则影响。

## 8. Structured claim contract

`ResearchCandidate` 使用严格 Pydantic model，包含 `schema_version / action_type / recommendation / claims[]`。第一版只允许 `RESEARCH_RECOMMENDATION / EXPERIMENT_DRAFT / JOURNAL_DRAFT / THESIS_REVISION_DRAFT`。

`ResearchClaim` 包含：

```text
claim_id
claim_type                 # FACT / INFERENCE / HYPOTHESIS
text
evidence_refs[]
subject?
predicate?                 # EQ/NE/GT/GTE/LT/LTE/DELTA/PERCENT_CHANGE
value?
unit?
uncertainty?
```

FACT 必须引用 pack ref 并可确定性验证；INFERENCE 必须有 refs，其结构化事实部分仍需 ground；HYPOTHESIS 可以无 evidence，但不得伪装为 FACT；USER_NOTE 不能支持 FACT；candidate 只能引用 pack 中已有 ref。

## 9. GroundingPolicy 与 predicates

`GroundingPolicyVersion=1` 固定：COUNT/INTEGER exact；CURRENCY/MONEY 使用 Decimal absolute tolerance `0.01`；RATIO 使用 absolute `1e-8`、relative `1e-6`；NUMBER 使用 absolute `1e-9`、relative `1e-6`；ENUM/STRING/BOOLEAN canonical exact。调用方和 candidate 不能传 tolerance。

`DELTA` 和 `PERCENT_CHANGE` 必须恰好引用两个有序 operand refs，由 Core 计算：

```text
DELTA = operand_0 - operand_1
PERCENT_CHANGE = (operand_0 - operand_1) / operand_1
```

Grounding findings 至少包括 `EVIDENCE_REF_NOT_FOUND / EVIDENCE_VALUE_MISMATCH / UNSUPPORTED_FACT / INFERENCE_WITHOUT_EVIDENCE / INVALID_FACT_TYPE / DUPLICATE_CLAIM_ID / DERIVED_OPERANDS_INVALID`。

## 10. 六层 Validation Pipeline

顺序固定且不可跳过：Syntax、Schema、Semantic、Grounding、Temporal、Immutable Fact。前一层存在 ERROR 时，不运行后续接受性校验。Finding 保存 `layer / code / severity / claim_id? / evidence_ref? / message_safe / retryable`。只有六层全部完成且 ERROR 数为零，candidate 才能 `ACCEPTED`。

Syntax 只接受标准 JSON，不从 Markdown code fence 猜测修复。非法 JSON 返回 `SYNTAX_INVALID_JSON`。Pydantic 错误映射为 `SCHEMA_MISSING_FIELD / SCHEMA_INVALID_TYPE / SCHEMA_INVALID_ENUM`，外部结果不包含完整 traceback 或敏感 payload。

SemanticValidator 检查空 recommendation、duplicate claim、FACT/INFERENCE 证据约束和 action allowlist。以下动作及等价别名一律 `FORBIDDEN_AI_AUTHORITY`、non-retryable：

- `EXECUTE_LIVE_ORDER`；
- `CREATE_ORDER_INTENT`；
- `APPROVE_EXECUTION`；
- `INCREASE_CAPITAL`；
- `UNFREEZE` / `UNFREEZE_ACCOUNT`；
- `ACTIVATE_LIVE`；
- `MODIFY_RISK_POLICY`。

Validation 不调用任何 PAPER/LIVE service，authority rejection 前后交易状态必须完全不变。

### 10.1 Immutable fact identity

retry 间 deterministic assertion identity 的 canonical payload 至少包含：

```text
claim_type
canonical subject
predicate
normalized evidence refs
canonical unit
derived operation
ordered operand refs
```

`claim_id` 不参与身份。direct predicates 的 refs 按稳定规则归一化；derived predicates 保留 operand 次序，调换 operand 会形成 drift。subject alias 必须映射为 evidence item canonical subject；unit 使用 policy allowlist 归一化，未知或不等价单位不能绕过比较。

attempt 间相同 assertion identity 的 asserted value 变化返回 `IMMUTABLE_FACT_DRIFT`。真实 accepted value 始终必须与 EvidencePack 相符；Attempt 1 的错误值不会成为事实。

### 10.2 Schema-invalid assertion observation

允许从已成功 JSON parse、但 schema-invalid 的 candidate 中 best-effort 提取字段完整、类型安全的 deterministic assertions，仅用于 retry consistency 和 forensic provenance：

```text
origin_attempt_id
trusted = false
acceptance_eligible = false
canonical assertion identity
observed asserted value
```

这些 untrusted observations 不能成为 accepted claim、不能进入 EvidencePack 或 ResearchCase fact、不能被其他 AnalysisRun 引用。即使单个 assertion grounding 正确，也不能绕过整个 Schema failure。它们只保存在 ValidationResult 的 `assertion_observations_json`，并按 attempt/run scope 读取。

## 11. ValidationResult persistence

`ai_validation_results` 保存：

```text
id
run_id
attempt_id?
evidence_pack_id
evidence_pack_fingerprint
validation_policy_version
status                     # ACCEPTED / REJECTED
layers_checked_json
findings_json
assertion_observations_json
normalized_output_fingerprint?
created_at
```

ValidationResult append-only；UPDATE/DELETE 由 SQLite trigger 拒绝。assertion observations 永远不提供跨 run evidence API。

Retry classification：syntax/schema 可 retry；grounding contradiction、fabricated ref、temporal leak、immutable drift、forbidden authority 和 security violation不可 retry。AI-2 只记录分类，不调用 Provider 或执行 retry。

## 12. ResearchGate

ResearchGate 只消费 Core facts：EvidencePack、Temporal findings、data quality/health、comparability 和 AnalysisRequirements。不存在 AI confidence 输入。

优先级固定：

```text
REJECT > WAIT_FOR_EVIDENCE > ABSTAIN > PROCEED
```

- deterministic violation、安全问题、temporal leak、market/asset/rules conflict：`REJECT`；
- evidence 缺失、REALTIME stale、required MarketRules 缺失：`WAIT_FOR_EVIDENCE`；
- not comparable 或问题本质上不可可靠回答：`ABSTAIN`；
- 其他情况：`PROCEED`。

reason codes 按固定 policy 顺序保存：`INVALID_EVIDENCE / TEMPORAL_LEAK / MARKET_MISMATCH / ASSET_TYPE_MISMATCH / MARKET_RULES_MISMATCH / MISSING_MARKET_RULES / INSUFFICIENT_EVIDENCE / STALE_MARKET_DATA / NOT_COMPARABLE / PROCEED`。

## 13. ResearchCaseDocument 与 retrieval

AI-1 ResearchCase 继续是 immutable case identity。AI-2 新增一对一、不可变 `ResearchCaseDocument`，只保存 bounded retrieval memory，不是事实源：

```text
id / case_id
title / summary / diagnosis
success_factors_json / failure_factors_json / regime_labels_json
strategy_family? / universe_id? / market_rules_version?
safe_tags_json / document_schema_version
fingerprint / created_at
```

document fingerprint 包含 canonical text/labels/metadata，不包含 id/created_at。文档创建后不可 update/delete；若同一 case 需要新解释，必须创建新 ResearchCase。prose 是 retrieval memory，不自动成为 FACT。

### 13.1 FTS derived index

FTS 只索引 title、summary、diagnosis、success/failure factors、regime labels 和 safe tags。禁止 raw response、credential、internal error、audit payload。

Repository 提供显式 `rebuild_research_case_fts()`：清空 virtual table并从 canonical documents 重建。普通 document + FTS insert 在同一事务中；FTS 可丢弃并重建。

### 13.2 RetrievalPolicyVersion=1

固定流程：

```text
hard filters
-> structured score
-> FTS lexical observation
-> quantized lexical component
-> deterministic rank
-> immutable RetrievalSnapshot
```

hard filters 包括 exact market、exact asset type、`case.as_of_utc <= market_data_cutoff`、`case.created_at <= knowledge_cutoff`、universe compatibility、仅在 query requires rules 时检查 MarketRules compatibility，以及 CN/US exact isolation。

strategy family 是固定高权重 structured score，不是默认 hard filter。调用方不能覆盖权重。

结构分使用整数：regime overlap、strategy family、universe、safe tags、cutoff 内 recency。FTS 原始 score 按稳定排序和固定阈值量化为整数 lexical component；最终业务分只使用整数。tie-break 为 `score DESC、case_end_at DESC、case_id ASC`。

### 13.3 RetrievalSnapshot

`ai_retrieval_snapshots` 保存：

```text
id / analysis_run_id?
query_context_json / retrieval_policy_version / hard_filters_json
all_candidate_ids_json
excluded_candidates_json        # case/document identities + reason codes
included_candidates_json        # fingerprints + score breakdown + rank
fingerprint / created_at
```

snapshot fingerprint 不含 created_at、FTS rowid 或 SQLite 内部状态。相同 query/policy/document corpus 产生相同 fingerprint。新增 case 或 FTS rebuild 不改变旧 snapshot。

## 14. Multi-market safety

- market 使用显式 `CN_A_SHARE / US_EQUITY`；
- instrument 使用 instrument_id，不能仅凭 symbol；
- CN 与 US hard filter 隔离；
- 无 `cross_market` 参数或隐藏开关；
- MarketRulesVersion 缺失仅阻塞依赖规则的分析；
- US contract 可存储 USD、ETF/EQUITY、timezone，但 US realtime/session-aware evidence等待 6B。

## 15. Persistence、事务与 API

Migration 线性接在 `20260827_0014` 后，revision id 唯一，使用当前日期序列 `20260830_0015`。迁移必须验证：

- empty -> head；
- 0013 -> 0014 -> 0015；
- 0014 -> 0015；
- 0015 -> 0014 -> 0015；
- FTS create/search/rebuild；
- single head；
- 四张历史表 UPDATE/DELETE 全部失败；
- FTS virtual table可重建，不声明为 provenance。

API 只新增安全只读端点：

```text
GET /api/v1/ai/evidence-packs/{id}
GET /api/v1/ai/retrieval-snapshots/{id}
GET /api/v1/ai/validation-results/{id}
```

不公开 arbitrary resolver 或 candidate validation POST。内部 service 负责 pack、validation 和 retrieval 创建。

## 16. Restart recovery 与 adversarial tests

EvidencePack、ValidationResult、ResearchCaseDocument、RetrievalSnapshot 创建后销毁 app/engine，再连接同一 SQLite，必须恢复相同 fingerprint、items、findings、assertion observations、scores 和 policy versions。

测试至少覆盖：

- dict key order、item insertion order、created_at 变化不影响 semantic fingerprint；
- future bar、future case、old-market/later-known case、cutoff equality、timezone boundary、market mismatch、missing temporal metadata；
- correct/wrong FACT、missing/invented ref、INFERENCE no refs、HYPOTHESIS no refs、risk decision/equity mismatch；
- Core recomputed DELTA/PERCENT_CHANGE、operand swap、claim id/alias/unit/ref-order bypass；
- schema-invalid assertion `trusted=false` 且不能接受或跨 run 引用；
- authority escalation全部 non-retryable，PAPER/LIVE 状态不变；
- valid/missing/stale/leak/mismatch/not-comparable Gate；
- CN/US isolation、future/future-known case exclusion、MarketRules conditional filter、FTS/structured ranking、tie、same fingerprint、snapshot immutability；
- FTS rebuild 前后业务排名相同；
- no embedding/provider/SDK/trading write imports。

## 17. 阶段边界调整

本批准覆盖原总架构中分散在 AI-2、AI-4 和 AI-5 的 EvidencePack、temporal validation、六层 deterministic validators、ResearchGate、SQLite FTS retrieval 与 RetrievalSnapshot。它们统一前移到 AI-2，因为未来 Provider 必须先面对已存在且已验收的确定性边界。

调整后：

- AI-2：本设计全部内容；
- AI-3：Provider isolation、Fake Provider、OpenAI-compatible adapter、budget enforcement；
- AI-4：使用 AI-2 contract 的 two-stage diagnosis/recommendation，不重造 validators/gate；
- AI-5：ResearchThesis、incremental case chain、delta summary 与后续 memory evolution；
- AI-6+：Copilot、draft confirmation、UI 与最终验收。

## 18. 完成标准

只有 Resolver allowlist、EvidencePack、双 cutoff、claims、grounding、derived recompute、immutable drift、untrusted observation、ResearchGate、FTS retrieval、snapshot、append-only、restart recovery、migration matrix、Ruff、mypy、完整 backend/frontend gate 全部通过，才可声明：

```text
AI-2 EVIDENCE & TEMPORAL VALIDATION STABLE
READY FOR AI-3 PROVIDER ISOLATION
```

完成后立即停止，不实现任何 AI-3 内容。
