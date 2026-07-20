import { useState } from "react";

import { fetchImportIssues, inspectImport, previewImport } from "../services/dataImports";
import type {
  DataQualityIssue,
  ImportInspection,
  ImportPreview,
} from "../types/dataImports";

export function DataImportPage() {
  const [file, setFile] = useState<File | null>(null);
  const [inspection, setInspection] = useState<ImportInspection | null>(null);
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [issues, setIssues] = useState<DataQualityIssue[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(false);

  async function handleInspect() {
    if (file === null) return;
    setBusy(true);
    setError(false);
    try {
      setInspection(await inspectImport(file));
      setPreview(null);
      setIssues([]);
    } catch {
      setError(true);
    } finally {
      setBusy(false);
    }
  }

  async function handlePreview() {
    if (inspection === null) return;
    setBusy(true);
    setError(false);
    try {
      const result = await previewImport(inspection.batch_id, inspection.suggested_mapping);
      setPreview(result);
      setIssues((await fetchImportIssues(inspection.batch_id)).items);
    } catch {
      setError(true);
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="page-shell import-page">
      <nav className="page-nav" aria-label="主要导航">
        <a href="/">系统状态</a>
        <span>数据导入</span>
      </nav>
      <header className="hero import-hero">
        <div>
          <p className="hero__kicker">PHASE 2A · LOCAL DATA</p>
          <h1>本地行情导入预览</h1>
          <p className="hero__summary">
            检查本地 CSV 或 Parquet，确认字段映射和质量问题。当前不会发布正式数据集。
          </p>
        </div>
      </header>

      <section className="import-panel">
        <label htmlFor="market-data-file">选择 CSV 或 Parquet 文件</label>
        <input
          id="market-data-file"
          type="file"
          accept=".csv,.parquet"
          onChange={(event) => setFile(event.target.files?.[0] ?? null)}
        />
        <button type="button" disabled={file === null || busy} onClick={handleInspect}>
          {busy ? "处理中…" : "检查文件"}
        </button>
      </section>

      {error && (
        <section className="state-panel state-panel--danger" role="alert">
          <h2>导入请求失败</h2>
          <p>请检查文件格式、大小和字段，然后查看本地后端日志。</p>
        </section>
      )}

      {inspection && (
        <section className="import-panel">
          <h2>字段映射</h2>
          <dl className="mapping-list">
            {Object.entries(inspection.suggested_mapping).map(([standard, source]) => (
              <div key={standard}>
                <dt>{standard}</dt>
                <dd>{source}</dd>
              </div>
            ))}
          </dl>
          <p>检测到 {inspection.row_count} 行，SHA-256：{inspection.source_file_hash}</p>
          <button type="button" disabled={busy} onClick={handlePreview}>
            生成预览
          </button>
        </section>
      )}

      {preview && (
        <section className="import-panel" aria-live="polite">
          <h2>预览结果</h2>
          <div className="metric-grid">
            <strong>总行数 {preview.row_count}</strong>
            <strong>接受 {preview.accepted_count}</strong>
            <strong>警告 {preview.warning_count}</strong>
            <strong>拒绝 {preview.rejected_count}</strong>
          </div>
          {preview.sample_rows.map((row, index) => (
            <article className="sample-row" key={`${row.instrument_id}-${index}`}>
              <strong>{row.instrument_id}</strong>
              <span>{row.trade_date}</span>
            </article>
          ))}
          <h3>质量问题</h3>
          {issues.length === 0 ? (
            <p>没有记录到质量问题。</p>
          ) : (
            <ul className="issue-list">
              {issues.map((issue, index) => (
                <li
                  className={
                    issue.severity === "ERROR" || issue.severity === "FATAL"
                      ? "issue--danger"
                      : undefined
                  }
                  key={`${issue.issue_code}-${issue.row_number}-${index}`}
                >
                  <strong>{issue.severity}</strong> 第 {issue.row_number ?? "-"} 行：{issue.message}
                </li>
              ))}
            </ul>
          )}
        </section>
      )}
    </main>
  );
}
