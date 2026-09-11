# AI-4 历史暂停审计与交接

日期：2026-09-11。本文是未完成状态记录，不是成功验收报告。

后续用户已批准 SERVER_FROZEN_CURRENT 十项冻结语义，本文所记暂停点已恢复实施。以下保留当时实际问题与测试记录，不代表当前进度；当前状态见 `docs/ai-4-research-acceptance.md`。

## A. Git

- 分支：dev。
- 本轮开始与暂停 HEAD：4d1ca8e21d23e41c106eb344a04554b7580b1735。
- 本轮提交：0；工作树包含本轮未提交代码、测试与文档，不是 clean。
- 本地 origin/dev 引用比较：behind 0 / ahead 9；未 fetch，不代表远端实时状态。
- 未 push、merge、rebase、reset、amend、新建分支或 worktree。

## B. Analysis Contract

已实现统一请求、四种 analysis_type、版本化两阶段 envelope、独立 lifecycle/outcome/progress、create/execute 幂等及 epoch。合同已做专项审查，但整体尚未验收。

## C. Context 与 Evidence

已接入正式 Resolver、EvidencePack、ResearchCase memory 回溯与 RetrievalSnapshot。存在阻塞：真实实验/比较 Resolver 的 known_at 使用本次观察时钟，而客户端 knowledge_cutoff 在此之前已冻结，正常 CURRENT_RESEARCH 被 FUTURE_KNOWLEDGE 拒绝。

证据：`backend/src/quant_lab/ai/source_resolvers.py` 的 research_experiment/research_comparison 明确以 max(clock(), updated_at, link.created_at, run.completed_at) 定义 known_at。`analysis_context.py` 随后按请求原 cutoff 校验。这不是允许回填 created_at/known_at 的理由。

建议待确认协议：仅 CURRENT_RESEARCH 允许显式选择服务端冻结 knowledge_cutoff；Core 先持久化有真实观察时间的不可变来源投影，再生成并冻结 resolved cutoff/context。submitted request fingerprint 与 resolved analysis input fingerprint 分别记录；create 同 key 重放必须返回首次已冻结结果，不能重新观察。显式传入 cutoff 及 HISTORICAL_REPLAY 保持原值，不能偷偷扩大。market_data_cutoff 不因此改变。Stage2、retry、resume 均只能使用同一已冻结结果。

该建议改变请求/持久化时间合同，尚未实施，等待用户确认。不能让用户填写未来 cutoff 作为规避方案。

## D. Stage 1

已实现 diagnosis、正式模板、Host 调用、单一六层校验、有界反馈与新 Attempt retry。尚未完成最终集成验收。

## E. Stage Transition Gate

Core 使用 REJECT > WAIT_FOR_EVIDENCE > ABSTAIN > PROCEED；已加入 dispatch 前独立 gate 检查，非 PROCEED 不派发 Stage2。需随最终修复再回归。

## F. Stage 2

已实现 recommendation、绑定 accepted diagnosis identity、同一校验链与研究动作 allowlist；不执行 draft 或交易副作用。

## G. Provenance

已实现 stage/lineage、base/rendered fingerprints、accepted artifact、epoch、预算和 trace。待补验：恢复时 validation trace 的幂等补齐、stage binding 数据库跨 Run/epoch 关系约束及 gate 内容 fingerprint 完整绑定。

## H. Failure Semantics

已实现已知 Provider failure、ABANDONED/unknown 保守预算、stage1 保留、budget 短路及取消后晚响应不推进。取消不代表上游未执行。真实数据库终态更新仍有回归问题，见 Q。

## I. Idempotency / Recovery

已加入单 owner、同 key 冲突、显式 RESUME/RETRY_UNKNOWN、已完成 candidate 仅本地补校验。创建相同 fingerprint 输入的并发竞争已修并定向测试，但修后完整 AI 分片未重跑。Core 本地授权 token 在 crash 遗留后的安全恢复仍需修复和真实应用启动测试。

## J. Security

已实现严格 JSON、独立本地授权和来源检查；Host availability 不访问上游，不声称健康或认证成功。尚需补齐 AI-4 静态 import boundary 和完整 create_app 启动/ACL 失败回归。未新增 PAPER/LIVE/Risk/Capital/Broker/Gateway 写入或真实 Provider 自动调用。

## K. API

已实现 `/api/v1/ai/analyses` 创建及按 id 的 execute/get/cancel，响应不公开 raw prompt/reasoning。CURRENT_RESEARCH cutoff 协议修订待批准。

## L. Tests

本轮有合同、availability、context、编排、API、migration 与本地双 HTTP 专项测试记录。不是最终整树结果，不将各次重叠测试数量相加。

最近独立集成审查小范围检查：42 passed，1 failed；失败为 `test_two_stage_runs_against_migrated_database_triggers`。此前 AI 分片为 246 passed，1 failed（相同 fingerprint 输入并发创建）；修复后仅定向并发回归通过，未重跑完整分片。

## M. Validation

Ruff 源码及根目录标准 mypy 检查曾通过，后续有代码修改，因此不代表最终版本全绿。新增测试尚需统一格式与完整检查。Frontend、TypeScript、Vite 和最终 `scripts/test.ps1` 尚未在本轮完成；没有完整门禁成功结果。

## N. Migration

新增未提交 forward revision：20260911_0017，接 20260910_0016。0014–0016 未修改。TEMP matrix 已有专项覆盖，但最近真实 migration trigger 集成回归失败，不能宣称迁移验收完成。

## O. External Provider

OPTIONAL EXTERNAL VALIDATION NOT RUN。测试使用本地 Fake 与 localhost upstream，没有真实计费 Provider 调用。

## P. Deferred

Conversation、AI UI、Streaming、Embedding、Incremental Thesis、Draft side effects、Autonomous tools、PAPER/LIVE writes；未进入 AI-5。

## Q. Remaining AI-4 Issues

1. 需用户决策：CURRENT_RESEARCH 观察时间与冻结 cutoff 的协议冲突，见 C；不得绕过 AI-2 时间规则。
2. 普通必修：PAPER_REVIEW 必须核验选定 snapshot/risk 与目标 session/account 的关联。审查已复现 ps2/pa2 搭配 ps1/pa1 snapshot 仍 PROCEED，当前仅同市场校验不足。
3. 普通必修：analysis_repository.checkpoint 将 progress 写成 TERMINAL 后，查询 STARTED attempts 触发 autoflush，再清 active_epoch_id，触发 0017 的 `AI analysis is terminal`。必须调整原子更新顺序并在真实 migration DB 回归，不能只依赖 Base.metadata 测试。
4. 完成 G/I/J 的持久化、安全与恢复补验，复核来源关联，不修改历史事实身份。
5. 规格通过后完成集成质量审查；同步 ADR-0003、总架构旧 retry/restart 描述及 operations。
6. 全部修复后冻结代码，运行完整 scripts/test.ps1，记录实际结果，再执行获授权的最多约 3 个普通本地提交并确认 clean。

## R. Final Status

NOT READY — 实验复盘的知识截止冻结协议待确认，且尚有来源关联、真实迁移终态更新及完整验收未关闭。

暂停修改冻结语义，不进入 AI-5，不将未通过验收的工作提交为完成版本。
