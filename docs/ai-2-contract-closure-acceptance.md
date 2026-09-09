# AI-2 合同收口验收记录

状态：`AI-2 EVIDENCE & TEMPORAL VALIDATION STABLE`。

`READY FOR AI-3 PROVIDER ISOLATION` 仅表示 AI-2 前置合同与验收完成。本轮已停止，不实施 AI-3。

## Git 与验收对象

- 分支：`dev`。
- 续接起点：`59579a4787f0b66200ed49a0a4428a75b6af7e37`，工作树干净。
- 该提交为 `fix(ai): close evidence and validation contracts`；前一提交为 `8e2f019ac04db6dee094635e4630a6f5accb047d`。
- 起点相对本地 `origin/dev` tracking ref 为 ahead 7、behind 0；未 fetch，不代表远端实时状态。
- 不 push、merge、rebase、reset、amend，不新建 branch/worktree。
- 使用 TEMP 隔离数据库，不操作真实业务数据库。

## 完整门禁

正式命令：`powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/test.ps1`。

上次执行以子进程退出码 `1073807364` 中断，不能算 PASS。2026-09-09 在 `59579a4` 可执行内容上串行补跑成功：退出码 0，后端 700 / AI 172，前端 10 文件 / 48 测试，Ruff、mypy（111 文件）、TypeScript/Vite 均通过。该结果不能覆盖后来新增的合同修复。

修复后的最终完整门禁已正常结束，退出码 **0**，末行为 `All backend and frontend checks passed.`。执行对象为 `59579a4` 加本轮 backend 工作树修改；验收期间及之后仅同步 Markdown。未新增或修改 migration、依赖、配置、scripts 或 frontend。

| 后端分片 | 实际通过数 |
|---|---:|
| foundation | 22 |
| datasets-a | 70 |
| datasets-b | 87 |
| market-data | 107 |
| backtest | 41 |
| research | 32 |
| paper | 142 |
| execution | 27 |
| ai | 206 |
| 合计 | 734 |

全部后端分片实际收集并通过共 734 项：failed 0、errors 0、skipped 0。AI 从续接前 172 项增加到 206 项（新增 34 项），不是沿用历史 107 项基线。前端为 10 files / 48 tests 全部通过，无跳过。Ruff 全部通过；mypy 检查 111 个源文件无错误；`tsc -b && vite build` 成功，Vite 构建 45 个模块。全部预期分片和前端检查均实际执行，没有未执行项。

非失败提示：mypy 保留 `backend/src/quant_lab/backtest/service.py:230` 的 annotation-unchecked note；npm 输出新版本 notice，未安装升级。Git 有全局 ignore 文件读取权限及 LF/CRLF 提示，未为此修改用户全局配置。部分分片墙钟耗时很长（datasets-b 8456 秒、PAPER 3285.76 秒），不据此推测原因，也未缩减门禁。

固定可执行内容的校验值（最终验收结束后已再次比较，两项完全一致）：

- tracked backend/scripts/frontend diff 的 UTF-8 SHA256：`80CE5FE205FC0CB99065127DE45447B11845AA49E30BDAA6C8FDF7040F4186DA`。
- 新增 `backend/tests/ai/test_ai2_final_acceptance.py` 文件 SHA256：`C5319841E0950A69E488C027A0B82DA9DFD1405F7817AE645DCADDB467C9F52E`。
- diff 计算方式为 `git diff --binary HEAD -- backend scripts frontend` 按 LF 连接后 UTF-8 编码；新测试尚未 tracked，因此另记文件哈希。

## 五类合同证据

下列实现均位于 `backend/src/quant_lab/ai/`，测试位于 `backend/tests/ai/`。测试通过不是合同正确性的唯一依据。

| 缺口 | 实现路径 / 符号 | 现有回归 | 当前核对结论 |
|---|---|---|---|
| CanonicalEvidenceItem / EvidenceRef | `contracts.py:CanonicalEvidenceItem`；`resolvers.py:ExplicitSnapshotResolver.resolve`；`packs.py:EvidencePackService.freeze` | `test_ai2_contract_closure.py` 的 typed contract、value fingerprint、Core-derived ref、bounded context；`test_ai2_api.py:test_restart_preserves_full_evidence_and_schema_contract` | 字段、Core 派生引用、版本和序列化参与运行；敏感 context 及金额单位已补回归 |
| 11 类 Resolver | `source_resolvers.py:build_domain_resolver_registry`、`_DomainSnapshotLoaders` | `test_ai2_concrete_resolvers.py:test_each_supported_source_resolves_from_real_domain_records`（11 类参数）与 `test_concrete_resolvers_are_read_only` | 使用 TEMP SQLite 正式领域模型与真实 repository/service，不是 fake payload-only resolver；风控投影与研究时间语义已修复 |
| Claim / Grounding | `contracts.py:StructuredClaim`、`StructuredCandidate`；`validation.py:ValidationService.validate`、`assertion_identity` | `test_ai2_contract_closure.py` 谓词、派生公式、重复 ID、recommendation；`test_ai2_adversarial_validation.py` drift / untrusted observation；新增单位和 claim_type 回归 | 跨单位断言及混币种 operands 拒绝；别名兼容；不提供自然语言 NLI |
| Schema findings | `validation.py:_schema_findings`、`_schema_field_path`；`gates.py:ResearchGate.decide` | `test_pydantic_errors_map_to_stable_schema_findings`、restart API、`test_deterministic_errors_precede_missing_rules` | 三类稳定错误、嵌套路径、安全输出与混合 ERROR 优先级均有回归 |
| Freshness | `contracts.py:FreshnessClass`、`FreshnessRequirement`；`policies.py:AI2Policy`；`ValidationService.validate` | `test_freshness_requirement_matrix_is_deterministic`、`test_stale_realtime_is_wait_not_reject_with_deterministic_reference_now`、`test_missing_market_rules_only_blocks_rule_dependent_analysis` | 历史不套 30 秒过期；显式 reference_now；MarketRules 缺失仅影响相关分析；stale 不掩盖双 cutoff 违规；最终门禁通过 |

## 具体领域接线

| 来源 | 正式读取边界 |
|---|---|
| DATASET_VERSION | `DatasetRepository.get_version`，结合 Dataset/Version 元数据 |
| MARKET_DATA_SNAPSHOT | `BacktestRepository.get` 或 `PaperRepository.get_session` 中冻结 JSON；不读取 Profile 最新绑定 |
| STRATEGY_VERSION | `StrategyLibrary.version` |
| BACKTEST_RUN | `BacktestRepository.get/artifacts` 与 `ArtifactReader` |
| RESEARCH_EXPERIMENT | `ResearchRepository.get_experiment/list_run_links` 与关联 BacktestRun |
| RESEARCH_COMPARISON | `BacktestComparisonService.compare` 与上述研究关联 |
| RESEARCH_DIAGNOSTIC | `ResearchDiagnosticsService.compute` |
| RESEARCH_REPORT | `ResearchReportService.run_report` 的受限投影 |
| PAPER_SESSION | `PaperRepository.get_session` |
| PAPER_ACCOUNT_SNAPSHOT | `PaperRepository.get_snapshot/get_session/get_account` |
| RISK_DECISION | `PaperRepository.get_risk_decision/get_intent/get_policy_version/get_session` |

TEMP 模型测试验证读取与投影，不冒称 11 类均重新执行了完整发布、回测或 PAPER replay。正式 Resolver 构造器是 Core 内部调用边界；AI-2 HTTP API 只读 provenance，不提供模型执行或外部 source payload 写入口。

## 安全与验证边界

- FACT 必须 grounding；INFERENCE 必须引用 evidence；HYPOTHESIS 可无 evidence。结构化断言通过不证明任意自由文本真实。
- uncertainty 是 LOW/MEDIUM/HIGH 标签，不是校准概率或资金管理输入。
- schema-invalid assertion 只作为带 origin attempt、`trusted=false` 的观察，用于 retry consistency / forensic provenance；不进入 accepted assertions、EvidencePack 或 ResearchCase fact。
- ResearchCaseDocument 是 durable retrieval input，FTS 是可重建 derived index，RetrievalSnapshot 是 durable result；本轮不改变检索架构。
- Provider/SDK、真实模型、streaming/chat/AI UI、embedding、PAPER/LIVE 写入、Broker/Gateway/资金授权均不引入。
- 正式 MarketRules resolver、US realtime/session-aware evidence 仍 Deferred；当前领域数据以已有 CN 能力为准，不伪造 US 接线。

## 本轮实际发现、修复与回归

新增回归全部位于 `backend/tests/ai/test_ai2_final_acceptance.py`。首次运行 31 项得到 16 failed / 15 passed，证明不是只补文档；随后两项和最后一项组合回归也分别先复现失败再修复。

| 实际问题 | 最小修复 | 回归测试名 |
|---|---|---|
| 同值跨单位 FACT 或跨币种 operands 被接受 | 单位归一化后必须一致；DELTA 保留单位，PERCENT_CHANGE 为 RATIO | `test_fact_rejects_equal_value_in_different_unit`、`test_unit_alias_remains_valid`、`test_derived_operands_cannot_mix_currencies` |
| 金额字段输出 CURRENCY 占位 | Resolver 使用正式 account currency | `test_money_resolver_uses_actual_account_currency` |
| 风控冻结投影使用不存在的 code | 使用领域已有 DAILY_LOSS_LIMIT / DRAWDOWN_LIMIT，纯读取 | `test_risk_freeze_projection_uses_formal_reason_codes` |
| evaluated_metrics 被替换成 account/market 包装对象 | 读取已保存的 `market_context.evaluated_metrics`；缺失时 fail closed | `test_risk_evaluated_metrics_are_the_persisted_domain_result` |
| 可变研究关联使用旧回测时间 | 当前投影由 Core server clock 观察，known_at 不早于当前观察与领域已知时间；不修改原记录 created_at | `test_mutable_research_projection_uses_system_observation_time` |
| Report 指纹随 Deferred Journal 改变 | fingerprint 只绑定受限确定性投影、artifact identity、run input 与 projection policy | `test_report_evidence_fingerprint_excludes_deferred_journal` |
| Schema 等 ERROR 被缺证据优先级覆盖 | 所有非 missing/stale/unanswerable ERROR 优先 REJECT | `test_deterministic_errors_precede_missing_rules` |
| allowlisted context 值可包含 secret，且冻结前未复查 | DTO 检查 secret-shaped 文本；EvidencePack 冻结前再次检查 context | `test_secret_text_in_allowlisted_context_is_rejected`、`test_pack_rechecks_mutated_context_before_freezing` |
| freshness 过期掩盖未来知识违规 | 双 cutoff 检查不因 stale 短路，ResearchGate 保持 REJECT | `test_stale_evidence_does_not_hide_future_knowledge_violation` |

还覆盖三种 claim_type 的证据要求，以及所有 11 类具体 Resolver 在加载前拒绝非法 field。共享 TEMP fixture 改为显式固定测试 clock，风控 fixture 使用正式 APPROVE / reason codes / evaluated_metrics 结构，没有删除旧测试或弱化断言。

`ai-evidence-v2`、`ai-validation-v2`、`ai-research-gate-v2`、concrete resolver policy `2` 标记本次语义修正；retrieval policy 仍为 `ai-retrieval-v1`。旧 JSON provenance、旧 RetrievalSnapshot 不回写、不重算、不迁移。

## 兼容性证据索引

- `test_ai2_retrieval.py`：2026 才创建的历史 case 不进入 2024 knowledge cutoff，CN/US 隔离，strategy family 为评分而非硬过滤，MarketRules 条件过滤。
- `test_ai2_fts_recovery.py:test_fts_rebuild_preserves_business_ranking_and_old_snapshot`：重建排名稳定且不改变旧 snapshot。
- `test_ai2_restart_recovery.py:test_restart_rebuilds_fts_from_canonical_documents_only`：重启只从 canonical documents 重建索引。
- `test_ai2_api.py:test_restart_preserves_full_evidence_and_schema_contract`：dispose/restart 后新 Evidence DTO、fingerprints、freshness/context 与 schema findings 一致读取。
- `test_ai2_migration.py:test_history_rows_are_append_only_but_fts_is_disposable`、`test_provenance_migration.py`：历史不可变，FTS 可丢弃。
- 本轮无 migration；只读 `alembic heads` 验证 head 为 `20260830_0015`。空库升级、0014→0015、downgrade/upgrade 矩阵由隔离测试覆盖，不操作真实数据库。

局部验收：修复后相关 105 项通过；补充修复后的 AI 全分片 205 项通过；最后增加 cutoff/stale 回归并修复后相关 44 项通过。上述为过程证据；最终依据为本报告记录的正式全门禁 734 / AI 206 全部通过。temporal / retrieval / FTS / append-only / restart / migration matrix 均包含在最终 AI 分片内并通过。

## 文档与最终结论

本轮文档更新：`ARCHITECTURE.md`、`docs/ADR-0003-ai-research-copilot-boundary.md`、AI 架构 spec、AI-2 design、原 AI-2 implementation plan、contract closure plan、本验收记录。README 未改为开发日志。

完整门禁之后仅更新 Markdown 状态/说明，代码校验值已复核一致；最终提交包含原样已验收代码与文档，不声称在提交完成后又跑过整套测试，也没有为纯文档状态再次重复耗时门禁。正常前向提交信息为 `fix(ai): finalize contract closure acceptance`；完整提交 SHA、最终工作树与 ahead 数以交付汇报中的提交后 Git 复核为准。

五类已批准合同的已知缺口均关闭，无 AI-2 阻塞项。Deferred 范围仍 Deferred，不把 Provider、US realtime、正式 MarketRules、embedding、AI UI 或交易写入算作已实现。

最终状态：

```text
AI-2 EVIDENCE & TEMPORAL VALIDATION STABLE
READY FOR AI-3 PROVIDER ISOLATION
STOP BEFORE AI-3
```
