import { useEffect, useState } from "react";
import { fetchBars, fetchDatasets, fetchSummary, fetchVersions } from "../services/datasets";
import type { Dataset, DatasetBar, DatasetSummary, DatasetVersion } from "../types/datasets";

export function DatasetsPage() {
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [selected, setSelected] = useState<Dataset | null>(null);
  const [versions, setVersions] = useState<DatasetVersion[]>([]);
  const [version, setVersion] = useState<DatasetVersion | null>(null);
  const [summary, setSummary] = useState<DatasetSummary | null>(null);
  const [bars, setBars] = useState<DatasetBar[]>([]);
  const [error, setError] = useState(false);
  useEffect(() => { fetchDatasets().then(setDatasets).catch(() => setError(true)); }, []);
  async function choose(dataset: Dataset) { setSelected(dataset); setVersion(null); setSummary(null); setBars([]); try { setVersions(await fetchVersions(dataset.dataset_id)); } catch { setError(true); } }
  async function chooseVersion(item: DatasetVersion) { if (!selected) return; setVersion(item); try { setSummary(await fetchSummary(selected.dataset_id, item.dataset_version_id)); setBars(item.status === "PUBLISHED" ? await fetchBars(selected.dataset_id, item.dataset_version_id) : []); } catch { setError(true); } }
  return <main className="page-shell"><nav className="page-nav"><a href="/">系统状态</a><span>数据集</span></nav><header className="hero"><div><p className="hero__kicker">PHASE 2B · DATASETS</p><h1>数据集发布与只读分析</h1><p className="hero__summary">仅展示 SQLite 已确认发布且文件校验通过的版本。</p></div></header>{error && <section className="state-panel state-panel--danger" role="alert"><h2>加载失败</h2></section>}<section className="status-grid"><article className="status-card"><h2>Dataset</h2>{datasets.map((item) => <button key={item.dataset_id} type="button" onClick={() => void choose(item)}>{item.name} · {item.frequency}</button>)}</article><article className="status-card"><h2>Versions</h2>{selected ? versions.map((item) => <button key={item.dataset_version_id} type="button" onClick={() => void chooseVersion(item)}>{`v${item.version}`} · {item.status} · {item.row_count} rows</button>) : <p>请选择数据集</p>}</article></section>{version && summary && <section className="import-panel"><h2>版本摘要</h2><p>行数 {summary.row_count} · 标的 {summary.instrument_count} · 文件 {summary.file_count}</p><h3>Bars</h3>{bars.map((bar) => <article className="sample-row" key={`${bar.instrument_id}-${bar.trade_date}`}><strong>{bar.instrument_id}</strong><span>{bar.trade_date} 收盘 {bar.close}</span></article>)}</section>}</main>;
}
