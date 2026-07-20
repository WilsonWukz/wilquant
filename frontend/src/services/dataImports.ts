import type {
  DataQualityIssueList,
  ImportInspection,
  ImportPreview,
} from "../types/dataImports";

const GENERIC_ERROR = "数据导入请求失败，请检查文件和后端日志";

async function readJson<T>(response: Response): Promise<T> {
  if (!response.ok) {
    throw new Error(GENERIC_ERROR);
  }
  return (await response.json()) as T;
}

export async function inspectImport(file: File): Promise<ImportInspection> {
  const filename = encodeURIComponent(file.name);
  const response = await fetch(`/api/v1/data/imports/inspect?filename=${filename}`, {
    method: "POST",
    headers: { "Content-Type": "application/octet-stream", Accept: "application/json" },
    body: file,
  });
  return readJson<ImportInspection>(response);
}

export async function previewImport(
  batchId: string,
  fieldMapping: Record<string, string>,
): Promise<ImportPreview> {
  const response = await fetch("/api/v1/data/imports/preview", {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify({ batch_id: batchId, field_mapping: fieldMapping }),
  });
  return readJson<ImportPreview>(response);
}

export async function fetchImportIssues(batchId: string): Promise<DataQualityIssueList> {
  const response = await fetch(`/api/v1/data/imports/${encodeURIComponent(batchId)}/issues`, {
    headers: { Accept: "application/json" },
  });
  return readJson<DataQualityIssueList>(response);
}
