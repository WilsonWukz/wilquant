export type TradingCalendar = { calendar_id: string; name: string; market: string; exchange: string };
export type CalendarVersion = { trading_calendar_version_id: string; version: number; status: string; fingerprint: string; session_count: number };
export type MarketDataProfile = { profile_id: string; name: string; market: string; bar_frequency: string; bars_dataset_version_id: string; calendar_version_id: string; status: string };
export type ProfileHealth = { profile_id: string; status: string; bars_dataset_version_id: string; calendar_version_id: string };
export type Coverage = { bar_count: number; expected_session_count: number; missing_session_count: number; missing_dates: string[]; missing_rate: number; status: string };
