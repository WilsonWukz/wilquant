# Phase 5 Paper Execution 与确定性风控设计

## 范围

本设计覆盖 Phase 5 的 PAPER 执行层：持久化账户/订单/持仓状态、确定性 RiskEngine、共享 ExecutionKernel、Session Advance 事务、以及未来 LIVE 资金授权边界。

本阶段不实现：Broker、LIVE、真实下单、scheduler、后台任务队列、vn.py、XtQuant、IBKR。

长期安全边界（从 PAPER 阶段即建立）：Strategy 不等于 Risk，Risk 不等于 Capital Authorization，Capital Authorization 不等于 Execution，且 AI NEVER CONTROLS CAPITAL AUTHORIZATION。

## 运行模式选择

第一版优先 A. Historical Replay PAPER：

1. WIL_QUANT 已具备 immutable DatasetVersion、MarketDataSnapshot、TradingCalendar 与事件驱动回测引擎，天然支撑确定性 replay。
2. 用户点击 ADVANCE 推进一个 TradingSession，无需真实时钟或 scheduler。
3. 进程重启后可基于持久化状态续跑，满足持续账户/持续订单/持续持仓。

B. Manual Current-Day PAPER 作为后续 SHOULD；C. Real-time Scheduler 本阶段 DEFER（禁止 scheduler）。

## Paper 与 Backtest 的本质差异

Backtest：一次性批处理，immutable inputs/outputs，run 完成后冻结。
Paper：持续账户、持续订单、持续持仓，逐 session 推进，重启后继续。

因此 Phase 5 不能只是给 BacktestEngine 包一层 API。Paper 需要独立的持久化领域模型与事务边界，但可复用 Phase 3 的市场/执行规则（见 ExecutionKernel）。

## 领域模型

### PaperAccount

字段：id、name、status（ACTIVE/FROZEN）、base_currency、initial_cash、cash、market_value、account_equity、created_at、updated_at。

cash/market_value/account_equity 是可变的状态快照（每 session 结算后更新）。initial_cash 不可变。

Paper 虚拟资金与未来 approved_live_capital 分离：PAPER 资金不是资金授权，未来 LIVE 的 approved_live_capital 由用户显式授权，且 realized profit 不得自动增加授权。

### PaperSession

字段：id、name、paper_account_id、market_data_profile_id、market_data_snapshot_json、market_data_snapshot_fingerprint、strategy_version_id(nullable)、status、current_session_date、version、started_at、paused_at、stopped_at、created_at、updated_at。

创建时冻结 DatasetVersion + CalendarVersion + MarketDataSnapshot fingerprint；禁止自动跟随 MarketDataProfile.latest，保证 replay 可复现。

状态机（合法转换）：CREATED -> RUNNING -> PAUSED -> RUNNING -> STOPPED；CREATED -> FAILED；RUNNING -> FAILED；RUNNING -> STOPPED；PAUSED -> STOPPED。RESUME 复用 start（从 PAUSED -> RUNNING）。

### OrderIntent

字段：intent_id、source_type（STRATEGY/MANUAL）、source_id、paper_session_id、instrument_id、side、quantity、order_type、limit_price、signal_session_date、intended_execution_session、strategy_version_id(nullable)、reason、metadata_json、idempotency_key、created_at。

OrderIntent 表示上游希望发生什么，绝不表示订单已执行。它是 RiskEngine 的输入。

### RiskPolicy

MVP 确定性字段（个人 A 股日线 PAPER 缩减后）：

MUST：max_single_order_notional、max_single_position_weight、max_total_exposure、cash_buffer_ratio、max_daily_loss、max_drawdown、max_open_orders、allowed_security_types。

OPTIONAL：max_daily_turnover、max_order_count_per_session。

DEFER：per_instrument_limits、time_based_limits、margin/derivatives。

RiskPolicy 采用 versioned（risk_policy_id + version），更新生成新版本而非原地改。禁止 AI 参与风控。

### RiskDecision

字段：id、order_intent_id、decision（APPROVE/REJECT）、reason_codes_json、risk_policy_id、risk_policy_version、account_snapshot_json、position_snapshot_json、market_context_json、evaluated_at。

创建后不可更新（append-only）。APPROVE/REJECT 是决策；RiskEngine 可额外触发 Account Freeze side effect，但 freeze 不作为 decision 枚举值。

Risk 不得偷偷修改订单：超限则 REJECT + ORDER_NOTIONAL_LIMIT，禁止静默降量。未来如需 APPROVE_WITH_LIMIT，必须显式保留 original intent + approved quantity + reason，但 MVP 不实现。

### PaperOrder

字段：id、client_order_id、paper_session_id、order_intent_id、risk_decision_id、instrument_id、side、requested_quantity、accepted_quantity、filled_quantity、order_type、limit_price、status、submitted_session_date、execution_session_date、reject_reason、created_at、updated_at。

状态机（结合 Phase 3 SimulatedOrderStatus 语义）：

CREATED -> RISK_REJECTED 或 APPROVED -> SUBMITTED -> FILLED / PARTIALLY_FILLED(-> EXPIRED) / REJECTED / CANCELLED / EXPIRED。

CREATED -> APPROVED 由 RiskDecision 驱动；APPROVED -> SUBMITTED 在目标 session 的 open 时刻发生。

### PaperFill

字段：id、paper_order_id、paper_session_id、instrument_id、side、quantity、raw_price、slippage、fill_price、commission、stamp_tax、transfer_fee、total_fee、trade_date、created_at。append-only。

### PaperPosition / PaperPositionLot

推荐 Option A（PaperPosition + PaperPositionLot）：

- PaperPositionLot：acquisition lot（acquired_date、quantity、remaining_quantity、cost_price、sellable_from_date），复刻 Phase 3 PositionLot 语义，支撑 T+1。
- PaperPosition：聚合视图（total_quantity、sellable_quantity、average_cost、market_value、unrealized_pnl、realized_pnl），每 session 结算后刷新。

理由：T+1 需要逐 lot 的 sellable_from_date；聚合需要避免每次动态求和；realized PnL 需要 SELL 时由 lot 成本计算；同一事务内更新保证一致。

### PaperAccountSnapshot

每 session 结算后一行：cash、market_value、equity、gross_exposure、daily_pnl、cumulative_pnl、drawdown、session_date。个人日线 PAPER 一年约 250 行，直接存 SQLite。

### PaperAuditEvent

append-only：id、paper_account_id、paper_session_id、event_type、payload_json、created_at。

事件：ACCOUNT_CREATED、SESSION_CREATED、SESSION_STARTED、SESSION_PAUSED、SESSION_ADVANCED、SESSION_STOPPED、INTENT_CREATED、RISK_APPROVED、RISK_REJECTED、ORDER_SUBMITTED、ORDER_FILLED、ORDER_PARTIALLY_FILLED、ORDER_EXPIRED、ORDER_CANCELLED、ACCOUNT_FROZEN、ACCOUNT_UNFROZEN、RISK_POLICY_UPDATED、STRATEGY_ERROR、RISK_ENGINE_ERROR。

AuditEvent 是审计轨迹，不是 event sourcing 的 source of truth；领域实体仍是主存储。

## 风控架构

RiskEngine 输入 OrderIntent + AccountSnapshot + PositionSnapshot + RiskPolicy + MarketContext，输出 RiskDecision。

MVP risk reason codes：INSUFFICIENT_CASH、ORDER_NOTIONAL_LIMIT、POSITION_CONCENTRATION_LIMIT、TOTAL_EXPOSURE_LIMIT、DAILY_LOSS_LIMIT、DRAWDOWN_LIMIT、ACCOUNT_FROZEN、SESSION_NOT_RUNNING、SECURITY_NOT_ALLOWED、OPEN_ORDER_LIMIT。

RiskEngine 异常 -> fail-closed（no approval、no submission、记录 RISK_ENGINE_ERROR）。

## 市场规则 vs 风控规则分层

Market/Execution Rules（ExecutionKernel，复用 Phase 3）：T+1、lot size、price tick、price limit、suspension、missing bar、volume participation、fee、slippage。

Risk Rules（RiskEngine）：order notional、position concentration、total exposure、daily loss、drawdown、account freeze、allowed security type。

## 共享 ExecutionKernel

从 backtest/engine.py 的 BacktestEngine._execute 与 backtest/rules.py 提取最小纯函数 kernel：

- 原样复用：rules.py 的 FeePolicy、SlippagePolicy、round_price、round_lot、validate_quantity、sellable_quantity、validate_sell_quantity、apply_slippage、calculate_fees、validate_execution_price、InstrumentSpec。
- 提取为新 kernel：把 _execute 的 bar missing -> SELL T+1 -> volume -> price limit -> slippage -> fee -> cash check -> partial fill 决策链抽成 ExecutionKernel.execute(...) -> ExecutionResult。
- BacktestEngine 改为调用 kernel（移动不改行为），保证 41 个 Backtest tests 无回归。

目标：BacktestEngine 与 PaperExecutionEngine 都调用 ExecutionKernel。

## 事务模型

advance 在一个 SQLite 事务内完成：RiskDecision + PaperOrder 状态 + PaperFill + cash + position lots + ledger + audit + session current_date。中途失败 ROLLBACK EVERYTHING。Market data 是只读输入，不进事务。

异常语义：策略 on_close 异常 -> Session FAILED + STRATEGY_ERROR，不生成订单；RiskEngine 异常 -> fail-closed；ExecutionEngine 异常 -> rollback + Session FAILED。

## 幂等模型

advance_idempotency_key：同一 key 只推进一次，DB unique constraint。client_order_id：PaperOrder 唯一，HTTP 重试不产生第二个订单。OrderIntent.idempotency_key：手动 intent 幂等。

## Optimistic Guard

advance 同时提交 expected_current_session_date；不一致返回 SESSION_VERSION_CONFLICT。配合 PaperSession.version 整数做 optimistic concurrency。

## Kill Switch / Freeze

PaperAccount.status = FROZEN -> 拒绝所有新 OrderIntent。RiskEngine 可 freeze，但不可自动 unfreeze；解除必须由显式用户动作。

冻结时 pending APPROVED/SUBMITTED 订单 -> CANCELLED/EXPIRED + AuditEvent；已 FILLED 的历史不可改。

## 持久化分层

全部控制面与逐笔状态（PaperAccount/Session/OrderIntent/RiskPolicy/RiskDecision/Order/Fill/Position/PositionLot/AccountSnapshot/LedgerEntry/AuditEvent）放 SQLite，因为个人日线 PAPER 成交量极低（一年约 250 session），与 Phase 3 大规模历史 artifact 走 Parquet 的取舍不同。

## 最小 Ledger

PaperLedgerEntry：id、paper_account_id、paper_session_id、entry_type、amount、related_fill_id(nullable)、created_at。

entry_type：INITIAL_DEPOSIT、BUY_SETTLEMENT、SELL_SETTLEMENT、COMMISSION、STAMP_TAX、TRANSFER_FEE。推荐一笔 Fill 生成一条 settlement summary，目标是 cash 可解释。MANUAL_ADJUSTMENT 第一版不实现。

## API 最小集合

Accounts：POST/GET /api/v1/paper/accounts、GET /api/v1/paper/accounts/{id}。
Sessions：POST/GET /api/v1/paper/sessions、GET /api/v1/paper/sessions/{id}、POST /{id}/start、POST /{id}/pause、POST /{id}/advance、POST /{id}/stop。
Manual intent：POST /api/v1/paper/sessions/{id}/order-intents。
State：GET /{id}/orders、GET /{id}/fills、GET /{id}/positions、GET /{id}/equity、GET /{id}/audit。
Risk：GET/PATCH /api/v1/paper/accounts/{id}/risk、POST /{id}/freeze、POST /{id}/unfreeze。GET risk decisions 为 SHOULD。

## 前端 /paper

页面显著显示 PAPER / 模拟交易，不能像实盘。包含 Account summary、Current session、START/PAUSE/ADVANCE/STOP、Positions/Orders/Fills/Audit、Risk status/policy/Freeze/Unfreeze。仅设计，不实现。

## 未来 Broker 边界

定义 ExecutionGateway 抽象：Phase 5 实现 PaperExecutionGateway，Phase 6+ 替换为 BrokerExecutionGateway。真实 Broker credential 只存在于隔离 execution process，禁止进入 Strategy/Research/Risk/FastAPI core 数据库。Phase 6/7 只替换 execution gateway 层。

## AI 权限矩阵

| Capability | User | Strategy | AI | Risk Engine |
| --- | --- | --- | --- | --- |
| Generate signal | yes | yes | yes | no |
| Create OrderIntent | yes | yes | 受控 | no |
| Approve risk | no | no | no | yes |
| Increase capital authorization | user only | no | no | no |
| Freeze | yes | no | no | yes |
| Unfreeze | user only | no | no | no |
| Enable LIVE | user only | no | no | no |

## Migration 设计

Alembic head 20260722_0010 -> 预计 20260722_0011（本轮不创建）。

预计新增表（可按最小实现裁剪）：paper_accounts、paper_sessions、paper_order_intents、paper_risk_policies、paper_risk_decisions、paper_orders、paper_fills、paper_positions、paper_position_lots、paper_account_snapshots、paper_ledger_entries、paper_audit_events。

append-only：paper_risk_decisions、paper_fills、paper_audit_events、paper_ledger_entries。stateful mutable：paper_accounts、paper_sessions、paper_orders、paper_positions、paper_position_lots、paper_risk_policies(versioned)。

## 测试计划（30–40 项）

Account：create、cash/equity invariant、freeze、user unfreeze。
Session：create、start、pause、resume、advance、stop、illegal transition、restart persistence。
Idempotency：duplicate advance、duplicate manual intent、duplicate order submission。
Risk：cash、order notional、position concentration、total exposure、daily loss、drawdown、frozen account、fail closed。
Execution：T+1、lot、price limit、missing bar、slippage、fee、volume、partial fill。
Transactions：fill failure rollback、position failure rollback、audit failure rollback。
Strategy：strategy-driven intent、no future leakage、strategy error。
Restart：account/session/orders/fills/positions/risk/audit 持久化重读一致。

## 实施计划

5A Domain + Migration（≤2h）、5B Deterministic Risk（≤2h）、5C Shared Execution Kernel + Paper Execution（≤3h）、5D Session Advance + Transactions（≤3h）、5E API（≤2h）、5F /paper UI（≤2h）、5G Recovery / Runtime Smoke / Acceptance（≤2h）。

## Open Questions

1. Paper 初始资金是否允许创建后再人工追加（INITIAL_DEPOSIT 之外的 MANUAL_ADJUSTMENT）？
2. ADVANCE 是否只允许在 RUNNING 状态，还是 PAUSED 下也允许单步推进？
3. 手动 intent 是否允许用户主动 CANCELLED 已 APPROVED/SUBMITTED 订单，还是 MVP 只允许 advance 驱动的生命周期？
