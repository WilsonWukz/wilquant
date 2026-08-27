# ADR-0002：ExecutionGateway 与 Multi-Market 执行边界

- 状态：已批准；仅批准架构边界，不授权实现 Broker 连接
- 日期：2026-08-27
- 决策范围：CN A-share 与 US stocks/ETFs 的统一市场规则、LIVE 资本授权边界、独立 ExecutionGateway、broker-neutral contract
- 前置决策：ADR-0001 vn.py runtime boundary、Phase 5 PAPER execution design

## 背景

wilquant 当前具备数据导入与不可变发布、交易日历、策略版本、A 股回测、研究工作台和确定性 PAPER 执行。FastAPI Core、SQLite、Parquet/DuckDB、BacktestEngine、ExecutionKernel 和 Paper Domain 均在不连接 Broker 的情况下运行。

Phase 6 需要同时解决两个架构升级：

1. 支持真实资金时，Strategy、Risk、Capital Authorization、User Approval、Gateway 和 Broker 必须形成不可绕过的权限链。
2. 系统从当前 A 股语义演化为 CN A-share 与 US stocks/ETFs 共用的 multi-market research & execution architecture。

不能只增加一个 US BrokerAdapter。若市场、标的、货币、日历、数量和交易规则仍然写死在 A 股或 Broker 层，US Data、Backtest、PAPER 与 LIVE 会形成不同语义，真实执行也无法可靠对账。

同时，Broker SDK 可能携带原生依赖、线程、进程级副作用、账户单例和 credential。它们不能进入 FastAPI Core，也不能成为 PAPER、回测或数据功能的启动依赖。

## 决策

采用以下统一架构：

```text
Data / TradingCalendar / Instrument
              |
              v
       MarketRulesVersion
              |
      +-------+--------+
      |                |
      v                v
 Backtest/PAPER   LIVE Pre-trade
      |                |
      |        Risk + Capital + User Approval
      |                |
      |                v
      |       FastAPI Core IPC Client
      |                |
      |     authenticated 127.0.0.1 HTTP/JSON
      |                v
      |       ExecutionGateway Process
      |                |
      |       BrokerCapabilities + Mapping
      |                |
      |                v
      |          BrokerAdapter
      |                |
      +---- no dependency on Broker SDK
```

决策由两个相互配合、但职责独立的边界组成。

## 决策一：统一 Multi-Market Domain

### 市场范围

第一阶段支持：

- CN A-share stocks/ETFs，CNY；
- US stocks/ETFs，USD。

US v1 为 long only、regular trading hours only、MARKET/LIMIT、no leverage、no short、no options、no extended-hours execution。

暂不支持 options、futures、crypto、short selling、margin automation、跨币种 portfolio 和自动 FX conversion。

### 共享领域概念

Data、Backtest、PAPER 和 LIVE 共同使用：

```text
Market
Instrument
Currency
TradingCalendarVersion
MarketRulesVersion
Quantity
SettlementPolicy
SellabilityPolicy
CashAvailabilityPolicy
```

Instrument 使用稳定内部 ID。`symbol` 只在 market/exchange scope 内有意义；全局身份至少冻结 market、exchange、symbol、currency 和 asset type。

每个 BacktestRun、PaperSession 和 ExecutionRequest 必须绑定不可变的 TradingCalendarVersion 与 MarketRulesVersion fingerprint。任何执行层不得临时根据 symbol 或 Broker 名称猜测市场规则。

### 数量与价格

MarketRulesVersion 明确：

```text
quantity_step
minimum_quantity
minimum_notional
price_tick
round_lot
fractional_allowed
quantity_precision
```

Phase 6A 不批准全项目 Decimal migration。Phase 6B 先以 Quantity 值对象封装现有 int，通过 `CN_A_SHARE_V1` compatibility rules 保持 Phase 5 零漂移；US v1 也先支持整数股。fractional capability 可以被契约表达，但默认不启用，后续需要独立 migration 与验收。

### Settlement 与时间

不再使用一个 `t_plus_one`/`supports_t0` boolean 同时代表结算、可卖和现金可用：

- SettlementPolicy 描述证券与现金结算；
- SellabilityPolicy 描述持仓何时可卖；
- CashAvailabilityPolicy 描述卖出资金何时可交易或提现。

事件 timestamp 使用 UTC，trade date 使用 market-local date。TradingCalendarVersion 使用 IANA timezone；US 使用 `America/New_York` 处理 DST，并显式保存 regular open/close。未来可记录 pre/after-hours 窗口，但 US v1 ExecutionRules 始终拒绝 extended-hours dispatch。

### Currency

Currency 是受控领域值。第一版账户为 single base currency：CN/CNY、US/USD。账户、Instrument、Broker account binding 和订单 currency 必须一致；不允许隐式 FX。

## 决策二：独立 ExecutionGateway

### 进程边界

ExecutionGateway 必须运行在独立本地进程。FastAPI Core 不导入 Broker SDK、不构造 Broker runtime、不读取 Broker credential。

Gateway 的权限限定为：

```text
health
submit/cancel/query order
list orders/fills
get account snapshot/positions
report Broker capabilities
set/query/reset kill latch
provide reconciliation inputs
```

Gateway 不能修改 Strategy、RiskPolicy、CapitalAuthorization、LIVE state 或研究数据，不能解冻 Core。

### IPC 选择

MVP 采用绑定 `127.0.0.1` 的 HTTP/JSON，加 256-bit 短期 Bearer secret、Windows 用户 ACL 文件、协议版本、request ID 和 timestamp。

| 候选 | 结论 |
|---|---|
| localhost HTTP/JSON | 采用；Windows、FastAPI/Pydantic、fake gateway、故障注入和调试成本最合适 |
| Windows named pipe | 不采用为 MVP；ACL 更强，但 Python 服务、测试和生命周期复杂度更高 |
| gRPC | 不采用为 MVP；强 schema 有价值，但 protobuf/tooling 对当前规模过重 |

Gateway 不得绑定 `0.0.0.0`。secret 不放在命令行、日志或审计中，并在 Gateway 重启时轮换。

该模型只承诺防网络暴露、误调用和跨普通 Windows 账户访问，不声称抵御已经控制同一 Windows 用户会话的恶意进程。本阶段不为该威胁引入远程 attestation、硬件密钥或其他过重基础设施。

### Credential

Broker credential 仅由 Gateway 读取，优先存放在 Windows Credential Manager。禁止进入 Core environment、Frontend、SQLite 普通配置、Strategy、Research artifact、IPC body、audit 或日志。

## 决策三：显式 Broker Mapping 与 Capability

真实 dispatch 必须引用不可变：

```text
BrokerAccountBindingVersion
BrokerInstrumentMappingVersion
```

不得直接使用前端选择结果或 symbol 字符串提交。Instrument mapping 至少冻结 Broker instrument ID、market、exchange、symbol、currency、asset type、quantity rules 和 fingerprint。缺失、漂移、冲突或 Broker 回报不一致时 fail closed。

BrokerAdapter 必须报告 BrokerCapabilities：

```text
supported markets/assets/order types
fractional shares
quantity precision/step/minimum
minimum notional
regular/extended hours
client order ID submit/query support
required instrument identifiers
cancel support
```

允许的执行能力是 System Phase Scope、MarketRulesVersion、账户授权、BrokerCapabilities 和 mapping 的交集。Broker 支持某项能力不代表 wilquant 自动启用它。

## 决策四：资本授权与人工确认

CapitalAuthorization 使用不可变版本，只有 USER 可以扩大额度。RiskEngine 只能拒绝、降低、冻结或 KILL。盈利不会自动提高 approved capital。

第一版真实执行仅支持 manual user-confirmed LIVE：

```text
OrderIntent
 -> deterministic RiskDecision
 -> CapitalAuthorization decision
 -> immutable ExecutionRequest
 -> immutable user ExecutionApproval
 -> ExecutionGateway
```

Approval TTL 为 60 秒，绑定：

- ExecutionRequest fingerprint；
- RiskPolicyVersion/fingerprint；
- CapitalAuthorizationVersion/fingerprint；
- Broker account snapshot ID/fingerprint；
- reconciliation run/state fingerprint；
- Broker account binding 与 instrument mapping version；
- MarketRulesVersion 与 TradingCalendarVersion。

任何请求、账户、snapshot、mapping、market rules 或 reconciliation 变化都使 Approval 失效。

## 决策五：UNKNOWN、幂等与 Reconciliation

`client_order_id` 在 Core 持久化并跨重启稳定。submit timeout 绝不 retry submit。

统一使用 UNKNOWN，同时记录：

```text
unknown_operation = SUBMIT | CANCEL
pending_operation = SUBMIT | CANCEL
```

SUBMIT UNKNOWN 与 CANCEL UNKNOWN 使用不同的 reconciliation 路径。UNKNOWN 不得由本地推测直接转成 SUBMITTED/CANCELLED。

Broker 不支持 client order ID 查询时，账户、标的、方向、数量、价格和时间窗口只能生成 reconciliation candidate。即使看起来唯一，也不能自动关联；只有 Broker 返回可证明唯一的稳定订单标识才可自动确定，否则保持 UNKNOWN 并要求人工确认或进一步对账。

Broker 是实际订单、成交、持仓和现金的外部事实来源；Core 是资本授权、LIVE state、RiskDecision 和 Approval 的事实来源。差异触发 fail closed、FROZEN 和追加式 reconciliation，不删除历史。

## 决策六：Kill 与恢复

Gateway 保存持久化 kill latch。Core 或 Gateway 重启不会自动清除。

- FROZEN 禁止 BUY，允许逐笔确认且严格 risk-reducing 的 SELL；
- KILLED 禁止所有新订单，只允许取消已有可撤订单；
- KILLED 不能直接恢复 ACTIVE；必须 DISABLED、用户 reset、Gateway 重握手、full reconciliation CLEAN、重新 ARM/ACTIVATE；
- 不自动清仓。

Core、Gateway、Broker 或 heartbeat 失败时全部停止新订单。已有 Broker 订单继续 query/cancel，不自动重发。恢复后必须 full reconciliation。

## PAPER 与 Backtest 兼容性

ExecutionGateway 不成为 Backtest、PAPER、Data 或 Research 的依赖。Multi-market rules 在核心纯领域中实现：

```text
ExecutionKernel + MarketRules/ExecutionRules
```

Backtest 与 PAPER 使用同一版本规则；LIVE 只使用内核做 pre-trade validation、dry run 和 parity comparison，不能生成 BrokerFill。

Phase 6B 必须先建立当前 CN 行为的 characterization tests，再引入 CN compatibility profile 和 US rules。US 支持的完整链路必须是：

```text
US Data -> US Backtest -> US PAPER -> US LIVE
```

## 被否决的方案

### 只增加 US BrokerAdapter

会把 market identity、日历、currency、quantity 和 settlement 规则留在 A 股 Core 或 Broker 层，造成 Data/Backtest/PAPER/LIVE 分叉，否决。

### 在 Paper 表增加 mode=LIVE

PaperFill 是模拟事实，BrokerFill 是外部事实；状态机、UNKNOWN、source of truth 和 reconciliation 不同，否决。

### Broker SDK 与 FastAPI 同进程

会扩大 credential 和原生依赖暴露面，使 Broker 崩溃影响 Core，并迫使 PAPER/研究安装交易依赖，否决。

### 未认证的 localhost Gateway

localhost 不等于安全边界，无法防误调用和跨普通账户访问，否决。

### Windows named pipe 作为 MVP

安全属性较好，但当前 Python/Windows 测试与调试复杂度不匹配；保留为后续强化选项，不作为 MVP。

### gRPC 作为 MVP

对当前单机请求量和技术栈过重，否决。

### 全项目立即 Decimal quantity migration

变更面过大，容易破坏 Phase 5 A 股行为。先使用 Quantity 值对象、MarketRules 与兼容层，fractional 实现另行迁移，否决一次性改造。

### 用 symbol 直接映射 Broker instrument

无法处理跨市场同 symbol、Broker identifier、currency 和 asset type 冲突，否决。

### timeout 后自动 retry submit

可能造成真实重复订单，永久禁止。

## 后果

### 正面

- CN 和 US 共用统一领域语言及 Data→Backtest→PAPER→LIVE 链路。
- Broker SDK、credential 和崩溃被限制在独立进程。
- 资本、风险、用户批准与真实执行无法被 Strategy/AI 合并绕过。
- UNKNOWN、mapping、capability 和 reconciliation 成为一等概念。
- Phase 5 PAPER 不需要 Gateway，A 股行为可通过 compatibility profile 保持不变。
- 首个 US Broker Adapter 不被国内 Adapter 进度阻塞。

### 代价

- Phase 6B 必须先完成 multi-market foundation，不能直接接 Broker。
- 需要版本化 MarketRules、mapping、Broker capability 和 calendar/session 契约。
- Gateway IPC、kill latch、heartbeat 和重启恢复增加运维与测试面。
- 同一 Windows 用户会话内的恶意进程仍超出 MVP 安全保证。
- fractional shares 需要未来独立的 quantity persistence migration。

## 实施顺序

```text
6A LIVE + Multi-Market Architecture / ADR
6B Multi-Market Foundation: US Data/Backtest/PAPER, no Broker
6C Capital Authorization + LIVE State Machine
6D ExecutionGateway + Fake Broker, UNKNOWN/reconciliation/recovery
6E First US Broker Adapter, manual-confirm, regular-hours stocks/ETFs
6F LIVE UI
6G Final LIVE Acceptance
```

国内真实 Broker Adapter 后续单独实施，不阻塞 6E。

## 本 ADR 不授权

- 不授权任何代码、配置、依赖或 migration 变更；
- 不授权启动 Gateway 或加载 Broker SDK；
- 不授权读取 credential、真实账户或提交订单；
- 不授权进入 Phase 6B；
- 不授权 Automated LIVE、extended hours、fractional execution、margin、short、options、futures 或 crypto。
