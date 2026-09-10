# AI-3 Provider Isolation 实施计划

> 使用 superpowers:subagent-driven-development 处理独立子任务；主线程负责 Core 接线与总体验收。用户已批准直接实施，无额外审阅停点；不新建 branch/worktree。

**目标：** 安全、可审计、可离线验收的独立 Provider Host，不进入 AI-4。

**架构：** Core 与 Host 仅共享纯 DTO；Host 管 key/HTTP，Core 管 provenance/budget/artifact。保留现有 run/attempt 状态与 AI-2 验证边界。

**技术：** Python、Pydantic、httpx、FastAPI/uvicorn、SQLAlchemy/Alembic、Windows ctypes、pytest、PowerShell。

## 任务 1：协议、Host 与凭证

- [x] 新增 `backend/tests/ai/test_provider_host.py`，先验证缺失模块失败，再实现 `backend/src/quant_lab/ai_provider_protocol/`、`backend/src/quant_lab/ai_provider_host/`。
- [x] DTO 使用 extra=forbid、UTC timestamp、bounded text/messages，capability 明确；未知 usage 保持 None。
- [x] Host auth/rotation/replay，Credential Manager wrapper + Memory store，ACL 创建即限制与验证；Fake 和 OpenAI-compatible adapters。
- [x] 执行 `backend/.venv/Scripts/python.exe -m pytest backend/tests/ai/test_provider_host.py -q`，检查 exit 0；补不同 token 参数和真实 socket upstream。
- [x] 独立需求符合性审查后，再做代码质量审查并修复。

## 任务 2：nullable usage 与 durable dispatch

- [x] `backend/tests/ai/test_provider_execution.py` 先断言 `AIUsageInput(None,None,None,None,None,None,"USD",True)` 可保留未知；旧实现应失败。
- [x] 修改 `ai/persistence.py`、`ai/provenance.py`；新增 `backend/alembic/versions/20260910_0016_ai_provider_execution.py`。四 token 字段 nullable，不回写旧历史；保留 append-only triggers。
- [x] 新增 `ai/provider_execution.py` 与独立 Core localhost client：request identity/reservation 在网络前 commit；已有身份拒绝二次发送；known failure→FAILED，unknown→ABANDONED。
- [x] 使用 TEMP SQLite 跑 `empty→head`、`0014→0015→0016`、`0015→0016`、`0016→0015→0016`；新增 NULL 数据的无损降级拒绝测试。

## 任务 3：成本、artifact、端到端与进程

- [x] 为 over budget/unknown price/concurrent reservation/timeout recovery 写失败测试；实现 Decimal 保守预算、80% warning、unknown 不释放。
- [x] 为 raw/reasoning/key 泄露写失败测试；实现 bounded atomic artifact 和哈希，candidate 与 accepted 分离。
- [x] 新增独立 Host 启停/credential/manual smoke 入口；验证 PID ownership、duplicate start、token rotation，普通 Core readiness 不依赖 Host。
- [x] 在 `backend/tests/ai/test_provider_e2e.py` 真实两层 localhost HTTP 验证 Core→Host→upstream→Core，并确认没有 ValidationResult acceptance。

## 任务 4：收口

- [x] 同步 architecture spec、ADR-0003、roadmap 和 AI-3 acceptance；README 只放必要用户入口。
- [x] 运行 AI 专项、Ruff、mypy；修复后串行运行 `powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/test.ps1`，期间不改可执行文件。
- [x] 记录真实 counts/exit codes/matrix/未运行外部 smoke，不沿用 AI-2 测试结果冒充本轮。
- [x] `git diff --check` 后本地正常提交（目标不超过 3 个），不 push/amend/rebase/reset；复核 HEAD/ahead/clean。未全部通过不得声明 STABLE。
