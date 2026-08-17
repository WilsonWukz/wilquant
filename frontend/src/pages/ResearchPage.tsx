import { useEffect, useState } from "react";
import {
  createExperiment,
  createJournalEntry,
  fetchComparison,
  fetchDiagnostics,
  fetchExperimentReport,
  fetchExperiments,
  fetchJournal,
} from "../services/research";
import type {
  Comparison,
  Diagnostics,
  Experiment,
  JournalEntry,
  ResearchReport,
} from "../types/research";

type Tab = "experiments" | "comparison" | "diagnostics" | "journal" | "reports";

export function ResearchPage() {
  const [tab, setTab] = useState<Tab>("experiments");
  return (
    <main>
      <h1>量化研究工作台</h1>
      <nav>
        {(["experiments", "comparison", "diagnostics", "journal", "reports"] as Tab[]).map(
          (t) => (
            <button key={t} onClick={() => setTab(t)} aria-pressed={tab === t}>
              {labelOf(t)}
            </button>
          )
        )}
      </nav>
      {tab === "experiments" && <ExperimentsTab />}
      {tab === "comparison" && <ComparisonTab />}
      {tab === "diagnostics" && <DiagnosticsTab />}
      {tab === "journal" && <JournalTab />}
      {tab === "reports" && <ReportsTab />}
    </main>
  );
}

function labelOf(tab: Tab): string {
  return { experiments: "实验", comparison: "比较", diagnostics: "诊断", journal: "日志", reports: "报告" }[tab];
}

function ExperimentsTab() {
  const [experiments, setExperiments] = useState<Experiment[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [hypothesis, setHypothesis] = useState("");
  const reload = () => fetchExperiments().then(setExperiments).catch(() => setError("实验加载失败"));
  useEffect(() => { reload(); }, []);
  const submit = async () => {
    await createExperiment({ name, hypothesis, tags: [] }).catch(() => setError("创建失败"));
    setName("");
    setHypothesis("");
    reload();
  };
  return (
    <section>
      <h2>实验</h2>
      <div><input aria-label="name" value={name} onChange={(e) => setName(e.target.value)} placeholder="名称" />
      <textarea aria-label="hypothesis" value={hypothesis} onChange={(e) => setHypothesis(e.target.value)} placeholder="研究假设" /></div>
      <button onClick={submit}>新建实验</button>
      {error && <p role="alert">{error}</p>}
      <table><thead><tr><th>名称</th><th>状态</th><th>假设</th></tr></thead>
        <tbody>{experiments.map((e) => <tr key={e.id}><td>{e.name}</td><td>{e.status}</td><td>{e.hypothesis}</td></tr>)}</tbody></table>
    </section>
  );
}

function ComparisonTab() {
  const [experimentId, setExperimentId] = useState("");
  const [comparison, setComparison] = useState<Comparison | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = async () => {
    try { setComparison(await fetchComparison(experimentId)); setError(null); } catch { setError("比较加载失败"); }
  };
  return (
    <section>
      <h2>比较</h2>
      <div><input aria-label="experimentId" value={experimentId} onChange={(e) => setExperimentId(e.target.value)} placeholder="实验 ID" />
      <button onClick={load}>加载比较</button></div>
      {error && <p role="alert">{error}</p>}
      {comparison && <ComparisonTable comparison={comparison} />}
    </section>
  );
}

function ComparisonTable({ comparison }: { comparison: Comparison }) {
  const nonStrict = comparison.runs.some((r) => r.comparability && r.comparability.status !== "STRICTLY_COMPARABLE");
  return (
    <div>
      <h3>可比性</h3>
      {comparison.ranking_allowed && !nonStrict ? <p>STRICTLY COMPARABLE</p> : <p>{nonStrict ? "NOT STRICTLY COMPARABLE" : "NOT COMPARABLE"}</p>}
      {comparison.runs.map((r) => r.comparability && r.comparability.reasons.length > 0 && (
        <p key={r.run_id}>{r.comparability.reasons.join(", ")}</p>
      ))}
      <table><thead><tr><th>Run</th><th>角色</th><th>总收益</th><th>Sharpe</th><th>最大回撤</th><th>费用</th><th>成交次数</th></tr></thead>
        <tbody>{comparison.runs.map((r) => <tr key={r.run_id}>
          <td>{r.run_id.slice(0, 8)}</td><td>{r.role}</td><td>{r.total_return ?? "-"}</td><td>{r.sharpe_ratio ?? "-"}</td>
          <td>{r.max_drawdown ?? "-"}</td><td>{r.total_fees ?? "-"}</td><td>{r.trade_count ?? "-"}</td>
        </tr>)}</tbody></table>
    </div>
  );
}

function DiagnosticsTab() {
  const [runId, setRunId] = useState("");
  const [diagnostics, setDiagnostics] = useState<Diagnostics | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = async () => {
    try { setDiagnostics(await fetchDiagnostics(runId)); setError(null); } catch { setError("诊断加载失败"); }
  };
  return (
    <section>
      <h2>诊断</h2>
      <div><input aria-label="runId" value={runId} onChange={(e) => setRunId(e.target.value)} placeholder="Run ID" />
      <button onClick={load}>加载诊断</button></div>
      {error && <p role="alert">{error}</p>}
      {diagnostics && <div><p>策略版本: {diagnostics.policy_version}</p><ul>{diagnostics.diagnostics.map((d) => <li key={d.code}>{d.severity} {d.code}: {d.message}</li>)}</ul></div>}
    </section>
  );
}

function JournalTab() {
  const [entries, setEntries] = useState<JournalEntry[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const reload = () => fetchJournal().then(setEntries).catch(() => setError("日志加载失败"));
  useEffect(() => { reload(); }, []);
  const submit = async () => {
    await createJournalEntry({ title, entry_type: "OBSERVATION", content, tags: [] }).catch(() => setError("创建失败"));
    setTitle("");
    setContent("");
    reload();
  };
  return (
    <section>
      <h2>研究日志</h2>
      <div><input aria-label="title" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="标题" />
      <textarea aria-label="content" value={content} onChange={(e) => setContent(e.target.value)} placeholder="内容" /></div>
      <button onClick={submit}>添加日志</button>
      {error && <p role="alert">{error}</p>}
      <ul>{entries.map((e) => <li key={e.id}><strong>{e.entry_type}</strong> {e.title}: {e.content}</li>)}</ul>
    </section>
  );
}

function ReportsTab() {
  const [experimentId, setExperimentId] = useState("");
  const [report, setReport] = useState<ResearchReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = async () => {
    try { setReport(await fetchExperimentReport(experimentId)); setError(null); } catch { setError("报告加载失败"); }
  };
  const copy = async () => { if (report) await navigator.clipboard.writeText(JSON.stringify(report, null, 2)); };
  return (
    <section>
      <h2>研究报告</h2>
      <div><input aria-label="experimentId" value={experimentId} onChange={(e) => setExperimentId(e.target.value)} placeholder="实验 ID" />
      <button onClick={load}>生成报告</button>{report && <button onClick={copy}>Copy JSON</button>}</div>
      {error && <p role="alert">{error}</p>}
      {report && <div><p>Fingerprint: {report.report_fingerprint}</p><p>Generated: {report.generated_at}</p></div>}
    </section>
  );
}
