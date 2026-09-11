# AI-4 两阶段研究分析实施计划

> 2026-09-11 完成：用户批准的 SERVER_FROZEN_CURRENT 十项冻结语义及 AI-4 全部必修项已实现、独立审查并通过完整门禁。原暂停记录作为历史保留；当前验收证据见 docs/ai-4-research-acceptance.md。停止在 AI-5 之前。

## 已批准的合同闭合增量

- [x] 显式 cutoff 与服务端冻结模式；submitted/resolved fingerprints 分离。
- [x] 持久化 create key 与唯一观察 owner；持久化不可变投影后生成 UTC cutoff，再冻结分析输入。同 key 重放不观察，中断 key 不自动重取证。
- [x] 时间协议专项回归、PAPER session/account/risk 关系对抗、真实 migration 终态原子更新。
- [x] G/I/J 恢复补验、跨 Run binding、validation trace、独立授权 crash 恢复和静态依赖边界。

> 执行技能：superpowers:subagent-driven-development；TDD；用户已授权直接实施，不新建 branch/worktree，不逐项询问。主线程负责持久化、Context/API 集成及总体验收。

**目标：** 在既有 Run/Attempt/Usage 及 AI-2/3 上完成严格串行两阶段研究分析，停止 AI-5。

**架构：** 版本化统一合同与单一 ValidationService；Core 冻结上下文及控制阶段/预算，Host 只调用 Provider。0017 持久化幂等、阶段与 retry lineage。

**技术：** Python/Pydantic、SQLite/SQLAlchemy/Alembic、FastAPI、现有 httpx Host、pytest、PowerShell。

## 1. 合同与统一校验

- [x] 新增 tests/ai/test_analysis_contracts.py：先断言 analysis_contracts 存在失败，再验证严格请求/版本化 diagnosis/recommendation、禁交易、retry反馈只含safe codes/paths。
- [x] 新建 ai/analysis_contracts.py、ai/analysis_prompts.py；扩展 ai/validation.py 的显式 stage contract 参数，默认保持 AI-2 v2；完整 schema失败不得接受部分claims。
- [x] 命令 `backend/.venv/Scripts/python.exe -m pytest backend/tests/ai/test_analysis_contracts.py backend/tests/ai/test_ai2_validation.py -q -p no:cacheprovider`，退出0后独立需求/质量审查。

## 2. 持久化与原子执行

- [x] tests/ai/test_analysis_persistence.py 先检验缺失的 stage/lineage、同key冲突与并发owner；失败后新增 ai/analysis_persistence.py、ai/analysis_repository.py 及 20260911_0017_ai_two_stage_analysis.py。
- [x] 扩展 ai/persistence.py 的 Attempt不可变字段，run identity不覆盖；新增stage binding、analysis record、execution epoch，SQLite BEGIN IMMEDIATE 实现唯一owner，accepted只写artifact引用。
- [x] 同分片覆盖append-only、legacy兼容、TEMP migration matrix与有损downgrade拒绝，逐步运行到退出0。

## 3. Context 与 Prompt

- [x] tests/ai/test_analysis_context.py 使用真实 Dataset/Strategy/Backtest/Experiment 和 Resolver，先验证缺失模块失败；新增 ai/analysis_context.py。
- [x] 固定四种来源政策、双cutoff、freshness、案例bounded projection；测试空案例可选、未来案例拒绝、未支持市场/缺指标短路、无自由fieldpaths。
- [x] Prompt服务端正式发布，冻结两个template和contract；artifact分区、秘密检查、相同inputs相同base fingerprint，反馈导致rendered改变。

## 4. 两阶段执行与安全

- [x] tests/ai/test_analysis_orchestration.py 先用序列Fake覆盖两次调用/两条校验链/一Run，失败后新建 ai/analysis_service.py、ai/analysis_execution.py。
- [x] 接入AIProviderExecutionService的attempt级binding；gate非PROCEED零Stage2、bounded retry、各类nonretryable、同Run预算、保留Stage1、cancel和late response拒绝推进。
- [x] Host协议/实现和client增加credential availability接口，先写 test_provider_availability.py；只报告可用性，不联网认证。
- [x] 重启区分AI-4绑定run与legacyrun；已完成candidate只重做本地校验，旧STARTED abandoned；显式epoch续跑不重做Stage1。

## 5. API与验收

- [x] tests/ai/test_analysis_api.py 先断言创建/execute/get/cancel路由不存在，再在api/ai_analyses.py与main.py接线；严格schema、安全来源与本地授权，safe response，不返回raw/prompt/reasoning。
- [x] E2E走Fake Host与双HTTP，幂等并发、预算、取消、restart、provenance重建及静态无交易/直接上游HTTP测试。
- [x] 独立规格审查再质量审查，修复所有必修项。运行AI分片、Ruff、mypy。
- [x] 同步ADR/架构历史说明与新设计/验收报告，不改写旧阶段事实。
- [x] 冻结代码后串行 `powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/test.ps1`：exit 0；后端978（AI450）、前端48/10文件、Ruff/mypy/TypeScript/Vite通过；外部smoke未运行。源码聚合摘要前后一致。
- [x] `git diff --check` 与 staged diff-check 通过，采用两批正常本地提交（实现/测试 + 本文档），不push/amend/rebase/reset；完整A–R中文验收报告已定稿。最终文档提交后的clean/ahead复核在交付消息记录。
