export type Dataset = { dataset_id: string; name: string; logical_key: string; frequency: string; adjustment_type: string };
export type DatasetVersion = { dataset_version_id: string; version: number; status: string; row_count: number; warning_count: number; published_at?: string | null };
export type DatasetSummary = { row_count: number; instrument_count: number; file_count: number; min_timestamp?: string; max_timestamp?: string };
export type DatasetBar = { instrument_id: string; trade_date: string; open: string; high: string; low: string; close: string; volume: number };
