export type PaperAccount = {
  id: string;
  name: string;
  status: string;
  base_currency: string;
  initial_cash: string;
  cash: string;
  market_value: string;
  account_equity: string;
  created_at: string;
  updated_at: string;
};

export type ExecutionConfig = {
  fee_policy: Record<string, unknown>;
  slippage_policy: Record<string, unknown>;
  max_volume_participation: string | null;
};

export type PaperSession = {
  id: string;
  name: string;
  paper_account_id: string;
  market_data_profile_id: string;
  market_data_snapshot_fingerprint: string;
  strategy_version_id: string | null;
  status: string;
  replay_start_date: string;
  replay_end_date: string | null;
  current_session_date: string | null;
  version: number;
  execution_config: ExecutionConfig;
  execution_config_fingerprint: string;
  dataset_version_id: string | null;
  calendar_version_id: string | null;
  started_at: string | null;
  paused_at: string | null;
  stopped_at: string | null;
  created_at: string;
  updated_at: string;
};

export type PaperAdvanceResult = {
  paper_session_id: string;
  previous_session_date: string | null;
  resulting_session_date: string | null;
  session_version: number;
  executed_order_count: number;
  fill_count: number;
  risk_approved_count: number;
  risk_rejected_count: number;
  created_order_ids: string[];
  cash: string;
  market_value: string;
  account_equity: string;
  snapshot_id: string | null;
  idempotent_replay: boolean;
  no_future_session: boolean;
};

export type PaperIntent = {
  id: string;
  paper_session_id: string;
  source_type: string;
  instrument_id: string;
  side: string;
  quantity: number;
  order_type: string;
  limit_price: string | null;
  signal_session_date: string;
  intended_execution_session: string;
  idempotency_key: string;
  risk_status: string;
  created_at: string;
};

export type PaperOrder = {
  id: string;
  client_order_id: string;
  order_intent_id: string;
  risk_decision_id: string;
  instrument_id: string;
  side: string;
  requested_quantity: number;
  accepted_quantity: number;
  filled_quantity: number;
  order_type: string;
  limit_price: string | null;
  status: string;
  submitted_session_date: string | null;
  execution_session_date: string | null;
  reject_reason: string | null;
  created_at: string;
  updated_at: string;
};

export type PaperFill = {
  id: string;
  paper_order_id: string;
  instrument_id: string;
  side: string;
  quantity: number;
  raw_price: string;
  slippage: string;
  fill_price: string;
  commission: string;
  stamp_tax: string;
  transfer_fee: string;
  total_fee: string;
  trade_date: string;
  created_at: string;
};

export type PaperPosition = {
  instrument_id: string;
  security_type: string | null;
  symbol: string | null;
  total_quantity: number;
  sellable_quantity: number;
  average_cost: string;
  market_value: string;
  unrealized_pnl: string;
  realized_pnl: string;
  updated_at: string;
};

export type PaperEquityPoint = {
  session_date: string;
  cash: string;
  market_value: string;
  equity: string;
  gross_exposure: string;
  daily_pnl: string;
  cumulative_pnl: string;
  drawdown: string;
};

export type PaperAuditEvent = {
  id: string;
  event_type: string;
  payload: Record<string, unknown>;
  created_at: string;
};

export type PaperRiskPolicy = {
  policy_id: string;
  name: string;
  status: string;
  version_id: string;
  version: number;
  fingerprint: string;
  max_single_order_notional: string;
  max_single_position_weight: string;
  max_total_exposure: string;
  cash_buffer_ratio: string;
  max_daily_loss: string;
  max_drawdown: string;
  max_open_orders: number;
  allowed_security_types: string[];
};

export type PaperRiskDecision = {
  id: string;
  order_intent_id: string;
  decision: string;
  reason_codes: string[];
  risk_policy_version: number;
  risk_policy_fingerprint: string;
  evaluated_metrics: Record<string, unknown>;
  evaluated_at: string;
};

export type StrategyDefinition = {
  id: string;
  name: string;
  description: string;
  strategy_type: string;
  status: string;
};

export type StrategyVersion = {
  id: string;
  strategy_definition_id: string;
  version: number;
  strategy_fingerprint: string;
};

export type Instrument = {
  instrument_id: string;
  symbol: string;
  exchange: string;
  name: string;
  security_type: string;
  currency: string;
  lot_size: number;
  price_tick: string;
};

export type ApiError = {
  error_code: string;
  message: string;
};
