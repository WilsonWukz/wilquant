import { useEffect, useState } from "react";
import { fetchCalendars, fetchCoverage, fetchProfileHealth, fetchProfiles } from "../services/marketData";
import type { Coverage, MarketDataProfile, ProfileHealth, TradingCalendar } from "../types/marketData";

export function MarketDataPage() {
  const [calendars, setCalendars] = useState<TradingCalendar[]>([]);
  const [profiles, setProfiles] = useState<MarketDataProfile[]>([]);
  const [selected, setSelected] = useState<MarketDataProfile | null>(null);
  const [health, setHealth] = useState<ProfileHealth | null>(null);
  const [coverage, setCoverage] = useState<Coverage | null>(null);
  const [error, setError] = useState(false);
  useEffect(() => { Promise.all([fetchCalendars(), fetchProfiles()]).then(([calendarItems, profileItems]) => { setCalendars(calendarItems); setProfiles(profileItems); }).catch(() => setError(true)); }, []);
  async function choose(profile: MarketDataProfile) { setSelected(profile); try { const [healthResult, coverageResult] = await Promise.all([fetchProfileHealth(profile.profile_id), fetchCoverage(profile.profile_id)]); setHealth(healthResult); setCoverage(coverageResult); } catch { setError(true); } }
  return <main className="page-shell"><nav className="page-nav"><a href="/">系统状态</a><span>市场数据</span></nav><header className="hero"><div><p className="hero__kicker">PHASE 2C · MARKET DATA</p><h1>交易日历与市场数据</h1><p className="hero__summary">显式绑定不可变 DatasetVersion 和 TradingCalendarVersion，供后续研究消费。</p></div></header>{error && <section className="state-panel state-panel--danger" role="alert"><h2>加载失败</h2><p>请检查本地后端状态。</p></section>}<section className="status-grid"><article className="status-card"><h2>TradingCalendar</h2>{calendars.map((calendar) => <p key={calendar.calendar_id}>{calendar.name} · {calendar.exchange}</p>)}</article><article className="status-card"><h2>MarketDataProfile</h2>{profiles.map((profile) => <button key={profile.profile_id} type="button" onClick={() => void choose(profile)}>{profile.name} · {profile.status}</button>)}</article></section>{selected && <section className="import-panel"><h2>{selected.name}</h2><p>DatasetVersion: {selected.bars_dataset_version_id}</p><p>CalendarVersion: {selected.calendar_version_id}</p>{health && <p>Health: {health.status}</p>}{coverage && <><p>Coverage: {coverage.status} · 缺失 {coverage.missing_session_count} / {coverage.expected_session_count}</p>{coverage.missing_dates.slice(0, 10).map((day) => <span className="sample-row" key={day}>{day}</span>)}</>}</section>}</main>;
}
