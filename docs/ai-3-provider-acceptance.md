# AI-3 Provider 隔离验收记录

状态：AI-3 实现及完整自动验收通过。`AI-3 ISOLATED PROVIDER HOST STABLE`；`READY FOR AI-4 TWO-STAGE RESEARCH COPILOT` 仅表示后续阶段可启动，本轮停止、不实施 AI-4。

## A. Git 与执行对象

- 分支 dev；开始 HEAD `4a9f9aeff38d38bcec13865da6eb1b2fc4d7d2f8`，起点工作树干净。
- 起点相对本地 origin/dev tracking ref ahead 8、behind 0，未 fetch。
- 本轮不 push、amend、rebase、reset、merge，不新建 branch/worktree。
- 交付采用本地正常提交；提交号及提交后的 clean-tree / ahead 复核随最终交付报告记录，不写入自引用提交号。

## B–D. 进程、认证与凭证

Core 与独立 Host 共享纯 `ai_provider_protocol`，不共享 DB、Repository、secret namespace 或交易权限。Host CLI 永远绑定 127.0.0.1，默认端口 8011；普通 dev/readiness 不依赖它。

token 使用 32 随机字节，启动旋转，Bearer 恒时校验。专用目录和文件从创建时带 current-user-only protected ACL，并读回验证；失败清理需 CreateNew 回执与本次随机 token 匹配，不能误删已有 token。协议 1；timestamp ±30 秒；ID 原子保留至少 60 秒，重复与缓存满均拒绝。

Provider key 仅 Host 通过 Windows Credential Manager ctypes wrapper 读取。测试使用 MemorySecretStore/native boundary stub，不读取用户真实 key。DPAPI 与 plaintext fallback 不存在。日志、raw、输出、错误经过脱敏；配置只有 credential_ref。

## E–G. 协议与 adapters

- Request：固定 ID、UTC 时间、profile/endpoint fingerprint、model、文本 messages、输出上限、显式 capability 参数。tools/functions、多模态、streaming 均拒绝。
- Result：安全 normalized content、model identity、response ID、finish reason、usage、latency；raw 是有界去 reasoning 的安全投影。
- Usage：prompt/cached/completion/total/reasoning 可为 NULL；不执行 missing→0。
- `OpenAI-compatible` 是共同协议族，不代表 OpenAI 行为完全相同。参数由 capability 驱动，测试覆盖 max_tokens 与 max_completion_tokens；不猜厂商，不重试 400，不自动切换。
- httpx 四类 timeout、无 retry、无 redirects、无环境 proxy。批准公网 endpoint 解析后校验所有 IP，并 pin IP/保留 Host 与 TLS SNI；HTTP 仅显式本地测试。
- FakeProvider 支持确定性 content、reasoning、usage、finish_reason、latency 和 timeout/429/500/malformed 场景。

## H–K. Core、预算、失败与安全

复用 AIAnalysisRun/Attempt/Usage 和 ModelConfigVersion；新增的是一对一不可变 `ai_provider_call_bindings`，不是第二套 run。绑定 request/config/prompt/evidence/gate fingerprints、policy 和 reservation，SQLite BEGIN IMMEDIATE 在发送前提交，重复 attempt 拒绝。typed 配置将浮点参数规范为可审计 decimal 文本，wire 投影由协议层显式完成。

STARTED 进入三个互斥终态：COMPLETED、FAILED、ABANDONED。明确失败为 FAILED；可能已发送后未知为 ABANDONED / PROVIDER_RESULT_UNKNOWN，不代表未执行。重启扫描所有 STARTED，包括终态 run 下的 attempt；保留 terminal run，不重放，原子补记未知 Usage。

预算包含输出/输入边界、per-run calls、nullable cost hard limit、80% warning。调用前预留配置输入/输出上界费用；成功用量可计价则结算，缺失/未知用量仍 NULL，保留 reservation。无价格且有金额 hard limit 时 fail closed。独立审查以文件 SQLite 双线程验证 max_calls=1 时仅一次调用。

Core 再次执行冻结的 message/chars/response/reasoning/raw 上限，client 使用冻结 timeout。candidate/raw 以原子文件和 SHA256 保存；candidate 不是 accepted output，不产生 ValidationResult acceptance。reasoning 默认不保留，debug retention 暂不开放。没有 public completion API、Provider fallback、工具调用或 PAPER/LIVE/Risk/Capital mutation。

## L. 端到端与进程

- FakeProvider：真实 localhost Host 链路通过，未访问外网。
- OpenAI-compatible：Core→Host→本地 HTTP upstream 两层 socket 链路，两种 token 参数均通过。
- Windows 进程：start/health/duplicate start/PID 所有权篡改拒绝/stop/restart token rotation 通过。修正公共脚本覆盖 RuntimeRoot、Path/PATH 大小写及虚拟环境父子启动器问题；只结束已核实本轮进程。同 RuntimeRoot 操作使用独占文件句柄串行化，无归属预存 token 拒绝且保留；相关 4 项 Windows 回归通过。
- 人工 smoke：显式确认参数、固定极小提示、全新独立审计库；显式覆盖 SQLite 路径，迁移与 repository 使用同一审计库，不继承主库绝对路径。自动测试覆盖环境变量 / `.env` 外部路径隔离、拒绝未确认及 Fake 链路。真实 Provider 为 `OPTIONAL EXTERNAL VALIDATION NOT RUN`。

## M–N. 测试与正式门禁

AI-2 历史基线是后端 734 / AI 206、前端 48。本轮最终冻结版本完整门禁：**后端 823 passed（AI 295，新增 89）**、前端 **10 文件 / 48 passed**。AI 分片 143.48 秒；不是沿用历史结论。

Ruff 全部通过；mypy 126 文件通过。uv lock --check --offline 使用专用 cache 后通过，44 packages，不联网、不升级依赖。httpx 从已有 dev 依赖提升为 runtime 依赖，无厂商 SDK。

正式 `powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/test.ps1` 退出码 **0**，末行 `All backend and frontend checks passed.`。PowerShell common helpers、Ruff、mypy 126 文件、TypeScript/Vite production build 均通过。

| 后端分片 | passed |
| --- | ---: |
| foundation | 22 |
| datasets-a | 70 |
| datasets-b | 87 |
| market-data | 107 |
| backtest | 41 |
| research | 32 |
| paper | 142 |
| execution | 27 |
| ai | 295 |
| 总计 | 823 |

最终全门禁运行期间没有修改代码、测试、配置或 migration。独立审查发现的 smoke 继承主库路径及脚本失败误删预存 token 两项 Important 均已按 TDD 修复，并包含在上述最终门禁中；没有未关闭的必修审查项。

非失败提示：现有 backtest/service.py:230 annotation-unchecked note；Starlette testclient 的 httpx 弃用提示，不为本轮安装 httpx2；普通 Git 全局 ignore/CRLF 提示。混合沙箱权限的历史 TEMP 私有 ACL 目录曾引起 pytest 清理提示，Windows 专项与正式门禁使用可验证真实用户权限的执行环境。

## O. Migration

head `20260910_0016`，线性接 0015；0014/0015 未修改。TEMP SQLite 验证 empty→head、0014→0015→0016、0015→0016、空数据 0016→0015→0016，nullable usage 与新 binding append-only。已有未知 usage/binding 时拒绝有损 downgrade，不填零或删除 provenance。

## P–S. 文档、延期和完成条件

更新 architecture、ADR-0003、路线图 spec、README 最小配置入口；新增 AI-3 design、implementation plan、运维与本验收记录。设计与自审固定 ABANDONED、nullable usage、预算 reservation、纯协议依赖方向和 explicit capability。

Deferred：Two-stage Copilot、ResearchRecommendation、Conversation、AI UI、Streaming、Embedding、Autonomous tools、PAPER/LIVE writes、debug reasoning retention、raw 删除 API/UI、DPAPI、周期预算。它们不是本轮未实现的 AI-3 必需功能。

AI-3 必需设计、实现与自动验收项已完成。外部真实 Provider smoke 保留为可选人工验证，不宣称任何真实端点已验证。停止在 AI-4 之前。
