export type ComponentName = "sqlite" | "duckdb";
export type ComponentStatus = "healthy" | "unhealthy";

export interface ComponentHealth {
  name: ComponentName;
  status: ComponentStatus;
  message: string;
}

export interface ReadinessResponse {
  status: "ready" | "not_ready";
  application_version: string;
  run_mode: "RESEARCH";
  components: ComponentHealth[];
}
