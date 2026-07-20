import { afterEach, describe, expect, it, vi } from "vitest";

import { fetchReadiness } from "./health";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("fetchReadiness", () => {
  it("returns the typed readiness payload", async () => {
    const payload = {
      status: "ready",
      application_version: "0.1.0",
      run_mode: "RESEARCH",
      components: [
        { name: "sqlite", status: "healthy", message: "connection available" },
        { name: "duckdb", status: "healthy", message: "connection available" },
      ],
    };
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response(JSON.stringify(payload), { status: 200 })),
    );

    await expect(fetchReadiness()).resolves.toEqual(payload);
  });

  it("replaces server details with a generic message", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response("D:/private/database", { status: 503 })),
    );

    await expect(fetchReadiness()).rejects.toThrow("无法获取系统状态，请确认后端服务已启动");
    await expect(fetchReadiness()).rejects.not.toThrow("private");
  });
});
