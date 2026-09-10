# 隔离 AI Provider Host：本地配置与验证

AI 是可选能力。普通 Data、Backtest、Research、PAPER 启动及 readiness 不依赖 Host。没有公开 chat/completion API，没有 AI UI，也没有交易写权限。

## 非密钥配置

将下列配置保存为本机批准的 profile JSON，并把 `model` 改为该端点支持、你明确选择的模型 ID。Host 不接受每次请求任意指定 URL；修改 endpoint/model/capability 需要重新冻结 Core ModelConfigVersion。

```json
{
  "profile_id": "openai-compatible-default",
  "base_url": "https://api.deepseek.com/v1",
  "model": "REPLACE_WITH_APPROVED_MODEL_ID",
  "credential_ref": "wilquant.ai.openai-compatible.default",
  "allow_local_http": false,
  "capabilities": {
    "output_token_parameter": "max_tokens",
    "reasoning_parameter": "unsupported",
    "supports_json_object": true,
    "supports_json_schema": false,
    "reasoning_content_field": "reasoning_content",
    "input_usage_field": "prompt_tokens",
    "output_usage_field": "completion_tokens",
    "total_usage_field": "total_tokens",
    "cached_usage_field": "prompt_cache_hit_tokens",
    "reasoning_usage_field": "completion_tokens_details.reasoning_tokens"
  }
}
```

以上是需要按目标服务核对的配置模板，不是对任意模型兼容性的承诺。`OpenAI-compatible` 表示共同协议族，而不是行为完全等同于 OpenAI。具体 request/response capability 必须被显式声明、冻结和测试。不存在按厂商名猜参数、收到 400 换参数重试或自动切换模型。JSON_SCHEMA、streaming、tools 暂不支持；unsupported reasoning 参数不发送。

## 保存凭证

在仓库根目录运行，下一个提示中隐藏输入 key。禁止将 key 放入命令参数、profile JSON、长期环境变量或聊天消息。

```powershell
backend\.venv\Scripts\python.exe -m quant_lab.ai_provider_host set-credential --credential-ref wilquant.ai.openai-compatible.default
```

Provider key 由 Windows Credential Manager 保存，Host 读取；Core 仅保存 credential_ref。无 plaintext/DPAPI fallback。Credential Manager 不可用则拒绝运行。

## 独立启动与停止

```powershell
scripts\ai-provider-host.ps1 -Action start -ProfilePath C:\YourConfig\provider.json
scripts\ai-provider-host.ps1 -Action status
scripts\ai-provider-host.ps1 -Action stop
```

默认 127.0.0.1:8011；运行目录 `runtime/ai-provider-host`。`-RuntimeRoot` 可指定专用目录；同一次启动/停止使用相同目录。`-Fake` 可用于无费用的本地测试。

脚本不加入默认 dev.ps1；启动隐藏窗口，记录 PID/创建时间并核对可执行文件及精确 Host 调用。停止仅处理已确认的 Host 及虚拟环境启动器子进程，不按 Python 名称批量结束。强制本地停止不保证 upstream 未计费。

token 在专用 `.secrets` 目录以受限 Windows ACL 创建并验证，每次启动旋转；不要移动到共享目录或手工打印。目录权限不满足要求时 fail closed，不自动放宽权限。

## 可选人工外部 smoke

先启动所批准的 Host，再显式确认可能产生费用：

```powershell
backend\.venv\Scripts\python.exe -m quant_lab.ai_provider_smoke --confirm-external-call --profile C:\YourConfig\provider.json --token-file runtime\ai-provider-host\.secrets\ai-provider-host.token --audit-root runtime\ai-smoke
```

仅发送固定 `Return {"status":"ok"} as JSON.` 等小型提示，不读取或发送 portfolio/PAPER/研究资料。每次创建独立新审计数据库和合成协议测试 case，沿用正式 Run/Attempt/Usage 及 migration；调用后关闭测试 run，不冒充 accepted analysis。输出模型、状态、usage、耗时、finish reason、审计目录，不输出 key 或 headers。没有价格配置时 cost 明确 UNKNOWN；调用次数限 1，输出限 32 tokens。

自动门禁只用 FakeProvider 与本地 HTTP upstream；本轮真实外部 smoke 未执行：`OPTIONAL EXTERNAL VALIDATION NOT RUN`。

## 状态、预算与保留

- STARTED 分别进入 COMPLETED / FAILED / ABANDONED；这些终态之间不能转移。
- 已知 HTTP/协议失败为 FAILED；可能已发送后丢失结果为 ABANDONED / PROVIDER_RESULT_UNKNOWN，不代表没有费用。
- 发送前固定身份和保守预算 reservation；未知结果不释放为零，重试必须新 Attempt。
- usage 的 NULL 表示未知，0 表示明确报告零；金额 hard budget 无可用价格时拒绝调用。
- ModelConfigVersion 内保存 typed provider_profile、budget、call_policy 及输出参数；预算价格由用户配置，不抓取实时定价。Core 输入预留使用配置的完整 token 上界，不使用 chars/4 乐观估计。
- raw 与 candidate 在 AI artifact namespace 独立保存，有上限、脱敏与 SHA256。candidate 不等于 accepted output；reasoning 默认删除且当前不开放 debug retention。删除 API/UI、tombstone 操作、周期预算和 DPAPI fallback 均 Deferred。
- 若已写入 0016 invocation binding 或未知 usage，降级至 0015 会拒绝，避免丢失审计或把未知填零。不要修改 migration 绕过保护。

本地安全模型防网络暴露、误调用、跨普通账户访问和 Core/UI/log 泄露；不声称抵御已控制同一 Windows 用户会话的恶意进程。Host 无应用数据库访问代码和凭证，并非同用户 OS 权限沙箱。
