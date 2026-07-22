import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";
import { BacktestsPage } from "./BacktestsPage";

beforeEach(() => vi.restoreAllMocks());

test("renders empty backtest state", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => ({ items: [] }) }));
  render(<BacktestsPage />);
  await waitFor(() => expect(screen.getByText("暂无回测记录")).toBeInTheDocument());
});

test("renders backtest snapshot fingerprint", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => ({ items: [{ backtest_run_id: "r1", name: "demo", status: "SUCCEEDED", market_data_profile_id: "p", market_data_snapshot_fingerprint: "a".repeat(64), strategy_type: "BuyAndHold", strategy_fingerprint: "b", config_fingerprint: "c", run_input_fingerprint: "d", initial_cash: "100", start_date: "2026-01-01", end_date: "2026-01-31" }] }) }));
  render(<BacktestsPage />);
  await waitFor(() => expect(screen.getByText("demo")).toBeInTheDocument());
  expect(screen.getByText("aaaaaaaaaaaa")).toBeInTheDocument();
});
