import type { ComponentHealth, ReadinessResponse } from "../types/health";

const GENERIC_ERROR = "无法获取系统状态，请确认后端服务已启动";

function isComponentHealth(value: unknown): value is ComponentHealth {
  if (typeof value !== "object" || value === null) {
    return false;
  }
  const component = value as Record<string, unknown>;
  return (
    (component.name === "sqlite" || component.name === "duckdb") &&
    (component.status === "healthy" || component.status === "unhealthy") &&
    typeof component.message === "string"
  );
}

function isReadinessResponse(value: unknown): value is ReadinessResponse {
  if (typeof value !== "object" || value === null) {
    return false;
  }
  const response = value as Record<string, unknown>;
  return (
    (response.status === "ready" || response.status === "not_ready") &&
    response.run_mode === "RESEARCH" &&
    typeof response.application_version === "string" &&
    Array.isArray(response.components) &&
    response.components.every(isComponentHealth)
  );
}

export async function fetchReadiness(signal?: AbortSignal): Promise<ReadinessResponse> {
  try {
    const response = await fetch("/api/v1/health/ready", {
      headers: { Accept: "application/json" },
      signal,
    });
    if (!response.ok) {
      throw new Error(GENERIC_ERROR);
    }
    const payload: unknown = await response.json();
    if (!isReadinessResponse(payload)) {
      throw new Error(GENERIC_ERROR);
    }
    return payload;
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw error;
    }
    throw new Error(GENERIC_ERROR);
  }
}
