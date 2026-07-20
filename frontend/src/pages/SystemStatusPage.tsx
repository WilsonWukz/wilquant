import { useEffect, useState } from "react";

import { StatusCard } from "../components/StatusCard";
import { fetchReadiness } from "../services/health";
import type { ReadinessResponse } from "../types/health";

type ViewState =
  | { state: "loading" }
  | { state: "ready"; data: ReadinessResponse }
  | { state: "error" };

export function SystemStatusPage() {
  const [view, setView] = useState<ViewState>({ state: "loading" });

  useEffect(() => {
    const controller = new AbortController();
    fetchReadiness(controller.signal)
      .then((data) => setView({ state: "ready", data }))
      .catch((error: unknown) => {
        if (!(error instanceof DOMException && error.name === "AbortError")) {
          setView({ state: "error" });
        }
      });
    return () => controller.abort();
  }, []);

  return (
    <main className="page-shell">
      <header className="hero">
        <div>
          <p className="hero__kicker">PERSONAL A-SHARE QUANT LAB</p>
          <h1>研究环境状态</h1>
          <p className="hero__summary">
            验证本地基础设施是否就绪。当前阶段仅支持研究模式，不包含行情、策略或交易能力。
          </p>
        </div>
        <div className="mode-badge" aria-label="当前运行模式">
          <span>运行模式</span>
          <strong>RESEARCH</strong>
        </div>
      </header>

      {view.state === "loading" && (
        <section className="state-panel state-panel--loading" aria-live="polite">
          <span className="loader" aria-hidden="true" />
          <p>正在检查系统状态…</p>
        </section>
      )}

      {view.state === "error" && (
        <section className="state-panel state-panel--danger" role="alert">
          <p className="state-panel__label">基础设施告警</p>
          <h2>系统尚未就绪</h2>
          <p>无法连接后端健康检查。请确认后端已启动，并查看本地结构化日志。</p>
        </section>
      )}

      {view.state === "ready" && (
        <>
          <section className="state-panel state-panel--success" aria-live="polite">
            <div>
              <p className="state-panel__label">Phase 1 · 基础骨架</p>
              <h2>研究环境已就绪</h2>
            </div>
            <p className="version">应用版本 {view.data.application_version}</p>
          </section>
          <section className="status-grid" aria-label="基础设施组件状态">
            {view.data.components.map((component) => (
              <StatusCard key={component.name} component={component} />
            ))}
          </section>
        </>
      )}

      <footer>
        <span>只读健康检查</span>
        <span aria-hidden="true">·</span>
        <span>无真实数据源</span>
        <span aria-hidden="true">·</span>
        <span>无实盘能力</span>
      </footer>
    </main>
  );
}
