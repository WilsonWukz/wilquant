# Phase 4 P0 与 Strategy Library 设计

## 范围

本设计覆盖 Phase 4 的第一批次：

1. 在不改变 Phase 3 核心语义的前提下完成 P0 类型检查与最小真实回测冒烟。
2. 建立可复用、不可变、可追溯的内置策略配置库。

本批次不实现 Experiment、Comparison、Diagnostics、Journal、Research Report 或 `/research` 前端工作台。

## P0 验收设计

### 类型检查

Mypy 使用项目 runtime 下的独立缓存目录，例如：

```powershell
python -m mypy backend --cache-dir .runtime/test-cache/mypy-phase4
```

不得使用 `--ignore-errors`、排除新文件或降低既有严格度。缓存目录必须位于受控项目 runtime 或临时目录，避免用户目录权限问题。

### 真实冒烟

使用临时 runtime root，按以下顺序执行：

1. 创建并发布最小交易日历。
2. 创建并发布最小 DatasetVersion。
3. 创建 READY MarketDataProfile。
4. 运行一次 BuyAndHold。
5. 查询 metrics、equity、orders、fills、positions。
6. 运行一次 TopNMomentumRotation。
7. 释放数据库连接并重新创建应用服务。
8. 重新读取两个 BacktestRun。
9. 重新计算并核对 Manifest/Artifact SHA-256。
10. 确认 SQLite 没有逐日 Bar、逐日 Equity 或逐笔 Artifact 明细表。

冒烟只验证已有 Phase 3 接口，不引入 Broker、网络行情或任意用户代码。

## Strategy Library 数据模型

### StrategyDefinition

字段：`id`、`name`、`description`、`strategy_type`、`status`、`created_at`、`updated_at`。

允许的 `strategy_type` 为 `BUY_AND_HOLD` 与 `TOP_N_MOMENTUM_ROTATION`；允许的 `status` 为 `ACTIVE` 与 `ARCHIVED`。名称是展示字段，不是版本身份。

### StrategyVersion

字段：`id`、`strategy_definition_id`、`version`、`strategy_spec_json`、`strategy_fingerprint`、`change_note`、`created_at`。

`strategy_spec_json` 必须是完整、可校验的内置策略配置。fingerprint 基于规范化 JSON、策略类型和规则版本生成，不包含数据库 ID、创建时间或本地化消息。

同一 Definition 内的版本号在 `BEGIN IMMEDIATE` 事务内执行 `max(version)+1`，立即插入，并由 `(strategy_definition_id, version)` 唯一约束提供最终保护。

StrategyVersion 创建后不可更新、不可删除。数据库触发器只允许正常插入，阻止已存在版本的 UPDATE/DELETE。归档 Definition 不级联删除版本。

## 服务与 API

Repository 负责事务、唯一约束和不可变保护；Service 负责策略类型/spec 校验和 fingerprint；API 负责安全输入模型和错误映射。

API：

```text
POST /api/v1/strategies
GET  /api/v1/strategies
GET  /api/v1/strategies/{strategy_id}
POST /api/v1/strategies/{strategy_id}/versions
GET  /api/v1/strategies/{strategy_id}/versions
GET  /api/v1/strategies/{strategy_id}/versions/{version_id}
POST /api/v1/strategies/{strategy_id}/archive
```

API 不接受 Python、表达式、SQL、模板或脚本字段。请求中的 spec 只允许对应内置策略的显式字段，并限制长度、数值范围和 JSON 深度。

## BacktestRun 兼容扩展

新增 `strategy_version_id` 为可空外键。旧 Run 保持可读；旧 Run 的内嵌 `strategy_spec_json` 不迁移、不重写。

新建 Run 必须显式提供 `strategy_version_id`，服务端读取冻结版本并将完整 spec 复制到 Run 快照中。Run fingerprint 同时覆盖 StrategyVersion fingerprint、完整 spec、数据快照、日期范围、初始资金、费用和滑点配置。

StrategyDefinition 归档或后续新增版本不得改变历史 Run 的读取结果。

## 失败与兼容策略

- 不存在的 Definition/Version 返回稳定的 404 业务错误。
- ARCHIVED Definition 不允许创建新版本或启动新回测，但历史版本和历史 Run 可读。
- spec 与 strategy_type 不匹配时拒绝写入，不产生半成品版本。
- 迁移失败时不修改已有 Phase 2/3 表数据。
- 不创建逐日 Bar、Equity 或 Artifact SQLite 明细表；结果仍通过 Parquet/Manifest 保存。

## 测试设计

后端至少覆盖：版本不可变、事务内递增、相同 spec fingerprint 稳定、新 Run 显式绑定版本、归档不影响历史 Run、旧 Run 兼容、非法脚本字段拒绝、Strategy API 路由与错误响应、迁移单一 head 与空库升级。

P0 还必须覆盖隔离 cache 的 mypy 命令与最小真实冒烟脚本，并在最终验收中报告完整后端 pytest、Ruff、mypy、前端测试/构建和 Alembic 往返结果。

## 明确不做

本批次不实现策略优化、网格搜索、并行回测、Broker/PAPER/LIVE/vn.py、Experiment、Comparison、Diagnostics、Journal、Report 或 `/research` UI。
