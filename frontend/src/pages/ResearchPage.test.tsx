import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";
import { ResearchPage } from "./ResearchPage";

beforeEach(() => vi.restoreAllMocks());

test("renders research workspace tabs", () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => ({ items: [] }) }));
  render(<ResearchPage />);
  expect(screen.getByText("量化研究工作台")).toBeInTheDocument();
  expect(screen.getByText("实验")).toBeInTheDocument();
});

test("renders experiment list", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => ({ items: [{ id: "e1", name: "exp", hypothesis: "h", market_data_profile_id: null, status: "DRAFT", tags: [], created_at: "2026-01-01", updated_at: "2026-01-01" }] }) }));
  render(<ResearchPage />);
  await waitFor(() => expect(screen.getByText("exp")).toBeInTheDocument());
});
