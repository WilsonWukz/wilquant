# AI-4 两阶段研究分析设计

状态：用户批准的统一方案、六项补充及 SERVER_FROZEN_CURRENT 十项语义已实现并通过完整门禁和合同审查。AI-4 TWO-STAGE RESEARCH COPILOT STABLE；验收证据见 docs/ai-4-research-acceptance.md。停止在 AI-5 之前。

## 已批准的服务端知识截止冻结协议

knowledge_cutoff_mode 明确区分 EXPLICIT / SERVER_FROZEN_CURRENT。历史回放仅 EXPLICIT；显式 cutoff 必须保持原值，不接受客户端 resolved cutoff。SERVER_FROZEN_CURRENT 仅用于 CURRENT_RESEARCH，客户端不同时提交 knowledge_cutoff。

Core 先持久化 submitted request identity、create key 与唯一 owner，观察获准来源并持久化不可变投影 artifact，然后以服务器 aware UTC 时间冻结 resolved_knowledge_cutoff，经过原 AI-2 双时间校验后冻结 EvidencePack、RetrievalSnapshot 与 resolved_analysis_input_fingerprint。不得改写来源 known_at；服务器时钟异常或来源未来时间仍失败关闭，不通过取最大未来时间绕过验证。market_data_cutoff 不扩大。

submitted_request_fingerprint 只包含请求内容；resolved_analysis_input_fingerprint 包含最终 cutoff、Pack/Retrieval、政策、模板与冻结上下文。不同 Run 可在不同观察时间产生不同 resolved identity。同 create key 并发由数据库 owner 串行化，重放返回首次结果。观察中断 key 保留失败记录，禁止重新观察，创建新分析需要新 key；无后台重试。

Stage1 retry、Stage2、retry、显式 resume 和 restart 均读取冻结 artifact/Pack，不重新读取 Experiment 或 Comparison。案例继续执行 case_end_at <= market cutoff 与 known_at <= resolved cutoff；摘要仍不是 FACT。

## 范围

一个 AIAnalysisRun 表示一次逻辑研究分析。Core 固定请求、证据、案例检索、两套 PromptTemplateVersion、一个 ModelConfigVersion、analysis/stage contract versions 和 policy。所有模型调用经过 AI-3 Host，串行执行 diagnosis → 六层校验 → deterministic gate → recommendation → 同一六层校验。无 UI、聊天、embedding、工具、草稿副作用或交易写入；不访问 PA_Agent 源码，不进行外部 Provider smoke。

## 三种状态各司其职

Run 生命周期沿用 CREATED/RUNNING/VALIDATING/COMPLETED/FAILED/REJECTED/CANCELLED。独立持久化 StageProgress：CONTEXT_PREPARED、STAGE1_PENDING、STAGE1_ACCEPTED、STAGE_GATE_DECIDED、STAGE2_PENDING、STAGE2_ACCEPTED、TERMINAL。独立 AnalysisOutcome：PROCEEDED、WAIT_FOR_EVIDENCE、ABSTAINED、REJECTED、PROVIDER_FAILED、VALIDATION_FAILED、BUDGET_BLOCKED、CANCELLED、PROVIDER_RESULT_UNKNOWN。

有效诊断后 ABSTAIN 是 COMPLETED + ABSTAINED + TERMINAL，不是失败。未知上游结果可保留非终态 Run 和等待显式恢复标记；终态永不重开。旧 AI-1/3 Run 保留旧恢复策略，AI-4 仅对正式绑定的 Run 执行阶段恢复。

## 最小 0017

不修改 0014–0016。Attempt 增加不可变 nullable stage（旧记录保持 NULL）、parent_attempt_id、retry_reason_codes、validation_feedback_fingerprint。新 AI-4 Attempt 必须使用 STAGE_1_DIAGNOSIS 或 STAGE_2_RECOMMENDATION。

新增既有 Run 的一对一分析绑定/编排记录、执行 epoch 幂等/owner 记录，以及既有 Attempt 的不可变阶段输入绑定。不是新 Run。请求 identity 与 create key 唯一；每 Run/execute key 唯一，一个 Run 同时只一个 owner。数据库保存冻结 identity、artifact hash/path、validation linkage 与执行进度；accepted 完整 payload 和 Prompt 在有界内容寻址 artifact 内，不放 Trace/日志。

Attempt 输入绑定包括 stage、template/model/contract versions、base_prompt_fingerprint、rendered_prompt_fingerprint、EvidencePack、RetrievalSnapshot、request/cutoffs 和 Stage2 diagnosis fingerprint。retry 固定 base inputs，仅追加稳定安全反馈，实际 rendered fingerprint 必须随消息变化。所有 lineage 保留。

## Context、输出和唯一校验链

四类请求 MARKET_DIAGNOSIS、STRATEGY_REVIEW、EXPERIMENT_REVIEW、PAPER_REVIEW 选择服务端固定 source/field 政策，禁止 arbitrary source/field/messages。真实 Resolver registry、EvidencePack 和 RetrievalSnapshot 接线。案例只投影受限 summary 与正式 refs，memory/USER_NOTE 标注非可信，不自动成为 FACT。缺少确定性市场指标则 WAIT/ABSTAIN，不要求模型补规则或趋势。US 数据能力不在本轮伪造；市场/资产、双 cutoff 和 MarketRules 条件要求继续生效。

统一 ResearchDiagnosis/ResearchRecommendation envelope 与 typed optional analysis-specific sections。扩展 AI-2 ValidationService 的版本化合同入口，不复制四套 pipeline。完整 envelope Schema/Semantic 错误参与最终 disposition；共享 Grounding/Temporal/Immutable，schema-invalid assertions 只用于 trusted=false 的重试一致性观察。所有结构化事实必须在 claims 中表达，summary/section 不能另造未经校验的事实渠道。diagnosis_ref 仅是推断上下文引用。

SYSTEM、FACT、USER_NOTE、CASE_MEMORY、QUESTION、OUTPUT CONTRACT 分区序列化；自由文本都是非可信数据。PromptTemplateVersion 是服务端发布的正式版本，API 不接受自定义系统指令。模板渲染排除运行时间/attempt ID等无关 metadata，保证相同冻结输入相同 base fingerprint。

## Gate、预算、重试

预检与阶段转换 gate 均由 Core 决定，优先级 REJECT > WAIT_FOR_EVIDENCE > ABSTAIN > PROCEED。预检非 PROCEED 零调用；阶段 gate 非 PROCEED 不调用 Stage2。阶段 gate 结合 validation、完整性、类型政策、案例要求及 abstention，不使用模型 confidence 自我放行。

每阶段最多两次 validation retry，且服从冻结 ModelConfig 的整个 Run call/cost budget，不提升既有上限。每次 retry 新 Attempt、新 invocation ID、新反馈 fingerprint。已知 Provider 失败、未知结果、grounding/temporal/security/authority/drift 不自动 retry。Stage2 不重新检索或更新证据，失败/预算不足仍保留 accepted Stage1。

## API、幂等、恢复、取消

POST /api/v1/ai/analyses 创建冻结分析；POST /{id}/execute 显式成本调用；GET /{id} 返回安全摘要；POST /{id}/cancel 显式取消。create/execute 分别 key+payload fingerprint；重复返回同记录，冲突409；同 Run 执行中拒绝新 owner，终态不能被新 key 绕过。无队列/调度器；同步执行沿用 AI-3 分阶段 HTTP timeout 和请求/响应大小边界，不宣称严格总 wall-clock deadline。HTTP 断开不构成上游未执行证明。

执行 epoch 表达初次执行与显式恢复。重启不调用 Provider；已 accepted Stage1 + PROCEED 且 Stage2 未派发，显式新 epoch 只继续 Stage2。已 STARTED 的 Attempt 恢复为 ABANDONED/PROVIDER_RESULT_UNKNOWN，保留未知用量及 reservation；必须新 execute key + 显式 unknown 重试意图才创建新 Attempt。已收到且持久化的 candidate 可重新完成本地校验，不能重新调用模型。

取消在事务中与 dispatch reservation 竞争：无可能派发调用则安全 CANCELLED；已可能发送则 Attempt ABANDONED，Outcome CANCELLED、provider_result_unknown=true，保留预算；晚到结果不能重开 Run 或推进 Stage2。曾完成的调用费用不因之后取消消失。

Host 检查仅声明 host_ready/profile_valid/credential_store_accessible/credential_available，不声明真实认证、quota、可达或模型可用；不做 health completion。成本 API 严格 JSON、来源检查与本地授权，不把 CORS 当授权；不共享 Host secret、不提供 raw proxy。

## 验收

Fake 两阶段、真实 localhost 双 HTTP、gate 短路、schema retry、lineage/immutable drift、grounding/temporal/authority 拒绝、预算、并发幂等、取消、restart/resume、ABANDONED、重建 provenance、import boundary。TEMP 迁移 empty→head、0015→0016→0017、0016→0017、兼容空数据降级再升级；含新历史时拒绝有损降级。完整 scripts/test.ps1、Ruff/mypy、前端48项回归和构建，最后正常本地提交/clean-tree；不push，不进入AI-5。
