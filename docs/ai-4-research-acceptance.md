# AI-4 两阶段研究分析验收报告

日期：2026-09-11。状态：AI-4 TWO-STAGE RESEARCH COPILOT STABLE。完整门禁及独立合同/质量审查均通过；停止在 AI-5 之前。

## A. Git

- Branch：dev。
- HEAD before：4d1ca8e21d23e41c106eb344a04554b7580b1735。
- 验收代码提交：99edffd42ea4474753e357cda4d27d76006d8acc（feat(ai): add validated two-stage research copilot）。
- 本报告与设计/操作说明作为第二批普通本地文档提交；最终 HEAD 和提交后 working tree 状态在交付消息中复核记录，避免报告自引用尚未生成的 commit identity。
- 开始时本地 origin/dev 引用：behind 0 / ahead 9；未 fetch，不推断实时远端。
- 禁止项保持：无 push、merge、rebase、reset、amend、新分支或 worktree。

## B. Analysis Contract

统一 ResearchAnalysisRequest，四种 analysis_type：MARKET_DIAGNOSIS、STRATEGY_REVIEW、EXPERIMENT_REVIEW、PAPER_REVIEW。统一 ResearchDiagnosis/ResearchRecommendation 版本化 envelope，typed optional sections，不复制 pipeline。一个 AIAnalysisRun；lifecycle、AnalysisOutcome、StageProgress 分离。

create 与 execute 各自 idempotency key/payload identity；同 key 同 payload 重放，同 key 不同 payload 409。执行 epoch 为 INITIAL / RESUME / RETRY_UNKNOWN；单 owner，不重开终态。

## C. Context 与 Evidence

真实固定来源政策 → AI-2 Resolver → canonical evidence → ResearchCase retrieval → bounded memory 回溯 → 最终 EvidencePack。FTS 仍为 derived index；memory 摘要不升 FACT，事实必须回正式来源验证 ref/source/value fingerprint。PAPER 选定 snapshot/risk 校验 session/account/intent/policy 关系。

EXPLICIT 保持原 knowledge cutoff；HISTORICAL_REPLAY 必须显式。SERVER_FROZEN_CURRENT 先持久化 submitted identity 和唯一 owner，捕获并持久化来源投影后生成服务器 aware UTC cutoff，再按原双时间规则冻结 Pack/Retrieval/resolved identity。已观察来源在基础证据和案例回溯共享缓存，同 key、Stage2、retry、resume 不重新观察本轮来源。未来 known/effective 仍拒绝；market cutoff 不扩大，known_at 不回填。freshness 复用正式校验，不将无 MarketRulesVersion 变成所有研究的硬阻塞。

## D. Stage 1

RESEARCH_DIAGNOSIS_V1 + 服务端发布 PromptTemplateVersion；经 AI-3 Host 派发，每次调用一个带 STAGE_1_DIAGNOSIS 的 Attempt。candidate 经同一六层管线，无 ERROR 才写 accepted artifact。可重试 validation 最多两次、新 Attempt/feedback lineage，不改冻结基础输入。

## E. Stage Transition Gate

Core 结合 accepted diagnosis、validation、证据完整性、analysis requirements 和 abstention 决定。REJECT > WAIT_FOR_EVIDENCE > ABSTAIN > PROCEED；预检非 PROCEED 零 Provider 调用，阶段 gate 非 PROCEED 零 Stage2。Provider reservation 前再次验证正式 gate 和阶段绑定，不信模型自我放行。

## F. Stage 2

RESEARCH_RECOMMENDATION_V1 + 第二个正式模板，同一 ModelConfig/Evidence/Retrieval/cutoffs。新 STAGE_2_RECOMMENDATION Attempt 额外绑定 accepted diagnosis fingerprint。单一六层校验，不允许新事实来源，不把 diagnosis 当 deterministic FACT。allowlisted suggested_next_actions 只持久化建议，不创建草稿或执行任何交易动作。

## G. Provenance

Run 固定 case/model/template/政策/输入身份；Attempt 固定 stage、parent、retry codes、反馈/base/rendered fingerprints；调用发送前固定 request identity 和预算 reservation。submitted_request_fingerprint 与 resolved_analysis_input_fingerprint 分离，后者含实际双 cutoff、Pack/Retrieval、政策及上下文。

accepted diagnosis/recommendation 是有界 hash artifact；数据库保存 validation/attempt linkage，并约束匹配 accepted 校验与阶段。Trace 记录 Context/Evidence/Case、stage attempts/validation/gate/terminal；已完成校验后 crash 可幂等补 trace，不重发调用。stage binding 必须匹配同 Run 的有效执行 owner。

## H. Failure Semantics

- 已知 Provider 错误：FAILED，不自动 retry。
- 可能已派发但结果不可知：ABANDONED / PROVIDER_RESULT_UNKNOWN，不代表未执行。
- 可修复 schema/syntax：受六层 finding、每阶段两次上限及全 Run 预算约束。
- grounding/temporal/authority/immutable drift：不自动 retry，拒绝。
- Gate WAIT/ABSTAIN：合法研究 outcome；ABSTAIN 不伪装 FAILED。
- Stage2 failure/validation/budget：Stage1 accepted 保留。
- Cancel：未可能派发可安全取消；可能派发则 unknown 标记与保守 reservation 保留，晚响应不推进。
- usage NULL 是未知，0 仅明确报告零；未知费用不当作免费。

## I. Idempotency 与 Recovery

create 在 observation 前持久化 owner；并发同 key 只有一次 freeze；崩溃中断 key 保留失败，不静默重新观察。execute 同 key 不增加调用，新 key 不能绕过当前 owner/终态/gate。

显式 RESUME 仅继续下一阶段或补已持久化 candidate 的本地 validation/trace。STARTED crash 后 ABANDONED；显式 RETRY_UNKNOWN 新 key 创建新 Attempt，并保留旧未知预算。Core 的数据库级 OS 锁防止另一实例误恢复正在执行的 Run，异常退出自动解锁。

## J. Security

Core 不直接访问外部 Provider；Host 纯协议/credential 隔离保持。没有 generic tools、PAPER/LIVE/Risk/Capital/Broker/Gateway 写入或 raw completion proxy。静态边界测试覆盖 orchestration imports。

Core API 独立持久本地 token，创建即私有 Windows ACL、owner/format/链接检查；不安全文件不覆盖。Host 短期 token 不变，不共用 Gateway。loopback/Host/Origin/Bearer/strict JSON 均校验；CORS 不承担认证。credential availability 不访问上游、不声称认证/健康。

安全模型防网络暴露、误调用和跨普通账户访问，不声称防同 Windows 用户会话已失陷。Core startup/default-disabled/ACL failure/crash/重复实例/不同 run_directory 同 DB 均有专项回归。

## K. API

`POST /api/v1/ai/analyses`；`POST /{id}/execute`；`GET /{id}`；`POST /{id}/cancel`。strict schema 拒绝 credential、Provider URL、自由 messages/fields/tools/订单；错误稳定且不回显秘密输入。结果提供 accepted typed output、attempt/usage 和 provenance，不公开 raw/prompt/reasoning artifact 路径。

## L. Tests

历史参考：AI-3 后端 823、AI 295、前端 48；不作为本轮结果。

本轮 TDD 与独立专项覆盖：两阶段、Gate、schema retry、immutable drift、grounding/temporal/authority、预算、unknown、取消、并发 create/execute、恢复、API、Windows ACL、真实 localhost 双 HTTP（两种 output-token capability）、TEMP migration、append-only 与恢复 trace。各分片反复运行有重叠，不相加冒充唯一测试数。

最终完整脚本的非重叠分片结果：

| 分片 | 通过数 | 耗时 |
| --- | ---: | ---: |
| foundation | 22 | 34.04s |
| datasets-a | 70 | 101.76s |
| datasets-b | 87 | 342.28s |
| market-data | 107 | 219.53s |
| backtest | 41 | 107.81s |
| research | 32 | 191.03s |
| paper | 142 | 3264.59s |
| execution | 27 | 0.12s |
| ai | 450 | 584.58s |
| 后端合计 | 978 | 不重复累计专项 |
| 前端 | 48（10 文件） | 54.38s |

全部通过，无失败。AI 分片仅有 Starlette TestClient 对 httpx 的弃用提示；本轮未为消除提示安装或更换依赖。

## M. Validation

完整 `powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/test.ps1` 退出码 0，结尾为 `All backend and frontend checks passed.`。PowerShell common helper、全部后端分片、Ruff、mypy（140 source files）、前端测试、TypeScript 和 Vite production build 全部通过。mypy 仅保留既有 backtest 未注解函数体检查范围提示，无错误。`git diff --check` 与 staged diff-check 通过。

完整门禁启动前与结束后，backend/src、backend/tests、backend/alembic、scripts、frontend/src 按稳定路径排序的文件 SHA256 聚合摘要一致：`BDC92FBD1A663CBF443D2412BC5072E3D2389C4028B9F39FDC4802BE05209FF6`。运行期间未编辑代码或测试；后续只定稿文档。既有 0014–0016、前端源码和 scripts 未改动。

## N. Migration

唯一新增 head：20260911_0017，down_revision 20260910_0016。未修改 0014/0015/0016。

TEMP matrix：empty→head、0015→0016→0017、0016→0017、空兼容 0017→0016→0017；新历史存在则拒绝有损 downgrade。真实迁移库两阶段回归（非仅 Base.metadata）验证 terminal 原子提交、stage binding、accepted validation linkage、append-only。

## O. External Provider

OPTIONAL EXTERNAL VALIDATION NOT RUN。没有自动互联网、真实 API key、计费 Provider、SDK 安装或真实投资数据发送。

## P. Deferred

Conversation、AI UI、Streaming、Embedding、Incremental Thesis、Draft side effects、Autonomous tools、PAPER/LIVE 写入。US 研究依赖 Phase 6B，当前不伪造 foundation。AI-5 及以后未进入。

## Q. Remaining AI-4 Issues

此前三个已证实阻塞均已修复并专项验证：知识截止冲突、PAPER 来源混用、migration terminal autoflush。冻结协议与编排、PAPER 来源关系、本地访问安全的独立合同和质量审查均通过；缺失 artifact 的安全终止与精确只读 import 例外也已通过增量复核。完整脚本通过，没有未关闭的 AI-4 必修问题。真实 Provider smoke 未执行，是已批准的可选人工验证项，不伪装为自动化验收结果。

## R. Final Status

AI-4 TWO-STAGE RESEARCH COPILOT STABLE

READY FOR AI-5 RESEARCH MEMORY & THESIS

这里的 READY 仅表示 AI-4 交付条件成立，不构成 AI-5 实施授权。本轮停止，未进入 AI-5；没有 push、真实 Provider smoke 或交易写入。
