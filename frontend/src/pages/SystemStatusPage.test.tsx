import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import * as healthApi from "../services/health";
import type { ReadinessResponse } from "../types/health";
import { SystemStatusPage } from "./SystemStatusPage";

const readyResponse: ReadinessResponse = {
  status: "ready",
  application_version: "0.1.0",
  run_mode: "RESEARCH",
  components: [
    { name: "sqlite", status: "healthy", message: "connection available" },
    { name: "duckdb", status: "healthy", message: "connection available" },
  ],
};

afterEach(() => {
  cleanup();
});

describe("SystemStatusPage", () => {
  it("shows component health when the backend is ready", async () => {
    vi.spyOn(healthApi, "fetchReadiness").mockResolvedValue(readyResponse);

    render(<SystemStatusPage />);

    expect(screen.getByText("正在检查系统状态…")).toBeInTheDocument();
    expect(await screen.findByText("研究环境已就绪")).toBeInTheDocument();
    expect(screen.getByText("SQLite")).toBeInTheDocument();
    expect(screen.getByText("DuckDB")).toBeInTheDocument();
  });

  it("prioritizes the unavailable warning", async () => {
    vi.spyOn(healthApi, "fetchReadiness").mockRejectedValue(new Error("private path"));

    render(<SystemStatusPage />);

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("系统尚未就绪");
    expect(alert).not.toHaveTextContent("private path");
  });
});
