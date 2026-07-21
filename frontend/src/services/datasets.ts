import type { Dataset, DatasetBar, DatasetSummary, DatasetVersion } from "../types/datasets";

const API = "/api/v1";
async function get<T>(path: string): Promise<T> {
  const response = await fetch(`${API}${path}`);
  if (!response.ok) throw new Error("request failed");
  return response.json() as Promise<T>;
}
export async function fetchDatasets(): Promise<Dataset[]> { return (await get<{ items: Dataset[] }>("/datasets")).items; }
export async function fetchVersions(id: string): Promise<DatasetVersion[]> { return (await get<{ items: DatasetVersion[] }>(`/datasets/${id}/versions`)).items; }
export async function fetchSummary(id: string, version: string): Promise<DatasetSummary> { return get(`/datasets/${id}/versions/${version}/summary`); }
export async function fetchBars(id: string, version: string, limit = 100): Promise<DatasetBar[]> { return (await get<{ items: DatasetBar[] }>(`/datasets/${id}/versions/${version}/bars?limit=${limit}`)).items; }
