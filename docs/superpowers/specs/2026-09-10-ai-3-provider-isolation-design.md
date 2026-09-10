# AI-3 隔离 Provider Host 设计

状态：已获用户批准并实施，最终完整门禁通过；验收证据见 `docs/ai-3-provider-acceptance.md`。停止在 AI-4 之前。

## 范围与依赖

本设计落实 2026-09-10 AI-3 附件及后续四项确认。Core → `ai_provider_protocol` ← Provider Host；共享协议只依赖 stdlib/Pydantic，不引用既有 `ai.contracts` 的 ORM 链。Host 独立进程，默认禁用，绑定 127.0.0.1:8011，只有 internal/v1 health、capabilities、complete。Core 不公开 completion API。

Host 不加载数据库、Repository、EvidenceResolver、ResearchCase、PAPER、LIVE、Broker 或 ExecutionGateway。该隔离是代码、凭证和进程职责边界，不冒称同 Windows 用户下的 OS 沙箱。127.0.0.1 + 用户 ACL + Credential Manager 防网络暴露、误调用、跨普通账户访问及 Core/UI/log 泄露，不抵御已控制同一 Windows 用户会话的恶意进程。

## 协议与能力

协议版本 1，冻结请求 ID、UTC timestamp、model、纯文本 messages、输出上限、temperature、reasoning、response_format、credential_ref 和明确允许的配置。禁止 tool/function、streaming、多模态与任意 JSON 透传。Host 自己持有批准 endpoint 配置；请求不能指定任意 URL。规范化 endpoint、capability、model、非密钥配置参与指纹；Core 与 Host 配置不一致拒绝。

“OpenAI-compatible”表示共同协议族，而不是行为完全等同于 OpenAI。具体 request/response capability 必须被显式声明、冻结和测试。输出参数由 `max_tokens` / `max_completion_tokens` capability 选择，reasoning 由 `reasoning_effort` / `thinking` / unsupported 选择；usage 和 reasoning 提取路径受限。能力不支持就不发送，不因 400 猜参数或切换 Provider。官方 Chat Completions 的 max_completion_tokens 包含可见输出及 reasoning tokens，这不是所有兼容端点的共同保证。

参考：[OpenAI Chat Completions 协议](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create)。使用 httpx，明确四种 timeout、无 retry、无 redirect、禁用环境代理；真实 endpoint 仅批准的 HTTPS 公网地址，HTTP 仅显式本地测试。禁止 URL userinfo、query、fragment、私网/metadata endpoint 和不受控重定向。

## 身份、认证、密钥

每次启动生成 256-bit CSPRNG Bearer token；在受限目录创建时应用 current-user-only ACL，并验证后才服务。ACL 失败即停止，关闭时清理本进程 token。每次启动旋转，恒定时间比较。请求 clock skew 30 秒，重复 ID 原子保留并拒绝；缓存 TTL 覆盖未来时间偏差窗口，容量满也拒绝，不能通过淘汰仍有效 ID 重放。

Provider key 只由 Host 从 Windows Credential Manager 读取，namespace `wilquant.ai.`；Core 仅 credential_ref。本地配置 CLI 使用隐藏输入，不允许 key argv。自动测试用 MemorySecretStore/native wrapper，不碰用户真实 credential。DPAPI fallback 暂缓，Credential Manager 不可用 fail closed，无明文 fallback。

## Core 持久化与状态

继续使用 ModelConfigVersion、AIAnalysisRun、AIAnalysisAttempt、AIUsageLedger、Trace。不要新增 ProviderRun/ProfileVersion。一次 attempt 一次 invocation；host_request_id 使用 attempt ID，upstream response ID 独立保存。调用前验证 immutable run/config/prompt/evidence 指纹和已批准的 gate context；这不是 gate orchestration。发送前在一个 SQLite 写事务里冻结调用 metadata、request 指纹和预算 reservation，重复 dispatch 拒绝。避免持有事务等待网络。

`STARTED` 只能进入三个终态：COMPLETED、FAILED、ABANDONED，而不是串行穿越终态。明确 HTTP 401/429/5xx/invalid response 是 FAILED；请求可能已发送后的超时、连接丢失、Core crash 和重启旧 STARTED 是 ABANDONED / PROVIDER_RESULT_UNKNOWN。ABANDONED 不意味着未执行。恢复不重放，后续重试必须新 attempt、新 ID。

0016 线性接在 0015 后：usage token nullable，必要调用元数据与预算绑定采用既有 attempt/trace 的明确持久化结构。不改旧 migration。0 是明确报告零，NULL 是未知；旧历史不回填未知为零。降级无法表达新 NULL 数据时必须拒绝无损降级，不偷偷填零；空库及可兼容数据矩阵可回滚再升级。append-only 与 terminal triggers 保持。

## 预算与结果

Core preflight 限制请求字节/messages/字符、输入上界、输出 tokens、run calls；按冻结价格与最保守输入/输出上界预留，80% soft warning。事务内累计预算防并发越限。配置金额 hard budget 而无法估价则禁止调用；无金额 hard budget 仍限制 calls/tokens，cost 为 UNKNOWN。

成功且用量可计算则实际结算；缺失用量仍 NULL，未知结果保持保守 reservation/consumption，绝不释放成免费调用。明确 pricing/max bounds 的不确定调用持续占用上界；不实现周期预算 scheduler。

Host 对实际 key/token、secret keys、错误内容统一脱敏后返回。Core 二次脱敏，raw 独立 artifact 有界、原子写入、相对安全路径、SHA256；normalized candidate 持久化但不是 accepted output。Reasoning 默认不保留，包括 raw 中 reasoning；若提供显式 debug retention 则独立 artifact，永不 Evidence/FACT。Hash 与 metadata 永久保留；删除 UI/API 暂缓。

## 验收与停止条件

TDD 覆盖 DTO/auth/replay/ACL/secret/adapter errors/budget/nullable usage/recovery/import boundary。真实 socket FakeProvider E2E 以及 Core→Host→local HTTP upstream E2E，至少两种 output-token capability。测试不依赖互联网或真实密钥。单独报告 Host、adapter、secret、isolation、E2E；最终 scripts/test.ps1 全绿、Alembic matrix、git diff --check、本地提交及 clean tree 才可 STABLE。

可选人工 smoke 只发送极小固定无敏感 JSON prompt，默认不运行。AI-4 two-stage、recommendation、conversation、UI、streaming、embedding、tools、PAPER/LIVE writes 均 Deferred。
