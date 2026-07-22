import { useEffect, useState } from "react";
import { fetchBacktests } from "../services/backtests";
import type { BacktestRun } from "../types/backtests";

export function BacktestsPage() {
  const [runs, setRuns] = useState<BacktestRun[]>([]);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { fetchBacktests().then(setRuns).catch(() => setError("回测列表加载失败")); }, []);
  return (
    <main>
      <h1>回测研究</h1>
      <p>仅支持研究模式与内置确定性策略。</p>
      {error && <p role="alert">{error}</p>}
      {!error && runs.length === 0 && <p>暂无回测记录</p>}
      <table>
        <thead><tr><th>名称</th><th>策略</th><th>状态</th><th>数据快照</th><th>日期</th></tr></thead>
        <tbody>{runs.map((run) => <tr key={run.backtest_run_id}>
          <td>{run.name}</td><td>{run.strategy_type}</td><td>{run.status}</td>
          <td>{run.market_data_snapshot_fingerprint.slice(0, 12)}</td>
          <td>{run.start_date} - {run.end_date}</td>
        </tr>)}</tbody>
      </table>
    </main>
  );
}
