import type { Comparison, Diagnostics, Experiment, JournalEntry, ResearchReport } from "../types/research";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api/v1${path}`, init);
  if (!response.ok) throw new Error("request failed");
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

function jsonInit(method: string, body: unknown): RequestInit {
  return { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
}

export function fetchExperiments(): Promise<Experiment[]> {
  return request<{ items: Experiment[] }>("/experiments").then((r) => r.items);
}

export function createExperiment(payload: Record<string, unknown>): Promise<Experiment> {
  return request<Experiment>("/experiments", jsonInit("POST", payload));
}

export function fetchComparison(experimentId: string): Promise<Comparison> {
  return request<Comparison>(`/experiments/${experimentId}/comparison`);
}

export function fetchDiagnostics(runId: string): Promise<Diagnostics> {
  return request<Diagnostics>(`/backtests/${runId}/diagnostics`);
}

export function fetchJournal(): Promise<JournalEntry[]> {
  return request<{ items: JournalEntry[] }>("/research-journal").then((r) => r.items);
}

export function createJournalEntry(payload: Record<string, unknown>): Promise<JournalEntry> {
  return request<JournalEntry>("/research-journal", jsonInit("POST", payload));
}

export function fetchExperimentReport(experimentId: string): Promise<ResearchReport> {
  return request<ResearchReport>(`/experiments/${experimentId}/research-report`);
}

export function fetchRunReport(runId: string): Promise<ResearchReport> {
  return request<ResearchReport>(`/backtests/${runId}/research-report`);
}
