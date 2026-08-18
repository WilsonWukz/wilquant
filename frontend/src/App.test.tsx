import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

import * as healthApi from "./services/health";
import App from "./App";

afterEach(() => {
  cleanup();
  window.history.replaceState({}, "", "/");
});

it("keeps the system status page at root", async () => {
  vi.spyOn(healthApi, "fetchReadiness").mockRejectedValue(new Error("offline"));
  window.history.replaceState({}, "", "/");

  render(<App />);

  expect(await screen.findByText("系统尚未就绪")).toBeInTheDocument();
});

it("routes to the data import page", () => {
  window.history.replaceState({}, "", "/data/import");

  render(<App />);

  expect(screen.getByRole("heading", { name: "本地行情导入预览" })).toBeInTheDocument();
});

it("shows a safe not-found page", () => {
  window.history.replaceState({}, "", "/unknown");

  render(<App />);

  expect(screen.getByRole("heading", { name: "页面不存在" })).toBeInTheDocument();
});

it("routes to the paper page", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(new Response(JSON.stringify({ items: [] }), { status: 200 })),
  );
  window.history.replaceState({}, "", "/paper");

  render(<App />);

  expect(await screen.findByRole("heading", { name: "PAPER · 模拟交易工作台", level: 1 })).toBeInTheDocument();
});
