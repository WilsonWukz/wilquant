# AI-4 两阶段研究分析操作说明

当前功能只提供研究 API，没有聊天或前端页面。AI-4 本地完整门禁与合同审查已通过，证据见 docs/ai-4-research-acceptance.md。真实 Provider smoke 尚未执行，仍需单独人工确认，不由本次自动化验收代替。

## 启用与授权

默认 `QUANT_LAB_AI_ANALYSIS_ENABLED=false`。显式启用后，Core 使用独立 `.run/ai-analysis-access/token`（相对于配置的 run_directory），创建时即限制当前 Windows 用户 ACL，并校验 owner/内容格式。安全的既有 Core token 会跨重启保留；不安全或损坏文件失败关闭，不自动覆盖、修 ACL 或明文降级。它不是 Provider credential。

同一 canonical SQLite 文件旁的 `.<数据库文件名>.ai-analysis.lock` 是无秘密、非阻塞 OS 所有权锁。不同 run_directory 但同一数据库也不能同时执行 AI-4 recovery；进程退出/崩溃自动释放锁。AI 关闭或拿锁失败不会执行 AI-4 恢复，旧 AI-1/3 恢复保持原合同。其他业务不因 AI 授权失败而不可用。

Host URL 通过 `QUANT_LAB_AI_PROVIDER_HOST_URL` 配置，默认 `http://127.0.0.1:8011`；Host token 路径通过 `QUANT_LAB_AI_PROVIDER_HOST_TOKEN_PATH` 配置。Core 不替 Host 创建 secret，也不读取 Provider Credential Manager key；启动独立 Host 的人工步骤沿用 [AI-3 操作说明](ai-3-provider-operations.md)。Host 短期 token、Core 持久本地 token、Gateway 授权完全分离。

安全边界为防网络暴露、误调用、跨普通 Windows 账户访问；不防已控制同一 Windows 用户会话的恶意进程。仅本机 loopback peer 与合法 Host；Origin 存在时必须在明确允许集合中。CORS 不是认证。令牌不要进入日志、截图、版本库或分析请求正文。

## 配置前置条件

需要已发布的 ModelConfigVersion，包括正确的冻结 EndpointProfile/capability、Host matching profile、预算及输出上界；全 Run 共用预算，不会为了两阶段提高 max_calls。若 max_calls=1，Stage1 之后 Stage2 会预算短路，这不是模型路由。

两个正式 PromptTemplateVersion 由 `quant_lab.ai.analysis_prompts.publish_analysis_prompts(PromptTemplateVersionService(repository))` 幂等发布，返回 Stage1/Stage2 对象及 id。当前无公共 Prompt/Model 配置写 API；本地受信配置工具通过既有版本服务发布，然后在研究请求中引用这两个 id，不能用自定义系统 Prompt 代替。create 会再次校验正式模板身份。

## API 请求

所有分析路由都需 `Authorization: Bearer <Core local token>`；POST 必须 `Content-Type: application/json`。不接受任意 source/field list、Provider URL、credential、messages、tools、SQL 或订单字段；额外字段拒绝，body 有界。

1. `POST /api/v1/ai/analyses`：正文 `{ "idempotency_key": "create-唯一键", "request": { ... } }`。冻结上下文，不调用 Provider。
2. `POST /api/v1/ai/analyses/{id}/execute`：正文 `{ "idempotency_key": "execute-唯一键", "intent": "INITIAL" }`。唯一显式模型派发入口。
3. `GET /api/v1/ai/analyses/{id}`：安全结果、stage/outcome、attempt、usage 和 provenance identities，不返回 raw/prompt/reasoning。
4. `POST /api/v1/ai/analyses/{id}/cancel`：正文 `{}`，终止后续编排，不证明上游没有执行。

analysis_type 为 MARKET_DIAGNOSIS、STRATEGY_REVIEW、EXPERIMENT_REVIEW、PAPER_REVIEW。引用正式领域 id；PAPER snapshot/risk 必须属于目标 session/account。当前 US foundation 未实现，明确拒绝，不伪造 US 数据链路。MARKET_DIAGNOSIS 缺确定性市场指标时 WAIT，不让模型补趋势。

### 时间模式

- EXPLICIT（默认）：必须传 aware `knowledge_cutoff`，CURRENT_RESEARCH 和 HISTORICAL_REPLAY 都原值处理。
- SERVER_FROZEN_CURRENT：仅 CURRENT_RESEARCH，省略或传 null `knowledge_cutoff`，不接受客户端 resolved cutoff。Core 先持久化 create identity/owner，再持久化观察投影，之后生成服务器 UTC cutoff。响应 provenance 返回实际 resolved cutoff 及 submitted/resolved 两种 fingerprints。
- market_data_cutoff 始终来自原请求；effective_at 超出它仍被拒绝。known_at 不回填。
- 相同 create key/相同 payload 返回首次冻结结果，不重新观察；不同 payload 返回 409。冻结中相同请求最多等待 30 秒再返回 ANALYSIS_IN_PROGRESS，可查询/重放同 key；不要自动换 key。
- 观察失败或进程中断后，该 create key 保留失败记录，不会偷偷重新观察。确需新分析时使用新 create key。

## 重试、恢复和费用

同步 execute 使用 AI-3 分阶段 HTTP timeout 和有界请求/响应；不宣称严格总 wall-clock 截止时间。HTTP 客户端断开不能当作取消或上游未执行证明。可通过独立 cancel 请求终止后续编排。

六层全部无 ERROR 才 accepted。可修复 schema/syntax 由同一校验政策决定，每阶段最多两次 validation retry，新 Attempt、新反馈，原 Evidence/Retrieval/Model/cutoffs 不变。grounding、temporal、authority、immutable drift 不自动 retry；Provider 明确失败同样不自动 retry。

已持久化 completed candidate、但校验/trace/checkpoint 未完成时，restart 后显式 `RESUME` + 新 execute key 只补本地步骤；已 accepted Stage1 不重做，未派发 Stage2 可以继续。两阶段始终复用首次 resolved input，不重新读取 Experiment/Comparison。

旧 STARTED 或可能发送后失去结果的 Attempt 为 ABANDONED / PROVIDER_RESULT_UNKNOWN。必须明确 `RETRY_UNKNOWN` + 新 execute key 才能追加调用，旧 Attempt 和 reservation 保留。NULL usage 是未知，不等于 0；缺 usage 不等于免费。

取消前若尚未可能派发，Run CANCELLED；若已可能发送，Run outcome CANCELLED 且 provider_result_unknown=true，Attempt ABANDONED，预算不归零。晚到响应不能推进 Stage2 或重开终态。

Host availability 仅返回 host_ready、profile_valid、credential_store_accessible、credential_available 及配置 identity。它不能证明 API key 有效、quota、endpoint/model 可用，不会产生 health completion 费用。

## 排错与验收

稳定错误码包括 IDEMPOTENCY_KEY_CONFLICT、ANALYSIS_IN_PROGRESS、ANALYSIS_CONTEXT_INTERRUPTED、PROVIDER_UNKNOWN_CONFIRMATION_REQUIRED、ANALYSIS_PAPER_SOURCE_RELATIONSHIP_INVALID、AI_HOST_CREDENTIAL_UNAVAILABLE。先读取安全结果与本地 provenance，再决定人工操作；不要删除历史数据库行或改写 cutoff 来解锁。

0017 仅接续 0016；含新历史时拒绝有损 downgrade。备份应包含 SQLite 与被引用的有界 artifacts，单独恢复数据库而丢失 artifact 会导致完整性失败。Prompt、投影和 accepted artifact 含研究信息，默认保存在本地，不记录完整 Prompt 到日志。

最终验收执行 `powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/test.ps1`。自动测试只用 Fake/localhost upstream；真实 Provider smoke 仅后续人工确认且先用合成证据，当前 OPTIONAL EXTERNAL VALIDATION NOT RUN。停止 AI-5 前。
