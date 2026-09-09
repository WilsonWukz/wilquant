# AI-2 Contract Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 关闭 AI-2 的 evidence、concrete resolver、claim/schema 和 freshness 五类合同阻塞，在不引入 Provider 或交易写路径的前提下恢复 stable 状态。

**Architecture:** 保持现有 AI-2 append-only JSON persistence 和 retrieval 设计，不新增 migration。由 Core resolver 从现有 SQLAlchemy domain repository/service 产生完整、可指纹化的 `CanonicalEvidenceItem`；validator 使用正式 semantic type、predicate 和 freshness policy 执行六层确定性验证。所有新行为按 RED→GREEN 小步实施，优先控制为两个 forward commits；数量不阻塞必要修复。

**Tech Stack:** Python 3.12、Pydantic v2、SQLAlchemy 2、SQLite/Alembic、pytest、Ruff、mypy、PowerShell quality gate。

## 当前执行状态（2026-09-09）

下方逐步命令保留为历史复现清单，不用其模板复选框推断当前进度。实际执行状态以本表及 `docs/ai-2-contract-closure-acceptance.md` 为准。

| 工作包 | 当前状态 |
|---|---|
| CanonicalEvidenceItem / Core-derived ref / context / policy | 已实现并通过局部回归 |
| 11 类具体 Resolver / TEMP domain / 无交易写副作用 | 已实现并通过局部回归 |
| Claim / Grounding / Schema / immutable observations | 已实现并通过局部回归 |
| Freshness / 双 cutoff / ResearchGate 优先级 | 已实现并通过局部回归 |
| 最终 scripts/test.ps1 | 已完成，退出码 0；后端 734 / AI 206；前端 10 文件 / 48 测试；全部静态检查与构建通过 |
| 最终文档状态与前向提交 | 文档已同步 STABLE；与最终已验收代码一起正常前向提交，不进入 AI-3 |

续接新增回归：`backend/tests/ai/test_ai2_final_acceptance.py`。修复范围、先失败再通过的证据、迁移/重启/FTS 兼容索引及验收代码校验值详见验收记录。

---

## File map

- `backend/src/quant_lab/ai/contracts.py`：正式 evidence/claim/freshness/schema DTO 与 enum。
- `backend/src/quant_lab/ai/policies.py`：versioned tolerance、freshness 和 gate policy。
- `backend/src/quant_lab/ai/resolvers.py`：Core-derived ref/value fingerprint、显式 field policy 与 registry。
- `backend/src/quant_lab/ai/source_resolvers.py`：11 类 domain source 的只读 loader/factory，不使用 generic ORM traversal。
- `backend/src/quant_lab/ai/validation.py`：stable schema mapper、predicate grounding、immutable identity 和 freshness validation。
- `backend/src/quant_lab/ai/gates.py`：`STALE_MARKET_DATA` 与四级决策优先级。
- `backend/src/quant_lab/ai/packs.py`：context/secret/size 安全与新字段持久化验证。
- `backend/tests/ai/test_ai2_contract_closure.py`：evidence、freshness、predicate、schema、drift 验收。
- `backend/tests/ai/test_ai2_concrete_resolvers.py`：TEMP SQLite 中 11 类真实 domain integration 验收。
- `backend/tests/ai/test_ai2_restart_recovery.py`：新 JSON contract 的 restart 一致性。
- `README.md`、`ARCHITECTURE.md`、`docs/ADR-0003-ai-research-copilot-boundary.md`、AI 架构/design/plan：过程状态与最终合同同步。

### Task 1: 锁定 evidence 与 freshness contract

- [ ] **Step 1: 写 evidence DTO 失败测试**

在 `test_ai2_contract_closure.py` 构造包含 `semantic_type=MONEY`、`freshness_class=REALTIME`、`observed_at`、`market_timestamp`、`context`、`resolver_policy_version` 的 item，断言 UTC normalization、enum 类型、不可变与完整 JSON round-trip。再断言值/单位相同时 `value_fingerprint` 相同，值或单位改变时不同。

- [ ] **Step 2: 确认 RED**

Run: `backend\.venv\Scripts\python.exe -m pytest backend/tests/ai/test_ai2_contract_closure.py -q`

Expected: 因 `EvidenceSemanticType` / `FreshnessClass` / 新字段不存在而失败。

- [ ] **Step 3: 实现最小 evidence contract**

增加 `EvidenceSemanticType(NUMBER/MONEY/RATIO/COUNT/TEXT/ENUM/DATETIME/BOOLEAN/IDENTIFIER/JSON)`、`FreshnessClass(IMMUTABLE_HISTORICAL/EOD/DELAYED/REALTIME)`、`FreshnessRequirement(HISTORICAL_OK/EOD_REQUIRED/DELAYED_OK/REALTIME_REQUIRED)`。`CanonicalEvidenceItem` 用 `ref_id/source_id/field_path/source_fingerprint/value_fingerprint` 正式命名，为已有内部调用保留只读 compatibility properties，但 serialized form 只输出 canonical name。

- [ ] **Step 4: 实现 Core fingerprints/context safety**

`value_fingerprint = sha256(canonical_json({value, semantic_type, normalized_unit}))`；`ref_id` 绑定 source identity、field path、source/value fingerprint、temporal metadata 和 resolver policy version。context 只允许 market/exchange/universe/analysis_scope/strategy_family，限制 key/count/depth/serialized bytes 并调用 secret scanner。

- [ ] **Step 5: 确认 GREEN**

Run: `backend\.venv\Scripts\python.exe -m pytest backend/tests/ai/test_ai2_contract_closure.py backend/tests/ai/test_ai2_contracts.py backend/tests/ai/test_ai2_resolvers.py -q`

Expected: PASS。

### Task 2: 连接 11 类 concrete domain resolvers

- [ ] **Step 1: 写 TEMP SQLite integration 失败测试**

在 `test_ai2_concrete_resolvers.py` 执行 Alembic head，通过正式 model/repository 创建 DatasetVersion、frozen MarketData snapshot（由 Backtest/PAPER frozen JSON 读取）、StrategyVersion、BacktestRun + metrics artifact、ResearchExperiment/link、comparison/diagnostic/report service input、PaperSession、PaperAccountSnapshot、RiskDecision。参数化断言 11 类 source 都能读取、missing/forbidden 失败、classification/semantic/temporal/fingerprint/version 正确。

- [ ] **Step 2: 确认 RED**

Run: `backend\.venv\Scripts\python.exe -m pytest backend/tests/ai/test_ai2_concrete_resolvers.py -q`

Expected: 因 `build_domain_resolver_registry` 与 concrete loader 不存在而失败。

- [ ] **Step 3: 实现显式 SourceFieldPolicy**

每个 field 显式声明 classification、semantic type、unit；每个 source policy 声明 `resolver_policy_version="1"`。删除 arbitrary `values`/getattr 路径，loader 仅返回 allowlisted canonical values。

- [ ] **Step 4: 实现只读 domain factory**

`build_domain_resolver_registry(engine, artifact_root)` 显式使用 `DatasetRepository`、`StrategyLibrary`、`BacktestRepository`、`ResearchRepository`、`BacktestComparabilityService`、`ResearchDiagnosticsService`、`ResearchReportService`、`PaperRepository`/相应 ORM 查询。所有 missing 翻译为 `EvidenceSourceNotFound`，时间元数据缺失翻译为 `TemporalMetadataUnavailable`，不使用 `now()` 补值。

- [ ] **Step 5: 确认 GREEN**

Run: `backend\.venv\Scripts\python.exe -m pytest backend/tests/ai/test_ai2_concrete_resolvers.py backend/tests/ai/test_ai2_source_resolvers.py -q`

Expected: PASS，11 类 source 均有真实 TEMP SQLite coverage。

### Task 3: 收口 claim、schema 与 immutable validation

- [ ] **Step 1: 写 claim/schema 失败测试**

增加 `text`、`uncertainty`、candidate/claim `recommendation` allowlist，参数化 EQ/NE/GT/GTE/LT/LTE/DELTA/PERCENT_CHANGE，覆盖 semantic tolerance、TEXT 大小比较拒绝、`(new-old)/abs(old)`、zero denominator、ordered operands、duplicate claim id。构造 missing/type/enum/nested schema error，断言 stable code 和 `claims[2].predicate` field path。

- [ ] **Step 2: 确认 RED**

Run: `backend\.venv\Scripts\python.exe -m pytest backend/tests/ai/test_ai2_contract_closure.py -q`

Expected: 因新 predicate/schema code 不存在或旧计算结果不符而失败。

- [ ] **Step 3: 实现 normalized claim contract**

`ClaimPredicate` 持久化值只使用 EQ/NE/GT/GTE/LT/LTE/DELTA/PERCENT_CHANGE，validation-only parser 可将 EQUALS/GREATER_THAN/LESS_THAN 映射为 canonical value。`Uncertainty` 只允许 LOW/MEDIUM/HIGH，recommendation 只允许 research draft/review/wait allowlist。

- [ ] **Step 4: 实现 stable schema mapper 和 predicate grounding**

Pydantic `missing`→`SCHEMA_MISSING_FIELD`，literal/enum→`SCHEMA_INVALID_ENUM`，其余类型错误→`SCHEMA_INVALID_TYPE`；路径格式化为 JSON-like field path。比较 tolerance 仅依 semantic type；二元派生量按有序 operands 重算；新 stable findings 使用 `EVIDENCE_REF_NOT_FOUND`、`EVIDENCE_VALUE_MISMATCH`、`SEMANTIC_PREDICATE_NOT_SUPPORTED`、`DERIVED_DIVISION_BY_ZERO`。

- [ ] **Step 5: 确认 GREEN**

Run: `backend\.venv\Scripts\python.exe -m pytest backend/tests/ai/test_ai2_contract_closure.py backend/tests/ai/test_ai2_validation.py backend/tests/ai/test_ai2_adversarial_validation.py -q`

Expected: PASS，schema-invalid observations 仍然 `trusted=false` 且不被 accepted。

### Task 4: 实现 freshness gate 与 restart/security regression

- [ ] **Step 1: 写 freshness 失败测试**

用固定 `reference_now` 覆盖 historical never stale、EOD→EOD required、EOD→realtime wait、DELAYED 不升级、fresh realtime proceed、stale realtime→`WAIT_FOR_EVIDENCE/STALE_MARKET_DATA`。新增 nested dict/list/camelCase/snake_case/mixed-case credential corpus 与 AI package forbidden import/write 静态扫描。

- [ ] **Step 2: 确认 RED**

Run: `backend\.venv\Scripts\python.exe -m pytest backend/tests/ai/test_ai2_contract_closure.py backend/tests/ai/test_ai_execution_boundary.py -q`

Expected: 因 freshness evaluator/policy 未完成而失败。

- [ ] **Step 3: 实现 policy-driven freshness**

`AI2Policy.realtime_max_age_seconds=30`、`research_gate_policy_version` 显式化；validator 接收 aware UTC `reference_now` 和 `FreshnessRequirement`，将类别不满足或 realtime 过期统一产生 `STALE_MARKET_DATA`。MarketRules 仍是独立条件，不依赖规则时允许 null。

- [ ] **Step 4: 验证 restart JSON 与 no-side-effect**

扩展 restart 测试，完全 dispose/reconnect 后比较 semantic type、value fingerprint、freshness、context、resolver version 和 stable schema findings。静态扫描确认 AI package 无 Gateway/Broker/PAPER-LIVE write/RiskPolicy/CapitalAuthorization/OrderIntent 边界突破。

- [ ] **Step 5: 运行 AI shard**

Run: `backend\.venv\Scripts\python.exe -m pytest backend/tests/ai -q -p no:cacheprovider`

Expected: 旧 107 项与新 closure tests 全部 PASS。

### Task 5: 文档恢复 stable、全门禁与两个 forward commits

- [ ] **Step 1: 同步真实合同**

只有最终可执行内容的完整 `scripts/test.ps1` 门禁退出码为 0，且五类合同核对全部通过后，才能将状态从 `CONTRACT CLOSURE IN PROGRESS` 恢复为 `AI-2 EVIDENCE & TEMPORAL VALIDATION STABLE`。记录 canonical field、8 predicates、4 freshness classes/requirements、11 concrete domains、stable schema codes 与 no-migration 决策；纯 Markdown 后续同步不要求重复完整门禁。

- [ ] **Step 2: 运行静态门禁**

Run: `backend\.venv\Scripts\python.exe -m ruff check backend/src backend/tests backend/alembic`

Run: `backend\.venv\Scripts\python.exe -m mypy backend/src`

Run: `git diff --check`

Expected: 全部 exit 0。

- [ ] **Step 3: 提交实现与主验收测试**

Run: `git add <closure source/tests/docs> && git commit -m "fix(ai): close evidence and validation contracts"`

Expected: 第 1 个 forward commit，不 amend。

- [ ] **Step 4: 运行完整门禁**

Run: `powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/test.ps1`

Expected: backend/AI/Ruff/mypy/frontend/TypeScript/Vite 全绿，末行为 `All backend and frontend checks passed.`

- [ ] **Step 5: 如完整门禁需要修正，仅追加第 2 个 commit**

先增加或修正失败回归测试，重跑相关 shard 与 `scripts/test.ps1`，然后执行 `git commit -m "test(ai): complete ai-2 contract acceptance"`。如无修正则不为满足两个 commit 而制造空提交。

- [ ] **Step 6: 最终证据**

Run: `git status --short`

Run: `git rev-list --left-right --count origin/dev...dev`

Expected: working tree clean；优先将本轮收口控制在已有提交加 0–1 个必要提交，但不能为守住数量而放弃必要修复；不 push、amend、reset、rebase 或改写历史。

## 2026-09-09 续接验收

- 起点：`59579a4787f0b66200ed49a0a4428a75b6af7e37`，`dev`，工作树干净。
- 上次门禁在 datasets-b 进程异常终止，退出码 `1073807364`，结果不完整，不能算 PASS。
- 正在串行执行补跑；测试期间仅同步 Markdown，不修改可执行内容。
- 只读合同核对发现：Grounding 缺少单位匹配；Risk `freeze_required` 投影使用了不存在的 reason code；研究关联可变时间与旧回测完成时间混淆；报告完整指纹包含已延后的 Journal 内容；ResearchGate 对未列举的 ERROR 与缺证据混合时优先级不正确。
- 门禁结束后按相关回归先复现、最小修复、最终统一完整门禁的顺序处理，不进入 AI-3。

## Self-review

- Spec coverage：五个 blocker、11 resolver、8 predicates、schema mapper、4 freshness classes/requirements、security/restart/docs/full gate 都有对应 task。
- Placeholder scan：无 TBD/TODO/未定实现；每个 RED/GREEN 都有具体命令和期望。
- Type consistency：统一使用 `ref_id`、`field_path`、`source_fingerprint`、`EvidenceSemanticType`、`FreshnessClass`、`FreshnessRequirement` 和 8 个 canonical predicates。
- Scope：不新增 migration/SDK/provider/UI/embedding/trading write，不重做 retrieval。
