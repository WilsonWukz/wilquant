export type Experiment = {
  id: string;
  name: string;
  hypothesis: string;
  market_data_profile_id: string | null;
  status: string;
  tags: string[];
  created_at: string;
  updated_at: string;
};

export type ComparabilityCheck = {
  name: string;
  passed: boolean;
  baseline_value: unknown;
  candidate_value: unknown;
};

export type ComparabilityResult = {
  status: string;
  reasons: string[];
  checks: ComparabilityCheck[];
};

export type ComparisonRow = {
  run_id: string;
  role: string;
  label: string | null;
  status: string;
  strategy_name?: string | null;
  strategy_version?: number | null;
  final_equity: string | null;
  total_return: string | null;
  annualized_return: string | null;
  sharpe_ratio: string | null;
  max_drawdown: string | null;
  total_fees: string | null;
  trade_count: number | null;
  comparability?: ComparabilityResult;
  deltas?: Record<string, string | null>;
};

export type Comparison = {
  experiment_id: string;
  baseline_run_id: string | null;
  ranking_allowed: boolean;
  runs: ComparisonRow[];
};

export type Diagnostic = {
  code: string;
  severity: string;
  message: string;
  value: unknown;
};

export type Diagnostics = {
  run_id: string;
  policy_version: string;
  summary: { total: number; warning_count: number; info_count: number };
  diagnostics: Diagnostic[];
  execution: Record<string, unknown>;
  portfolio: Record<string, unknown>;
  cost: Record<string, unknown>;
  data_quality: Record<string, unknown>;
};

export type JournalEntry = {
  id: string;
  title: string;
  entry_type: string;
  content: string;
  tags: string[];
  experiment_id: string | null;
  backtest_run_id: string | null;
  strategy_version_id: string | null;
  created_at: string;
  updated_at: string;
};

export type ResearchReport = {
  report_fingerprint: string;
  generated_at: string;
  [key: string]: unknown;
};
