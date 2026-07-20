export interface ImportInspection {
  batch_id: string;
  provider_name: string;
  columns: string[];
  suggested_mapping: Record<string, string>;
  row_count: number;
  file_size: number;
  source_file_hash: string;
}

export interface ImportPreview {
  batch_id: string;
  provider_name: string;
  source_name: string;
  source_file_hash: string;
  status: "PREVIEW_READY";
  row_count: number;
  accepted_count: number;
  rejected_count: number;
  warning_count: number;
  error_category: string | null;
  error_summary: string | null;
  sample_rows: Record<string, string>[];
}

export interface DataQualityIssue {
  row_number: number | null;
  symbol: string | null;
  field_name: string | null;
  severity: "INFO" | "WARNING" | "ERROR" | "FATAL";
  issue_code: string;
  message: string;
  raw_value: string | null;
}

export interface DataQualityIssueList {
  items: DataQualityIssue[];
}
