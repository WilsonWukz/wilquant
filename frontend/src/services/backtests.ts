import type { BacktestRun } from "../types/backtests";

async function get<T>(path: string): Promise<T> {
  const response = await fetch(`/api/v1${path}`);
  if (!response.ok) throw new Error("request failed");
  return response.json() as Promise<T>;
}

export async function fetchBacktests(): Promise<BacktestRun[]> {
  return (await get<{ items: BacktestRun[] }>("/backtests")).items;
}

export async function createBacktest(payload: Record<string, unknown>): Promise<BacktestRun> {
  const response = await fetch("/api/v1/backtests", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) throw new Error("request failed");
  return response.json() as Promise<BacktestRun>;
}
