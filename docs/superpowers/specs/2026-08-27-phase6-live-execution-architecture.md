# Phase 6A LIVE Execution、Capital Authorization 与 Multi-Market Architecture 设计

- 状态：已批准
- 日期：2026-08-27
- 基线：`dev` / `19ce9c6`
- 适用范围：Phase 6A LIVE + Multi-Market 设计，不授权实现真实 Broker 连接

## 1. Goals

本设计将 wilquant 从当前 A 股能力演化为覆盖 CN A-share 与 US stocks/ETFs 的 multi-market quant research & execution architecture，并为 LIVE 执行建立可实现、可审计、默认关闭且 fail-closed 的正式边界。目标包括：

1. 定义真实资金授权模型，并确保只有本地用户能够扩大资金权限。
2. 将 Strategy、Risk、Capital Authorization、User Approval 和 Broker Execution 分成不可绕过的独立门禁。
3. 将 ExecutionGateway 与 FastAPI Core 隔离为不同进程，使 Broker SDK、原生依赖和 credential 不进入 Core。
4. 定义 broker-neutral 的请求、订单、成交、账户快照和 Adapter 契约。
5. 处理重复点击、submit timeout、UNKNOWN、崩溃恢复、状态漂移和 reconciliation。
6. 保持 Phase 5 PAPER 在没有 Gateway、Broker SDK 和 credential 时完全独立运行。
7. 正式定义 Market、Instrument、Currency、TradingCalendar 与版本化 MarketRules，使同一规则服务 Data、Backtest、PAPER 和 LIVE。
8. 以兼容层和基线测试保证 Phase 5 A 股回测与 PAPER 行为零漂移。
9. 建立完整链路 `US Data → US Backtest → US PAPER → US LIVE`，不把美股支持缩减为单个 BrokerAdapter。
10. 为 Phase 6B–6G 提供顺序清晰、每阶段均可测试的实施边界。

## 2. Non-Goals

Phase 6A 不包含：

- Alembic migration 或任何数据库 schema 变更；
- LIVE API、LIVE 页面、Gateway 进程或 BrokerAdapter 实现；
- QMT、XtQuant、vn.py、IBKR、Alpaca、BigTrader 或其他券商依赖；
- 真实账户登录、行情订阅或真实订单提交；
- 自动策略 LIVE、自动清仓、离线订单排队或后台自动重试；
- 多用户登录、RBAC、多方审批或远程 Gateway；
- 抵御已经完全控制当前 Windows 用户会话的恶意进程。
- options、futures、crypto、short selling、margin automation、leverage 或跨币种 portfolio；
- 美股 extended-hours execution、自动 FX conversion 或 fractional share 实现；
- 对现有全项目执行 Decimal quantity migration。

Alembic head 在本阶段保持 `20260722_0013`。

## 3. Architecture Invariants

以下规则是后续所有 multi-market 与 LIVE 实现必须满足的正式不变量：

1. **AI NEVER CONTROLS CAPITAL AUTHORIZATION。** AI、Agent、Strategy、Optimizer 和 Research workflow 均不能增加资本、启用 LIVE、解冻、清除 kill latch 或访问 credential。
2. Strategy 只能产生 `OrderIntent`，不能创建 `ExecutionApproval`、`BrokerOrder` 或 `BrokerFill`。
3. RiskEngine 只能 `REJECT`、`REDUCE`、`FREEZE` 或 `KILL`，不能增加授权、激活 LIVE 或解冻。
4. 只有本地 `USER` 可以增加资本、激活 LIVE、解冻和逐笔批准真实执行。
5. 资金授权存在不等于 LIVE 已启用；LIVE 启用也不等于某个请求已获批准。
6. realized profit 不会自动提高 `approved_live_capital`。
7. 所有授权、策略、风险、审批、mapping 和 reconciliation 输入必须通过不可变版本 ID 或 fingerprint 冻结。
8. Gateway 只执行已通过全部门禁的请求，不能修改 Core 的策略、风险、资本授权或 LIVE 状态。
9. Broker credential 只存在于 Gateway 进程，不进入 Core、前端、SQLite、普通配置、日志或审计。
10. LIVE 的 BrokerOrder、BrokerFill 与 PAPER 的 PaperOrder、PaperFill 永久分离。
11. LIVE Fill 必须来自 Broker 外部事实，ExecutionKernel 不得生成 BrokerFill。
12. 任何认证失败、mapping 缺失、状态过期、对账差异、连接异常或结果歧义均 fail closed。
13. submit timeout 绝不直接 retry submit。
14. PAPER、回测、数据和研究功能不依赖 Gateway 启动或 Broker credential。
15. Instrument 的全局身份不能只使用 symbol，至少由稳定内部 ID 关联 market、exchange、symbol、currency 和 asset type。
16. Data、Backtest、PAPER 与 LIVE 必须消费同一不可变 MarketRulesVersion，禁止仅在 LIVE Adapter 内实现美股规则。
17. Currency 是显式领域概念；第一版每个账户只有一种 base currency，CN 为 CNY，US 为 USD。
18. 时间戳内部使用 UTC；trade date 始终是相应 market timezone 下的 market-local date。
19. SettlementPolicy、SellabilityPolicy 与 CashAvailabilityPolicy 必须分离，禁止用单一 `t_plus_one` boolean 描述不同市场。
20. Phase 5 CN A-share 的手数、费用、滑点、T+1 和 FIFO 行为在 multi-market 演化中必须零漂移。

## 4. System Context 与 Trust Boundary

```text
React Frontend
    |
    | Core HTTP API
    v
FastAPI Core Process
    +-- Market / Instrument / Currency
    +-- TradingCalendar / MarketRulesVersion
    +-- Strategy / Manual OrderIntent
    +-- Deterministic RiskEngine
    +-- CapitalAuthorizationService
    +-- LiveTradingStateService
    +-- ExecutionApprovalService
    +-- BrokerReconciliationService
    +-- SQLite: market control, authorization, approval, local mirror, audit
    |
    | authenticated broker-neutral HTTP/JSON
    | bind 127.0.0.1 only
    v
ExecutionGateway Process
    +-- protocol and authentication guard
    +-- gateway-side persistent kill latch
    +-- request idempotency registry
    +-- account/instrument mapping validation
    +-- broker-neutral Adapter mapping
    +-- credential loader
    |
    v
BrokerAdapter
    |
    v
Future Official Broker API
```

信任边界分成三层：

- **Frontend → Core**：前端只表达用户意图，不能自行计算最终授权或直接访问 Gateway。
- **Core → Gateway**：Core 发送已批准、带不可变绑定的 execution envelope；Gateway 再执行协议、kill latch、mapping 和幂等校验。
- **Gateway → Broker**：只有 Gateway 持有 Broker credential 和 Broker SDK 对象。

Core compromise 可能伪造业务请求，但仍不能直接读取 Broker credential；Gateway 必须独立验证协议、认证、kill latch、请求结构和 mapping。Gateway compromise 可能滥用当前 Broker 会话，因此 credential 最小权限、账户 allowlist、资本上限、Broker 侧限制和 reconciliation 仍然必要。进程隔离降低耦合和凭据暴露范围，但不被描述为完整安全沙箱。

## 5. Multi-Market Domain Foundation

### 5.1 第一阶段市场范围

| Market | Asset type | Account currency | Direction | Session | Order type |
|---|---|---|---|---|---|
| `CN` | A-share stock / ETF | CNY | long only | 交易所 regular session | MARKET simulation / LIMIT；LIVE 能力由 Broker capability 决定 |
| `US` | stock / ETF | USD | long only | regular trading hours only | MARKET / LIMIT |

第一阶段统一禁止：options、futures、crypto、short selling、margin automation、leverage 和 extended-hours execution。US v1 不要求 fractional execution，但领域与 capability 契约必须能够表达 fractional support；是否允许实际 fractional order 由后续阶段、MarketRulesVersion 与 Broker capability 的交集决定，默认 false。

国内真实 Broker Adapter 在首个 US Adapter 之后单独加入，不阻塞 US LIVE。CN 的 Data、Backtest 和 PAPER 继续工作，且不因 Gateway 或 US 支持产生行为漂移。

### 5.2 Market、Instrument 与 Currency

建议核心值对象：

```text
Market
    market_id              CN | US
    default_currency       CNY | USD
    timezone               Asia/Shanghai | America/New_York
    calendar_id

Instrument
    instrument_id          stable internal UUID/ID
    market_id
    exchange               XSHG | XSHE | XNYS | XNAS | ARCX | ...
    symbol
    currency
    asset_type             STOCK | ETF
    listing_status
    trading_rules_version_id

Currency
    code                    CNY | USD
    minor_unit
    amount_precision
```

`symbol` 只是 market/exchange scope 内的可读标识，不是全局主键。所有数据、策略、回测、PAPER、LIVE、mapping 和审计使用稳定 `instrument_id`；展示或导入时再解析 `(market, exchange, symbol, currency, asset_type)`。

Instrument identity 与 Broker identity 分离。一个内部 instrument 可以针对不同 Broker/environment 拥有不同 `BrokerInstrumentMappingVersion`，但 mapping 必须反向唯一且经过验证。

Currency 正式成为领域值对象，而不是任意字符串。第一版账户仍为 single base currency：CN account 只能是 CNY，US account 只能是 USD；一个 BacktestRun、PaperAccount 或 LiveAccount 只能绑定一个 market/currency scope。跨币种 portfolio、cash netting 和自动 FX conversion 不在本阶段设计范围内。

### 5.3 TradingCalendar 与时间模型

TradingCalendarVersion 必须表达：

```text
market_id
exchange
timezone              IANA timezone
market_local_trade_date
regular_open_local
regular_close_local
regular_open_utc
regular_close_utc
is_open
session_type
optional pre_market window
optional after_hours window
fingerprint
```

内部事件、Broker 消息、订单和成交 timestamp 使用 timezone-aware UTC。交易日、T+N 计算、策略 session 和日级净值使用 market-local `trade_date`。US 使用 `America/New_York` IANA timezone，通过 timezone database 处理 DST，不用固定 UTC offset。

Phase 6B 可以扩展日历 schema 支持 regular session UTC 边界和可选 pre/after-hours 元数据，但 US v1 ExecutionRules 永久拒绝 extended-hours dispatch。即使日历未来包含盘前/盘后窗口，也不等于账户或 Broker 获得 extended-hours 权限。

### 5.4 TradingRules / MarketRulesVersion

`MarketRulesVersion` 是 Data、Backtest、PAPER、Risk 和 LIVE 共同引用的不可变规则集合：

```text
market_rules_version_id
market_id
asset_type
effective_from
quantity_rules
price_rules
session_rules
settlement_policy
sellability_policy
cash_availability_policy
fee_policy
short_sale_policy
leverage_policy
fingerprint
```

数量和价格规则至少包含：

```text
quantity_step
minimum_quantity
minimum_notional
price_tick
round_lot
fractional_allowed
quantity_precision
```

含义必须分离：

- `quantity_step`：订单数量的最小增量；
- `minimum_quantity`：允许提交的最小数量；
- `round_lot`：标准交易单位，不自动等同 minimum quantity；
- `fractional_allowed`：市场规则是否允许小数数量；
- `quantity_precision`：规范化和序列化精度；
- `minimum_notional`：适用于支持按金额或 fractional 的市场/Broker 限制；
- `price_tick`：合法委托价格增量。

CN v1 compatibility profile 固定复现当前规则，例如 A 股 BUY round lot 100、整数 quantity、既有 price tick、费用和卖出可用性。US v1 profile 表达整数股 long-only、regular-hours、MARKET/LIMIT、无 leverage；未来 fractional capability 不通过隐式 Decimal 转换开启。

### 5.5 Settlement、Sellability 与 Cash Availability

禁止用单一 `t_plus_one` 或 `supports_t0` boolean 同时描述以下三件事：

```text
SettlementPolicy
    证券与现金何时完成法律/账务结算

SellabilityPolicy
    新买入资产何时可以再次卖出

CashAvailabilityPolicy
    卖出所得何时可以重新交易或提取
```

CN A-share 兼容规则由独立 policy 明确表示买入资产下一 market-local trade date 才可卖；US 股票/ETF 的 sellability、settlement 和 cash reuse 根据账户类型及 Broker capability 分别建模。即便 US Broker 允许卖出所得立即用于交易，也不能推导资金已经可提现。

PositionLot 应保存 acquisition timestamp、market-local trade date、settlement date、sellable-from instant/date 和 quantity，而不是只依赖 `sellable_from_date` 推导所有市场行为。

### 5.6 ExecutionKernel 演化

目标结构：

```text
ExecutionKernel
    +-- immutable ExecutionRules / MarketRulesVersion
    +-- QuantityNormalizer
    +-- PriceNormalizer
    +-- SessionEligibility
    +-- SellabilityPolicy
    +-- CashAvailabilityPolicy
    +-- FeePolicy
```

ExecutionKernel 仍然是无 Broker、无数据库副作用的确定性纯内核。Backtest 和 PAPER 传入相同 MarketRulesVersion；LIVE 只用它做 pre-trade validation、dry run、预估滑点和 parity comparison，不能生成 BrokerFill。

Phase 6B 不做全项目一次性 Decimal migration。推荐先引入规范化 `Quantity` 值对象和 `quantity_precision`：CN compatibility adapter 接受现有 int 并产生相同 int 结果；US v1 也先使用整数股。未来 fractional 实现必须通过独立 migration 和测试，不可通过把类型从 int 静默改成 Decimal 来启用。

### 5.7 当前 A 股假设审计

当前代码中已确认的 market-specific 假设包括：

- `market_data.domain.Exchange` 只有 `XSHG/XSHE`；
- `InstrumentId.value` 与 Bar identity 使用 `symbol.exchange`，尚无显式 market/currency/asset type identity；
- Instrument 虽保存 currency、lot size、price tick，但 currency 尚不是受控领域值对象；
- `OrderIntent`、订单、成交、PositionLot、ExecutionKernel 和 PAPER DTO 使用 `quantity: int`；
- ExecutionKernel 使用 `lot_size` 做 round-lot 和 volume rounding；
- Instrument 使用 `supports_t0`，PositionLot 以 `sellable_from_date` 表示可卖性；
- ExecutionKernel fee result 包含 stamp tax 与 transfer fee 等 A 股字段；
- Backtest `OrderType` 目前为 `LIMIT` 与 `MARKET_ON_OPEN_SIMULATED`；
- Backtest metrics 默认 annualized days 为 252；
- TradingCalendar 已有 market、exchange、timezone、local session date/open/close，为 multi-market 扩展提供基础，但尚未正式冻结 regular-session UTC 边界与 DST 契约。

Phase 6B 必须用 characterization tests 锁定这些现有 CN 输入输出，然后以 `CN_A_SHARE_V1` MarketRulesVersion 包装当前语义。只有 CN 全部基线测试不变后，才增加 US rules 和 US Data→Backtest→PAPER 测试。

### 5.8 统一的跨市场链路

目标不是“LIVE 才支持 US”，而是：

```text
CN Data -> CN Backtest -> CN PAPER -> future CN LIVE
US Data -> US Backtest -> US PAPER -> US LIVE

                 shared stable instrument identity
                 shared TradingCalendarVersion
                 shared MarketRulesVersion
                 shared deterministic Risk DTO
```

MarketDataProfile、BacktestRun、PaperSession 与 ExecutionRequest 都必须冻结 market、currency、TradingCalendarVersion 和 MarketRulesVersion fingerprint。禁止在执行层临时猜测 market rules。

### 5.9 US Data Contract

US v1 market bar contract 必须显式包含：

```text
instrument_id
market_id = US
exchange
symbol
currency = USD
asset_type = STOCK | ETF
frequency
timestamp_utc
market_local_trade_date
session_type = REGULAR
open / high / low / close
volume
amount nullable when provider cannot supply
adjustment_type
data_source
source_batch_id
quality_status
```

唯一性建立在不可变 DatasetVersion、instrument ID、frequency、market-local trade date/session 上，不建立在 symbol 上。导入数据中的 symbol/exchange 必须先解析到已验证 instrument identity；无法唯一解析时拒绝发布。

US v1 只消费 regular-session bars。原始价、复权价和 corporate action 来源必须通过 adjustment type 与数据版本显式区分，不能在 Backtest 或 PAPER 中静默切换。corporate action 现金流与复杂税务不在 Phase 6B 首个 vertical slice 中实现，但数据契约必须保留版本和来源，避免未来无法重放。

US MarketDataProfile 第一版绑定单一 market、USD、TradingCalendarVersion、MarketRulesVersion 和 bars DatasetVersion。US BacktestRun 与 PaperSession 使用该 profile；策略、估值、费用、session eligibility、quantity 和 sellability 全部由同一个冻结规则快照驱动。

## 6. Actors 与权限

| Actor | 可以执行 | 永久禁止 |
|---|---|---|
| `USER` | 创建/调整资本授权、ARM/ACTIVATE、FREEZE/KILL、满足条件后 UNFREEZE、批准逐笔执行、触发 reconciliation | 直接创建 BrokerFill、绕过 Gateway 或修改历史版本 |
| `RISK_ENGINE` | APPROVE/REJECT 风险、收紧额度、FREEZE、KILL | 增资、激活 LIVE、解冻、创建用户 Approval |
| `SYSTEM` | freshness 检查、故障冻结、过期 Approval、启动恢复、触发 reconciliation | 扩大资本或替用户确认真实执行 |
| `GATEWAY` | submit/cancel/query、报告 Broker 状态、设置/保持 kill latch | 修改策略、风险、资本授权、解冻 Core |
| `BROKER` | 返回外部订单、成交、持仓、现金和账户事实 | 修改 wilquant 的授权与审批历史 |
| `STRATEGY` | 产生 OrderIntent | 产生 Approval、调用 Gateway、修改资金或 LIVE 状态 |

MVP 面向单机、单 Windows 用户，不引入登录系统或多人 RBAC。`approved_by`、`created_by` 等字段记录当前本地用户身份、稳定用户 profile ID 和操作来源。

## 7. Capital Authorization

### 7.1 聚合与不可变版本

`CapitalAuthorization` 是稳定身份和当前版本指针；`CapitalAuthorizationVersion` 保存每次授权的不可变事实。

版本至少包含：

```text
id
capital_authorization_id
account_id
market_id
currency
version
approved_live_capital
max_deployed_capital
max_single_order_notional
effective_from
status
fingerprint
created_by
created_at
change_type = CREATE | INCREASE | DECREASE | REPLACE
change_reason
```

任何提高或降低都创建新版本。授权金额、account equity、position market value、reservation 和 order notional 必须使用该账户唯一 base currency；CN 为 CNY，US 为 USD，不做隐式 FX。历史 `RiskDecision`、`ExecutionRequest`、`ExecutionApproval` 和 `BrokerOrder` 必须保留当时使用的 `capital_authorization_version_id` 与 fingerprint。

### 7.2 资本计算

```text
effective_live_capital
= min(approved_live_capital, account_equity)

deployable_ceiling
= min(effective_live_capital, max_deployed_capital)

deployed_capital
= broker_position_market_value + reserved_buy_notional

remaining_deployable
= max(0, deployable_ceiling - deployed_capital)

unapproved_profit
= max(0, account_equity - approved_live_capital)
```

`reserved_buy_notional` 使用未终结 BUY 订单已批准的 notional ceiling 加预估费用，不使用可能低估风险的最后成交价。部分成交后，reservation 等于未成交数量对应的剩余 ceiling；FILLED、CANCELLED、REJECTED 或经 Broker 证明终结后释放。

数据库可以静态约束：

```text
0 < max_single_order_notional
max_single_order_notional <= max_deployed_capital
max_deployed_capital <= approved_live_capital
```

数据库不得约束 `approved_live_capital <= current account_equity`，因为市场亏损可能在不修改授权历史的情况下使 equity 下降。运行时始终使用 `effective_live_capital` 收紧可用资本。

### 7.3 增加与降低授权

- 增加授权只能由 `USER` 发起，必须展示旧值、新值、差额、账户和 `LIVE · REAL CAPITAL`，重新输入新金额并完成明确确认。
- 降低授权由 `USER` 发起后立即创建并激活新版本，不因当前 deployed capital 已高于新 ceiling 而回滚历史或强制清仓。
- 降低后若 `deployed_capital > deployable_ceiling`，禁止所有 risk-increasing 请求，只允许符合持仓、T+1 和风险规则的减仓 SELL。
- RiskEngine 可以生成更低的临时/持久限制或触发 FROZEN/KILLED，但不能创建更高版本。
- account equity、盈利、充值镜像或 Broker snapshot 更新均不能隐式改变授权版本。

## 8. LIVE Trading State Machine

### 8.1 状态语义

| 状态 | 新 BUY | 减仓 SELL | Cancel | 说明 |
|---|---:|---:|---:|---|
| `DISABLED` | 禁止 | 禁止 | 允许处理已有订单 | 未启用真实执行 |
| `ARMED` | 禁止 | 禁止 | 允许 | 授权、Gateway、mapping、对账已准备 |
| `ACTIVE` | 满足门禁时允许 | 满足门禁时允许 | 允许 | 唯一允许新风险进入 Gateway 的状态 |
| `FROZEN` | 禁止 | 用户确认且 risk-reducing 时允许 | 允许 | 暂时故障或风险收紧 |
| `KILLED` | 禁止 | 禁止 | 取消可撤订单 | 紧急停止，Gateway latch 同步保持 |

### 8.2 状态转换

```text
DISABLED --USER arm + prerequisites--> ARMED
ARMED --USER activate + final checks--> ACTIVE
ARMED --USER disable---------------> DISABLED
ACTIVE --USER/RISK/SYSTEM freeze----> FROZEN
FROZEN --USER unfreeze + reconcile--> ACTIVE
ACTIVE/FROZEN/ARMED --kill----------> KILLED
KILLED --controlled reset-----------> DISABLED
```

ARM 前置条件：存在有效 CapitalAuthorizationVersion 与 RiskPolicyVersion、Gateway authenticated/healthy、Broker account binding 有效、instrument mapping catalog 可用、Broker snapshot 新鲜、full reconciliation 无差异、kill latch 未设置。

UNFREEZE 只能由 `USER` 发起；RiskEngine 和 Gateway 不能解冻。UNFREEZE 必须展示冻结原因、最新 Broker snapshot 与 reconciliation 结果，并重新执行 prerequisites。

`KILLED` 不允许直接变成 ARMED/ACTIVE。controlled reset 要求 Core 已为 DISABLED、用户明确 reset、Gateway 重启或重新握手、Broker 已连接、full reconciliation 通过；清除 gateway latch 后仍需重新 ARM 和 ACTIVATE。MVP 不自动清仓，紧急 liquidation 属于独立未来设计。

## 9. Shared Intent 与 PAPER/LIVE 分离

共享层只包含没有执行副作用的概念：

```text
Strategy / User
    -> OrderIntent DTO
    -> deterministic Risk input/output DTO
    -> instrument and market rule DTO
```

执行事实严格分叉：

```text
Approved Intent
    +-- PAPER -> PaperExecutionEngine -> PaperOrder / PaperFill
    |
    +-- LIVE  -> ExecutionRequest -> ExecutionApproval
                  -> ExecutionGateway -> BrokerOrder / BrokerFill
```

禁止给 `paper_orders` 增加 `mode=LIVE`。PaperFill 是模拟事实，BrokerFill 是外部事实，二者具有不同 source of truth、失败状态、对账和不可变性语义。

PAPER 的启动、测试和运行不加载 Gateway client、Broker SDK 或 credential loader。

## 10. ExecutionRequest 与 Fingerprint

`ExecutionRequest` 是 Core 内部、与 PaperOrder 分开的 LIVE 执行请求，至少包含：

```text
id
account_id
broker_account_binding_version_id
instrument_id
broker_instrument_mapping_version_id
side
quantity
order_type
limit_price
execution_mode = LIVE | LIVE_DRY_RUN
source_type = MANUAL | STRATEGY
strategy_version_id nullable
order_intent_id
risk_decision_id
risk_policy_version_id
capital_authorization_version_id
requested_at
idempotency_key
client_order_id
status
request_fingerprint
```

请求还必须冻结 `market_id`、`currency`、`market_rules_version_id`、`trading_calendar_version_id`、market-local trade date 和规范化 quantity/price。`request_fingerprint` 使用规范化 JSON 和 SHA-256，覆盖所有能够改变真实订单语义或授权判断的字段，包括：账户及 binding 版本、标的及 mapping 版本、MarketRulesVersion、TradingCalendarVersion、方向、数量、订单类型、价格、执行模式、Intent/Risk/Capital 版本、strategy version 和 client order ID。fingerprint 创建后不可修改；需要修改数量、价格、账户、标的、市场规则或交易 session 时必须创建新的 ExecutionRequest。

## 11. ExecutionApproval

`ExecutionApproval` 是用户批准 WHO、WHEN、WHAT 的不可变记录，至少包含：

```text
id
execution_request_id
execution_request_fingerprint
approved_by
approved_at
expires_at
approved_quantity
approved_notional_ceiling
approved_notional_currency
risk_decision_id
risk_policy_version_id
risk_policy_fingerprint
capital_authorization_version_id
capital_authorization_fingerprint
broker_account_snapshot_id
broker_account_snapshot_fingerprint
reconciliation_run_id
reconciliation_state_fingerprint
broker_account_binding_version_id
broker_instrument_mapping_version_id
market_rules_version_id
trading_calendar_version_id
status = VALID | CONSUMED | INVALIDATED | EXPIRED
```

默认 Approval TTL 为 60 秒，且只能成功 dispatch 一次。dispatch 前必须重新加载并比较：

- ExecutionRequest ID 和 fingerprint；
- RiskPolicyVersion、RiskDecision 和 fingerprint；
- CapitalAuthorizationVersion 和 fingerprint；
- broker account binding 与 instrument mapping 版本；
- MarketRulesVersion、TradingCalendarVersion 与 market session eligibility；
- broker account snapshot ID、fingerprint 和 freshness；
- reconciliation run ID、状态与 fingerprint；
- LIVE 状态、Gateway health 和 kill latch。

请求内容、账户状态版本、Broker snapshot、mapping 或 reconciliation 状态发生任何变化，Approval 立即 `INVALIDATED`，不得复用。超过 60 秒则 `EXPIRED`。无论失效原因如何，用户都必须在重新 risk/capital evaluation 后创建新 Approval。

Strategy、AI、RiskEngine、SYSTEM 和 Gateway 均不能创建用户 Approval。

## 12. Execution Lifecycle

### 12.1 状态

```text
CREATED
RISK_APPROVED
CAPITAL_APPROVED
AWAITING_USER_CONFIRMATION
APPROVED
DISPATCHING
SUBMITTED
PARTIALLY_FILLED
FILLED
CANCEL_PENDING
CANCELLED
REJECTED
EXPIRED
UNKNOWN
```

核心路径：

```text
CREATED
 -> RISK_APPROVED
 -> CAPITAL_APPROVED
 -> AWAITING_USER_CONFIRMATION
 -> APPROVED
 -> DISPATCHING
 -> SUBMITTED
 -> PARTIALLY_FILLED
 -> FILLED
```

任何 pre-dispatch 门禁失败可进入 `REJECTED` 或 `EXPIRED`，且不创建 BrokerOrder。`DISPATCHING` 表示请求已越过本地事务边界、准备或已经向 Broker 发送，因此不能把 IPC timeout 当作“未发送”。

### 12.2 UNKNOWN 与 pending operation

`UNKNOWN` 是统一未知状态，同时必须记录：

```text
unknown_operation = SUBMIT | CANCEL
pending_operation = SUBMIT | CANCEL
unknown_since
last_gateway_request_id
last_known_broker_order_id nullable
unknown_reason_code
```

- `SUBMIT` UNKNOWN：Broker 可能已接受，禁止重新 submit，优先查询 client order ID、订单和成交。
- `CANCEL` UNKNOWN：原订单可能仍然有效或已经撤销，继续查询该 Broker order 的状态和后续成交；不得假设 reservation 已释放。
- UNKNOWN 不得由本地推测直接转为 SUBMITTED 或 CANCELLED。
- 只有 Broker 返回稳定订单标识/状态，或 reconciliation 取得可证明的外部事实后才能离开 UNKNOWN。
- 所有 UNKNOWN 转换追加 `ORDER_RECONCILED` 审计，并记录证据来源。

## 13. Order Idempotency

`client_order_id` 在 Core 中持久化后、dispatch 前生成，全局稳定且重启后不变。一个 ExecutionRequest 永久对应一个 client order ID。

幂等层次：

1. Frontend/API 使用 `idempotency_key` 防止重复点击创建请求或 Approval。
2. Core 对 ExecutionRequest fingerprint 和 client order ID 建唯一约束。
3. Gateway 保存或持久化已见的 gateway request ID、client order ID 和响应摘要。
4. Broker 支持 client order ID 时，以其作为首选查询和去重依据。
5. submit timeout 时只允许 query/reconcile，不允许 retry submit。

若 Broker 不支持 client order ID 查询，账户、标的、方向、数量、价格和时间窗口只能产生 `reconciliation candidate`。即使候选看起来唯一，也不能自动认定为已提交。只有 Broker 返回可证明唯一对应的稳定订单标识，系统才可自动关联；否则保持 UNKNOWN，并要求人工确认或进一步对账。

## 14. Broker Account 与 Instrument Mapping

### 14.1 Account binding

`BrokerAccountBindingVersion` 将 wilquant `live_account_id` 显式绑定到：

```text
broker_id
broker_environment
broker_account_id
account_type
base_currency
adapter_instance_id
version
fingerprint
status
effective_from
created_by
created_at
```

账户 binding 采用不可变版本。更换 Broker account、环境或 Adapter instance 必须创建新版本，并使引用旧版本但尚未 dispatch 的 Approval 失效。

### 14.2 Instrument mapping

`BrokerInstrumentMappingVersion` 显式映射：

```text
internal_instrument_id
broker_id
broker_environment
broker_instrument_id
market_id
exchange
symbol
security_type
currency
lot_size
price_tick
quantity_step
minimum_quantity
minimum_notional
fractional_allowed
version
fingerprint
status
effective_from
```

LIVE dispatch 不得仅依赖 symbol 字符串、显示名称或前端选择结果。Core 和 Gateway 都必须验证 account binding、instrument mapping、MarketRulesVersion 与 Broker capability 的交集；缺失、版本漂移、冲突、停用或 Broker 回报不一致时 fail closed，并触发 FROZEN/reconciliation。

## 15. LIVE Risk Snapshot 与 Freshness

RiskEngine 必须在 Gateway 之前执行，但 LIVE 风险输入来自最近完成且无差异的 Broker reconciliation snapshot，而不是 PAPER 账户或过期本地缓存。

默认规则：

- Broker account snapshot 最大年龄为 10 秒；
- Approval TTL 为 60 秒；
- dispatch 前重新验证 snapshot ID、fingerprint 和 freshness；
- open orders 必须计入 reserved capital；
- 持仓、现金、open orders 或 mapping 变化会使旧 Approval 失效；
- snapshot stale、reconciliation 非 CLEAN 或 Broker disconnected 时 fail closed。

SELL 不受新增资本 ceiling 阻止，但仍检查 Broker 可卖持仓、T+1、现有 SELL reservation、订单状态和 LIVE state。FROZEN 仅允许严格 risk-reducing、逐笔确认的 SELL；KILLED 不允许新 SELL。

## 16. LIVE DRY RUN

`LIVE_DRY_RUN` 与 PAPER 不同：

- 连接 Gateway 并读取真实 Broker account snapshot、mapping 和 health；
- 使用 LIVE RiskPolicy、CapitalAuthorization 和 reconciliation 状态；
- 生成完整的 RiskDecision、capital decision 和 dry-run audit；
- 永远不调用 `BrokerAdapter.submit_order()`；
- 不创建 BrokerOrder 或 BrokerFill；
- 页面和 API 明确返回 `DRY_RUN_NOT_SUBMITTED`。

Dry run 不能自动升级为 LIVE dispatch；真实执行必须创建或重新确认 LIVE ExecutionRequest。

## 17. Core ↔ Gateway IPC

### 17.1 方案比较

| 方案 | 安全 | Windows 支持 | 可调试性 | 复杂度 | 故障隔离 |
|---|---|---|---|---|---|
| localhost HTTP/JSON | loopback + local secret + ACL，适合单用户威胁模型 | 优秀 | 优秀 | 低 | 独立进程 |
| Windows named pipe | ACL 边界更强 | 优秀 | 中等 | 中高，测试与 Python 服务整合更复杂 | 独立进程 |
| gRPC localhost | 可加认证与强 schema | 良好 | 中等 | 高，引入 protobuf/tooling | 独立进程 |

MVP 选择 localhost HTTP/JSON。它与 FastAPI/Pydantic 技术栈一致，便于 fake gateway、契约测试、故障注入和 Windows 本地诊断；不因为形式“专业”而引入 gRPC。

### 17.2 网络与认证

- Gateway 只绑定 `127.0.0.1`，不得绑定 `0.0.0.0`。
- 启动器生成 256-bit 随机短期 Bearer secret。
- secret 通过仅当前 Windows 用户可读的 ACL 文件传递，不放在命令行参数、日志或审计中。
- Gateway 每次重启轮换 secret；旧 secret 立即失效。
- 请求包含 protocol version、gateway request ID、timestamp 和 client order ID。
- Gateway 拒绝无认证、版本不匹配、过期、格式非法和已处理但 payload 不同的请求。
- IPC secret 是本地进程认证 secret，不是 Broker credential；Core 永远接触不到 Broker credential。

该安全模型的明确边界是：防止网络暴露、误调用和跨普通 Windows 账户访问；不声称能够抵御已经控制同一 Windows 用户会话的恶意进程。Phase 6A 不为这个超出 MVP 的威胁引入远程 attestation、硬件密钥或其他过重基础设施。

### 17.3 Gateway 最小权限 API

Gateway 仅暴露：

```text
health
submit order
cancel order
query order
list open orders
list fills
get broker account snapshot
get positions
reconcile inputs
set/query/reset kill latch
```

Gateway 不暴露策略、研究、RiskPolicy、CapitalAuthorization、Core unfreeze 或账户资金编辑能力。

## 18. Broker-Neutral Adapter Contract

概念契约：

```python
class BrokerAdapter(Protocol):
    def connect(self) -> BrokerConnectionStatus: ...
    def disconnect(self) -> None: ...
    def health(self) -> BrokerHealth: ...
    def capabilities(self) -> BrokerCapabilities: ...

    def get_account_snapshot(self) -> BrokerAccountSnapshot: ...
    def get_positions(self) -> tuple[BrokerPosition, ...]: ...

    def submit_order(self, request: BrokerSubmitRequest) -> BrokerSubmitResult: ...
    def cancel_order(self, request: BrokerCancelRequest) -> BrokerCancelResult: ...

    def get_order(self, broker_order_id: str) -> BrokerOrderSnapshot: ...
    def find_order_by_client_id(self, client_order_id: str) -> BrokerOrderSnapshot | None: ...
    def list_open_orders(self) -> tuple[BrokerOrderSnapshot, ...]: ...
    def list_fills(self, since: datetime) -> tuple[BrokerFillSnapshot, ...]: ...
```

`BrokerCapabilities` 至少表达：

```text
supported_markets
supported_asset_types
supported_order_types
fractional_shares
quantity_precision
quantity_step
minimum_quantity
minimum_notional
regular_hours
extended_hours
client_order_id_submit
client_order_id_query
required_instrument_identifiers
cancel_supported
```

核心 DTO 只使用 broker-neutral 字段：Decimal、显式 market/currency/exchange/asset type、UTC 时间戳、market-local trade date、内部 instrument/account binding version 和稳定外部 ID。券商特有能力放入经过 allowlist 的 `adapter_metadata` 或 `broker_specific_options`，不能污染核心状态机。

最终可执行能力取以下交集：

```text
System Phase Scope
∩ MarketRulesVersion
∩ LiveAccount Authorization
∩ BrokerCapabilities
∩ BrokerAccountBindingVersion
∩ BrokerInstrumentMappingVersion
```

例如 Broker 支持 extended hours 或 fractional shares，也不能突破 US v1 的 regular-hours、默认整数股范围。

若 Adapter 不支持某项能力，必须显式报告 capability，不得伪造空结果。真实 Adapter 接入前要对字段、枚举、时区、数量单位、价格单位和 client order ID 支持做契约测试。

## 19. BrokerOrder 与 BrokerFill

`BrokerOrder` 是内部订单镜像，不等于 Broker order ID：

```text
internal_order_id
execution_request_id
client_order_id
broker_id
broker_account_binding_version_id
broker_account_id
broker_order_id nullable until proven
status
pending_operation nullable
unknown_operation nullable
submitted_at nullable
last_broker_update_at nullable
```

`BrokerFill` 必须包含 Broker 提供的稳定 fill/trade ID、broker order ID、账户 binding、instrument mapping、数量、价格、费用、时间与原始响应 fingerprint。BrokerFill 追加写入并按稳定外部 ID 幂等去重，不允许 ExecutionKernel、本地价格推算或 UI 创建。

## 20. Source of Truth 与 Reconciliation

### 20.1 事实来源

| 数据 | 事实来源 |
|---|---|
| CapitalAuthorization、LIVE state、ExecutionApproval | wilquant Core |
| RiskDecision | wilquant deterministic RiskEngine |
| Broker 实际订单、成交、持仓、现金 | Broker |
| 本地 BrokerOrder/BrokerFill/account snapshot | Broker 事实的可审计镜像 |
| PAPER Order/Fill | wilquant PAPER domain |

### 20.2 BrokerReconciliationService

每次 full reconciliation：

1. 创建 `BrokerReconciliationRun` 并冻结 account binding、mapping catalog 和起始时间。
2. 查询 Broker open orders、recent orders、recent fills、positions、cash 和 account identity。
3. 规范化并保存原始响应 fingerprint。
4. 比较 expected 与 actual 的 orders、fills、positions、cash、account mapping 和 instrument mapping。
5. 产生 `CLEAN`、`DISCREPANCY` 或 `INCOMPLETE` 结果及逐项 discrepancy。
6. 追加校正镜像和审计，不删除或覆盖历史事实。
7. 只有 `CLEAN` 且 snapshot 新鲜时才允许 ARM/ACTIVATE 或创建可 dispatch Approval。

自动关联只在 Broker 返回稳定 order/fill/account/instrument ID，且能证明唯一对应时发生。基于字段相似度产生的 candidate 必须保持待人工确认，不得改变 UNKNOWN 或创建 BrokerFill。

## 21. Crash Recovery 与 Kill Switch

### 21.1 Gateway-side kill latch

- Core KILL 时先持久化 Core 状态和审计，再向 Gateway 设置持久化 latch。
- Gateway 在 latch 设置后拒绝所有 submit，继续允许 cancel/query/reconciliation。
- Core 崩溃或 Gateway 重启不能自动清除 latch。
- 清除要求 Core 为 DISABLED、用户明确 reset、Broker connected、full reconciliation CLEAN。
- latch 清除后 LIVE 仍为 DISABLED，必须重新 ARM 和 ACTIVATE。

### 21.2 Heartbeat

Core 与 Gateway 默认每 5 秒进行一次 authenticated heartbeat。连续 3 次丢失即视为失联：

- Gateway 停止接受新 execution，继续观察已提交 Broker orders；
- Core 禁止 dispatch，将可能已经发出的 DISPATCHING 请求转为 UNKNOWN/SUBMIT；
- 恢复连接后先 reconciliation，不自动恢复 ACTIVE。

### 21.3 Restart

Gateway 启动后默认处于不可 dispatch 状态，必须查询：

```text
broker account identity
open orders
recent orders
recent fills
positions
cash
kill latch
```

完成 account/instrument mapping 校验和 full reconciliation 前，Core 不能恢复 ACTIVE。

## 22. Credential Boundary

优先 credential 来源顺序：

1. Windows Credential Manager；
2. 受 OS 权限保护的 gateway-local secret manager；
3. 仅 Gateway 进程可读的环境注入，用于特定 Adapter 无法使用 credential store 的情况。

禁止来源与落点：

- Frontend request/response；
- Core `.env` 或 Core process environment；
- SQLite 普通配置表；
- StrategyVersion、research report 或 artifact；
- audit payload、异常信息、日志或 telemetry；
- IPC request body。

日志只记录 broker ID、脱敏 account binding ID、credential source type 和加载结果，不记录 secret、token 或完整 Broker account number。

## 23. Audit

LIVE 关键动作必须写入 append-only `live_audit_events`，至少包括：

```text
CAPITAL_AUTH_CREATED
CAPITAL_AUTH_INCREASED
CAPITAL_AUTH_DECREASED
LIVE_ARMED
LIVE_ACTIVATED
LIVE_FROZEN
LIVE_UNFROZEN
LIVE_KILLED
LIVE_KILL_RESET
EXECUTION_REQUEST_CREATED
RISK_APPROVED
RISK_REJECTED
CAPITAL_APPROVED
CAPITAL_REJECTED
EXECUTION_APPROVED
EXECUTION_APPROVAL_INVALIDATED
EXECUTION_REJECTED
ORDER_DISPATCH_STARTED
ORDER_SUBMITTED
ORDER_UNKNOWN
ORDER_RECONCILED
CANCEL_REQUESTED
CANCEL_UNKNOWN
BROKER_FILL_RECEIVED
BROKER_POSITION_RECONCILED
RECONCILIATION_STARTED
RECONCILIATION_COMPLETED
RECONCILIATION_DISCREPANCY
GATEWAY_CONNECTED
GATEWAY_DISCONNECTED
GATEWAY_KILL_LATCH_SET
GATEWAY_KILL_LATCH_CLEARED
ACCOUNT_MAPPING_INVALID
INSTRUMENT_MAPPING_INVALID
```

Audit payload 记录 actor、对象 ID、版本 ID、fingerprint、原因码和时间，但不得包含 credential、IPC secret 或未脱敏 Broker account number。

## 24. Schema Proposal

本节只定义候选 schema，不创建 migration。

| 实体 | 职责 | 历史策略 |
|---|---|---|
| `markets` | CN/US 市场、默认 currency、timezone 和 calendar identity | 稳定身份 |
| `currencies` | CNY/USD 精度与 minor unit | 受控参考数据 |
| `instrument_versions` | market/exchange/symbol/currency/asset type 与 lifecycle | 不可变版本 |
| `market_rules_versions` | quantity、price、session、settlement、sellability、cash、fee policies | append-only + fingerprint |
| `live_accounts` | wilquant LIVE account 身份、当前状态和当前版本指针 | 状态可变，转换有审计 |
| `broker_account_bindings` | 稳定 binding 身份 | 不原地改语义 |
| `broker_account_binding_versions` | Broker/environment/account/adapter 不可变映射 | append-only |
| `capital_authorizations` | 授权聚合身份和当前版本指针 | 不保存历史额度覆盖值 |
| `capital_authorization_versions` | 每次资本授权事实 | append-only，UPDATE/DELETE trigger |
| `broker_instrument_mappings` | 内部 instrument 与 Broker mapping 聚合 | 不原地改语义 |
| `broker_instrument_mapping_versions` | 不可变 Broker instrument 映射 | append-only |
| `execution_requests` | 冻结的 LIVE/LIVE_DRY_RUN 请求 | fingerprint 后不可改 payload |
| `execution_approvals` | 用户逐笔批准及全部版本绑定 | append-only，状态仅按受控转换 |
| `broker_orders` | 本地 Broker order 镜像和 UNKNOWN operation | 状态受控转换，外部 ID 不可重绑 |
| `broker_fills` | Broker 成交事实 | append-only，外部 fill ID 幂等 |
| `broker_account_snapshots` | 现金、权益、持仓摘要、open order 摘要 | append-only + fingerprint |
| `broker_reconciliation_runs` | 对账输入、结果与状态 fingerprint | append-only 结果 |
| `broker_reconciliation_items` | order/fill/position/cash/mapping 差异 | append-only |
| `live_audit_events` | LIVE 全链路审计 | append-only |

所有金额使用 Decimal/Numeric，时间保存 timezone-aware UTC，交易日另存显式 market-local date。quantity 的持久化目标类型必须能表达 `quantity_precision`，但 Phase 6A 不创建 migration，Phase 6B 先以兼容值对象封装现有整数列。schema 需要为 instrument identity、MarketRulesVersion、account binding、instrument mapping、client order ID、Broker order/fill ID、Approval fingerprint 建唯一约束或冲突检测。

## 25. Core API Proposal

以下为 `/api/v1/live` contract 草案，不在 Phase 6A 实现。

```text
GET  /markets
GET  /markets/{market_id}/rules/versions
GET  /instruments/{instrument_id}
GET  /instruments/{instrument_id}/rules

POST /accounts
GET  /accounts/{account_id}

POST /accounts/{account_id}/broker-bindings
GET  /accounts/{account_id}/broker-bindings/versions
POST /instrument-mappings
GET  /instrument-mappings/{instrument_id}/versions

POST /accounts/{account_id}/capital-authorizations
POST /accounts/{account_id}/capital-authorizations/increase
POST /accounts/{account_id}/capital-authorizations/decrease
GET  /accounts/{account_id}/capital-authorizations/versions

POST /accounts/{account_id}/arm
POST /accounts/{account_id}/activate
POST /accounts/{account_id}/freeze
POST /accounts/{account_id}/unfreeze
POST /accounts/{account_id}/kill
POST /accounts/{account_id}/kill-reset

POST /execution-requests
GET  /execution-requests/{request_id}
POST /execution-requests/{request_id}/evaluate-risk
POST /execution-requests/{request_id}/evaluate-capital
POST /execution-requests/{request_id}/approve
POST /execution-requests/{request_id}/dispatch
POST /execution-requests/{request_id}/cancel

GET  /accounts/{account_id}/broker/orders
GET  /accounts/{account_id}/broker/fills
GET  /accounts/{account_id}/broker/snapshots/latest
POST /accounts/{account_id}/reconciliations
GET  /accounts/{account_id}/reconciliations/{run_id}
GET  /accounts/{account_id}/audit
```

提高资本、ACTIVATE、UNFREEZE、KILL reset、Approval 和 dispatch 必须带 idempotency key 与 expected version/fingerprint。冲突返回 `409`；状态或 snapshot 过期返回结构化 fail-closed 错误，不自动重试。

API 的 quantity 使用 canonical decimal string DTO，即使当前 CN/US v1 只接受整数，也不使用 JSON binary float。Core 根据 MarketRulesVersion 与 BrokerCapabilities 验证精度；不合法 quantity 返回明确错误，不静默 round。trade date 使用 `YYYY-MM-DD` market-local date，event timestamp 使用带 `Z`/offset 的 ISO-8601 UTC。

## 26. Frontend Safety UX

LIVE 页面必须长期显示文字 `LIVE · REAL CAPITAL`，不能只依赖颜色。market、currency、market-local session、账户、Broker environment、脱敏 Broker account、授权额度、当前 deployed/reserved capital、LIVE state、snapshot age 和 reconciliation state 必须持续可见。CN 与 US 的市场标签和 timezone 必须使用文字，不只依赖颜色或 symbol 格式。

危险操作：

- **Increase capital**：展示旧值/新值/差额，要求重新输入新授权金额并勾选真实资金确认。
- **Activate LIVE**：展示账户、Broker、CapitalAuthorizationVersion、RiskPolicyVersion、mapping 与 reconciliation 摘要，再明确确认。
- **Unfreeze**：展示冻结原因、处理结果和最新 reconciliation，再明确确认。
- **Kill**：保持易于触发，只需一次清晰确认；不得使用复杂口令阻碍紧急停止。
- **Execution approval**：展示精确 instrument mapping、方向、数量、订单类型、价格/notional ceiling、Broker account、snapshot time 和 60 秒倒计时。

双击或网络重试由 idempotency key 吸收。前端倒计时仅用于提示，最终 TTL、fingerprint 和 freshness 校验全部由 Core 执行。

## 27. Threat Model

| Threat | Mitigation |
|---|---|
| duplicate order / UI duplicate click | API idempotency、稳定 client order ID、Gateway request registry、无 submit 自动重试 |
| stale Broker state | 10 秒 freshness、dispatch 前复核、stale 时 fail closed |
| credential leak | credential 仅在 Gateway，Windows Credential Manager，日志/审计脱敏 |
| gateway compromise | 最小 Gateway API、账户 allowlist、Broker 侧权限、kill latch、对账 |
| core compromise | Gateway 独立认证、kill latch、mapping 和 schema 校验；credential 不进入 Core |
| local IPC 网络暴露 | 只绑定 127.0.0.1、short-lived secret、协议版本、ACL 文件 |
| same-user malicious process | 明确不在 MVP 保证范围；不声称本地 secret 可抵御已控制同一用户会话的进程 |
| submit response lost | DISPATCHING/UNKNOWN(SUBMIT)，查询与对账，绝不 retry submit |
| cancel response lost | UNKNOWN(CANCEL)，保留 reservation，查询订单/成交后再确定 |
| restart during dispatch | 持久化 client order ID，重启 full reconciliation，UNKNOWN 保守恢复 |
| incorrect account mapping | 不可变 account binding version，Core/Gateway 双重验证，冲突 fail closed |
| wrong instrument mapping | 显式 mapping version，不依赖 symbol，Broker 回报校验 |
| same symbol across markets/exchanges | 稳定 instrument ID + market/exchange/currency/asset type，不以 symbol 作为全局身份 |
| DST/session boundary error | IANA timezone、UTC timestamp、market-local trade date、版本化 calendar session |
| fractional/lot rounding error | Quantity 值对象、MarketRulesVersion、不静默 round、Broker capability 交集 |
| currency/account mismatch | single-base-currency account、account binding currency 验证、禁止隐式 FX |
| Broker capability exceeds product scope | system phase scope 与 MarketRules/BrokerCapabilities 取交集，默认拒绝 extended hours/fractional/leverage |
| reconciliation candidate 误关联 | candidate 不自动改变状态；需稳定 Broker ID 证据或人工确认 |
| unauthorized capital increase | USER-only command、二次确认、不可变版本、append-only audit |
| profit expands authorization | approved ceiling 与 equity 分离，unapproved profit 不自动部署 |

当前 localhost + Windows ACL + local secret 安全模型只承诺防网络暴露、误调用和跨普通账户访问。它不是同一用户会话内的恶意进程隔离机制，Phase 6A 不为此引入过重基础设施。

## 28. Failure Matrix

| Failure | 新订单 | 已有订单 | 本地状态 | Recovery |
|---|---|---|---|---|
| Core down | Gateway 拒绝 | Gateway 继续 query/记录，不重发 | ACTIVE 不可信 | Core 恢复后 full reconciliation |
| Gateway down | 禁止 dispatch | Broker 订单可能继续成交 | DISPATCHING -> UNKNOWN(SUBMIT) | Gateway 恢复、查询并对账 |
| Broker down | 禁止 | 不假设取消或终结 | FROZEN/INCOMPLETE | Broker 恢复后 full reconciliation |
| IPC timeout before proven send | 禁止 retry | 可能已发送 | UNKNOWN(SUBMIT) | 按 client ID 查询/对账 |
| submit timeout | 禁止 retry | 可能已接受 | UNKNOWN(SUBMIT) | 稳定 Broker ID 证据后转换 |
| cancel timeout | 禁止重复推断 | 原订单可能有效或已撤 | UNKNOWN(CANCEL)，reservation 保留 | 查询 order/fills 后对账 |
| reconciliation mismatch | 禁止 | 继续观察/允许 cancel | FROZEN/DISCREPANCY | 解决差异并重新 full reconciliation |
| credential unavailable | 禁止 | 无法 query 时状态不前推 | Gateway unhealthy | 恢复 credential 后连接、对账 |
| risk snapshot stale | 禁止 | 不改变 Broker 事实 | Approval invalidated | 获取新 snapshot、重评估、重审批 |
| capital exceeded | 禁止 BUY | 允许合规减仓 SELL | FROZEN 或 ACTIVE 下拒绝 BUY | 降低 deployed capital 或用户增资 |
| account mapping missing/drift | 禁止 | 保持已知状态，不重绑 | FROZEN | 创建新 binding version、对账、重审批 |
| instrument mapping conflict | 禁止相关标的 | 不自动改 Broker order 映射 | FROZEN/DISCREPANCY | 人工修正 mapping version、对账 |
| market session closed/ambiguous | 禁止 | 继续 query/cancel | 请求 REJECTED，账户不自动变更 | 刷新 CalendarVersion/session 后重新创建请求 |
| DST/calendar mismatch | 禁止 | 不推测 market-local trade date | FROZEN/DISCREPANCY | 修正 CalendarVersion 并重新验证数据/对账 |
| quantity/capability mismatch | 禁止 | 不改已有 Broker 数量 | 请求 REJECTED | 使用规则与 Broker capability 交集重新创建请求 |
| account currency mismatch | 禁止 | 只读 query/cancel | FROZEN | 修正 account binding；禁止隐式 FX |
| Gateway heartbeat lost | 禁止 | Gateway 继续观察 | Core/Gateway fail closed | 重新认证并 full reconciliation |
| kill latch set | 禁止全部新单 | cancel 可撤订单 | KILLED | controlled reset -> DISABLED |

MVP 不缓存离线订单等待恢复后批量发送。

## 29. Manual LIVE 与 Automated LIVE

首个真实 Broker 版本仅支持 manual user-confirmed LIVE。Strategy 可以创建 Intent，但每个 ExecutionRequest 都必须经过 Risk、Capital 和用户逐笔确认。

未来 Automated LIVE 只有在以下条件全部满足并经过独立设计批准后才可出现：

```text
explicit user automated-live enable
bounded capital authorization
immutable risk policy
bounded single-order notional
gateway authenticated and healthy
broker snapshot fresh
reconciliation CLEAN
account and instrument mappings valid
no freeze or kill
strategy version explicitly authorized
automated kill and audit acceptance complete
```

Phase 6A 不批准 Automated LIVE。

## 30. Future Adapter Candidates

候选仅用于未来调研，不代表选型或实现授权：

- 首个 US Adapter 候选：IBKR、Alpaca；
- 后续国内 Adapter 候选：XtQuant / MiniQMT、vn.py broker gateways。

BigTrader 只有在存在明确、稳定、可审计的外部订单 API 时才可评估为 direct execution adapter；否则不作为直接执行 Adapter。

本阶段不安装任何候选依赖。

## 31. Phase 6 Implementation Sequence

```text
6A LIVE + Multi-Market Architecture / ADR
   本设计与 Gateway/multi-market boundary ADR

6B Multi-Market Foundation
   US instrument/calendar/timezone
   MarketRulesVersion and quantity semantics
   Settlement/Sellability/CashAvailability policies
   US data contract
   US Backtest + US PAPER
   CN characterization and zero-drift acceptance
   NO Broker

6C Capital Authorization + LIVE State Machine
   CapitalAuthorizationVersion
   Broker account/instrument mapping model
   ExecutionRequest/Approval fingerprints
   no real Broker

6D ExecutionGateway + Fake Broker
   authenticated localhost HTTP/JSON
   BrokerCapabilities
   UNKNOWN(SUBMIT/CANCEL)
   reconciliation
   crash recovery
   gateway kill latch

6E First US Broker Adapter
   manual user-confirmed LIVE only
   US stocks/ETFs
   USD single-currency account
   long only, MARKET/LIMIT
   regular hours only

6F LIVE UI
   market/currency/account mapping
   capital, activation, approval, freeze, kill and reconciliation UX

6G Final LIVE Acceptance
   CN and US regression
   end-to-end fault injection
   duplicate/timeout/restart/mapping/DST acceptance
   release audit
```

每个阶段完成后单独验收。Phase 6A 完成后停止，不自动进入 6B。

## 32. Design Acceptance Answers

- **谁能授权或增加真实资金？** 只有本地 USER；Risk、Strategy、AI、SYSTEM 和 Gateway 均不能。
- **谁能冻结？** USER、RiskEngine 和 SYSTEM 可以按原因冻结；Gateway 通过故障报告触发 SYSTEM 冻结。
- **谁能解冻？** 只有 USER，且必须通过新鲜 snapshot 与 CLEAN reconciliation。
- **LIVE 何时允许发送？** ACTIVE、Approval 有效且单次未消费、所有 fingerprint/版本未变、snapshot 不超过 10 秒、reconciliation CLEAN、mapping 有效、Gateway healthy、kill latch 未设置时。
- **Strategy 如何到 ExecutionRequest？** Strategy 只产生 Intent；Core 经过 Risk 与 Capital 后创建冻结 fingerprint 的 ExecutionRequest。
- **Risk 与 Capital 如何组合？** 二者是独立的 fail-closed 门禁，均通过后才进入用户确认；任一变化使 Approval 失效。
- **Core 与 Gateway 在哪里隔离？** 不同进程，通过认证的 127.0.0.1 HTTP/JSON 通信。
- **credential 在哪里？** 仅 Gateway，优先 Windows Credential Manager。
- **submit timeout 怎么办？** UNKNOWN(SUBMIT)，只查询和对账，绝不 retry submit。
- **duplicate order 怎么避免？** API idempotency、稳定 client order ID、Gateway registry 和 Broker 查询。
- **UNKNOWN 怎么办？** 记录 SUBMIT/CANCEL operation；只有稳定 Broker 事实可推进状态，candidate 不自动关联。
- **Core/Gateway/Broker crash 怎么办？** 全部停止新单，保持/查询已有订单，恢复后 full reconciliation。
- **Broker 与本地冲突谁是事实来源？** 实际订单、成交、持仓和现金以 Broker 为事实来源；Core 保存授权事实和外部事实镜像。
- **reconciliation 如何执行？** 冻结 binding/mapping/snapshot 输入，比较 orders/fills/positions/cash/mappings，追加差异和校正记录。
- **profit 会不会自动提高授权？** 不会，未批准盈利保持 `unapproved_profit`。
- **PAPER 与 LIVE 如何隔离？** 只共享纯 Intent/Risk DTO；PaperOrder/Fill 与 BrokerOrder/Fill 分离，PAPER 不加载 Gateway。
- **US 是否只存在于 LIVE Adapter？** 否。US 使用与 CN 相同的 Market/Instrument/Calendar/MarketRules 抽象，必须先完成 US Data→Backtest→PAPER，再进入 LIVE。
- **Instrument 如何唯一标识？** 使用稳定内部 instrument ID，并冻结 market、exchange、symbol、currency、asset type；symbol 不是全局身份。
- **中美数量差异如何处理？** 通过 Quantity 值对象和 MarketRulesVersion 的 step/minimum/round-lot/precision/fractional capability；本阶段不做全项目 Decimal migration。
- **T+1 如何跨市场表达？** 拆分 SettlementPolicy、SellabilityPolicy 和 CashAvailabilityPolicy，不使用单一 boolean。
- **时间与 DST 如何处理？** timestamp 使用 UTC，trade date 使用 market-local date，TradingCalendarVersion 使用 IANA timezone 计算 regular session。
- **Currency 如何处理？** Currency 是显式领域值；CN/CNY 与 US/USD 使用单 base currency account，不做自动 FX。
- **如何保证 Phase 5 A 股零漂移？** 先用 characterization tests 冻结现状，再由 CN_A_SHARE_V1 MarketRules compatibility profile 复现全部行为。

## 33. Phase 6A Completion Boundary

Phase 6A 的唯一仓库变更是本设计文档和 ExecutionGateway/Multi-Market ADR。没有业务代码、配置、依赖或 migration 变更。完成文档自审和 `scripts/test.ps1` 后，状态才能标记为：

```text
PHASE 6A LIVE + MULTI-MARKET ARCHITECTURE DESIGNED
READY FOR PHASE 6B MULTI-MARKET FOUNDATION
```
