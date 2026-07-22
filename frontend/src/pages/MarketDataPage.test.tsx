import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MarketDataPage } from "./MarketDataPage";

describe("MarketDataPage", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.stubGlobal("fetch", vi.fn((url: string) => Promise.resolve({ ok: true, json: async () => url.endsWith("market-calendars") ? { items: [{ calendar_id: "cal", name: "CN", market: "CN_A_SHARE", exchange: "XSHG_XSHE" }] } : { items: [{ profile_id: "p", name: "CN daily", market: "CN_A_SHARE", bar_frequency: "DAILY", bars_dataset_version_id: "v", calendar_version_id: "cv", status: "ACTIVE" }] } })));
  });
  it("loads calendars and profiles", async () => { render(<MarketDataPage />); expect(await screen.findByText("CN daily · ACTIVE")).toBeInTheDocument(); expect(screen.getByText("CN · XSHG_XSHE")).toBeInTheDocument(); });
  it("shows an error when initial data loading fails", async () => { vi.stubGlobal("fetch", vi.fn(() => Promise.reject(new Error("offline")))); render(<MarketDataPage />); expect(await screen.findByRole("alert")).toHaveTextContent("加载失败"); });
});
