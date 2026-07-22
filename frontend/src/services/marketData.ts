import type { Coverage, MarketDataProfile, ProfileHealth, TradingCalendar } from "../types/marketData";

async function get<T>(path: string): Promise<T> {
  const response = await fetch(`/api/v1${path}`);
  if (!response.ok) throw new Error("request failed");
  return response.json() as Promise<T>;
}
export async function fetchCalendars(): Promise<TradingCalendar[]> { return (await get<{ items: TradingCalendar[] }>("/market-calendars")).items; }
export async function fetchProfiles(): Promise<MarketDataProfile[]> { return (await get<{ items: MarketDataProfile[] }>("/market-data/profiles")).items; }
export async function fetchProfileHealth(id: string): Promise<ProfileHealth> { return get(`/market-data/profiles/${id}/health`); }
export async function fetchCoverage(id: string): Promise<Coverage> { return get(`/market-data/profiles/${id}/coverage`); }
