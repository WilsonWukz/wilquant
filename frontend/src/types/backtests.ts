export type BacktestRun = {
  backtest_run_id: string;
  name: string;
  status: string;
  market_data_profile_id: string;
  market_data_snapshot_fingerprint: string;
  strategy_type: string;
  strategy_fingerprint: string;
  config_fingerprint: string;
  run_input_fingerprint: string;
  initial_cash: string;
  start_date: string;
  end_date: string;
  failure_code?: string | null;
  failure_message?: string | null;
};
