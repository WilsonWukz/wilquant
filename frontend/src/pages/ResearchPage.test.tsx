import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";
import { ResearchPage } from "./ResearchPage";

beforeEach(() => vi.restoreAllMocks());

test("renders research workspace tabs with default selection", () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => ({ items: [] }) }));
  render(<ResearchPage />);
  expect(screen.getByRole("heading", { name: "量化研究工作台", level: 1 })).toBeInTheDocument();
  for (const label of ["实验", "比较", "诊断", "日志", "报告"]) {
    expect(screen.getByRole("button", { name: label })).toBeInTheDocument();
  }
  expect(screen.getByRole("button", { name: "实验" })).toHaveAttribute("aria-pressed", "true");
  expect(screen.getByRole("button", { name: "比较" })).toHaveAttribute("aria-pressed", "false");
});

test("renders experiment list", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => ({ items: [{ id: "e1", name: "exp", hypothesis: "h", market_data_profile_id: null, status: "DRAFT", tags: [], created_at: "2026-01-01", updated_at: "2026-01-01" }] }) }));
  render(<ResearchPage />);
  await waitFor(() => expect(screen.getByText("exp")).toBeInTheDocument());
});
