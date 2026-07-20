import type { ComponentHealth, ComponentName } from "../types/health";

const COMPONENT_LABELS: Record<ComponentName, string> = {
  sqlite: "SQLite",
  duckdb: "DuckDB",
};

interface StatusCardProps {
  component: ComponentHealth;
}

export function StatusCard({ component }: StatusCardProps) {
  const isHealthy = component.status === "healthy";
  return (
    <article className={`status-card status-card--${component.status}`}>
      <div className="status-card__header">
        <span className="status-card__eyebrow">本地基础设施</span>
        <span className="status-pill" aria-label={isHealthy ? "状态正常" : "状态异常"}>
          <span className="status-pill__dot" aria-hidden="true" />
          {isHealthy ? "正常" : "异常"}
        </span>
      </div>
      <h2>{COMPONENT_LABELS[component.name]}</h2>
      <p>{isHealthy ? "连接与基础查询均可用" : "依赖检查未通过，请查看后端日志"}</p>
    </article>
  );
}
