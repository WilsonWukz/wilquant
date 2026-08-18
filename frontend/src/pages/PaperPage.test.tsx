import { render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import type { PaperSession } from "../types/paper";
import { PaperPage } from "./PaperPage";

afterEach(() => vi.unstubAllGlobals());

const account = {
  id: "a1",
  name: "acct",
  status: "ACTIVE",
  base_currency: "CNY",
  initial_cash: "100000",
  cash: "98000",
  market_value: "2000",
  account_equity: "100000",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

const runningSession: PaperSession = {
  id: "s1",
  name: "sess",
  paper_account_id: "a1",
  market_data_profile_id: "p",
  market_data_snapshot_fingerprint: "f".repeat(64),
  strategy_version_id: null,
  status: "RUNNING",
  replay_start_date: "2026-01-02",
  replay_end_date: null,
  current_session_date: "2026-01-02",
  version: 3,
  execution_config: { fee_policy: {}, slippage_policy: {}, max_volume_participation: null },
  execution_config_fingerprint: "e".repeat(64),
  dataset_version_id: "v1",
  calendar_version_id: "cv1",
  started_at: null,
  paused_at: null,
  stopped_at: null,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

function stubFetch(routes: Record<string, unknown>) {
  const fetchMock = vi.fn((input: RequestInfo | URL) => {
    const url = String(input);
    for (const [key, value] of Object.entries(routes)) {
      if (url.includes(key)) {
        return Promise.resolve(new Response(JSON.stringify(value), { status: 200 }));
      }
    }
    return Promise.resolve(new Response(JSON.stringify({ items: [] }), { status: 200 }));
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function stubAccountAndSession(session = runningSession) {
  return stubFetch({
    "/paper/accounts/a1/risk": { policy_id: "p1", version: 1, fingerprint: "p".repeat(64), name: "p", status: "ACTIVE", version_id: "v1", max_single_order_notional: "1000000", max_single_position_weight: "0.5", max_total_exposure: "1", cash_buffer_ratio: "0.1", max_daily_loss: "0.05", max_drawdown: "0.2", max_open_orders: 10, allowed_security_types: ["EQUITY"] },
    "/paper/accounts/a1": account,
    "/paper/accounts?": { items: [account] },
    "/paper/accounts": { items: [account] },
    "/paper/sessions?account_id=a1": { items: [session] },
    "/paper/sessions/s1": session,
  });
}

test("shows the PAPER simulation warning", async () => {
  stubFetch({ "/paper/accounts": { items: [] } });
  render(<PaperPage />);
  expect(await screen.findByRole("heading", { name: "PAPER · 模拟交易工作台", level: 1 })).toBeInTheDocument();
  expect(screen.getByText("所有资金、订单和成交均为本地模拟，不会发送到真实券商。")).toBeInTheDocument();
  expect(screen.getByText("本地历史回放，非实盘")).toBeInTheDocument();
});

test("shows onboarding when there are no accounts", async () => {
  stubFetch({ "/paper/accounts": { items: [] } });
  render(<PaperPage />);
  expect(await screen.findByText("暂无 PAPER 账户")).toBeInTheDocument();
});

test("renders the account summary", async () => {
  stubAccountAndSession();
  render(<PaperPage />);
  expect(await screen.findByText("现金")).toBeInTheDocument();
  expect(screen.getByText("¥98000.00")).toBeInTheDocument();
  expect(screen.getByText("权益")).toBeInTheDocument();
});

test("renders the session selector", async () => {
  stubAccountAndSession();
  render(<PaperPage />);
  expect(await screen.findByText("选择 Session")).toBeInTheDocument();
  expect(screen.getByText(/sess · RUNNING/)).toBeInTheDocument();
});

test("CREATED session only enables START", async () => {
  stubAccountAndSession({ ...runningSession, status: "CREATED", current_session_date: null, version: 1 });
  render(<PaperPage />);
  const start = await screen.findByRole("button", { name: "START" });
  expect(start).toBeEnabled();
  expect(screen.getByRole("button", { name: "ADVANCE" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "PAUSE" })).toBeDisabled();
});

test("RUNNING session enables PAUSE/ADVANCE/STOP", async () => {
  stubAccountAndSession();
  render(<PaperPage />);
  await screen.findByRole("button", { name: "ADVANCE" });
  expect(screen.getByRole("button", { name: "PAUSE" })).toBeEnabled();
  expect(screen.getByRole("button", { name: "ADVANCE" })).toBeEnabled();
  expect(screen.getByRole("button", { name: "STOP" })).toBeEnabled();
  expect(screen.getByRole("button", { name: "START" })).toBeDisabled();
});

test("PAUSED session enables RESUME/STOP", async () => {
  stubAccountAndSession({ ...runningSession, status: "PAUSED" });
  render(<PaperPage />);
  await screen.findByRole("button", { name: "RESUME" });
  expect(screen.getByRole("button", { name: "RESUME" })).toBeEnabled();
  expect(screen.getByRole("button", { name: "STOP" })).toBeEnabled();
  expect(screen.getByRole("button", { name: "ADVANCE" })).toBeDisabled();
});

test("manual intent is not immediate execution", async () => {
  stubAccountAndSession();
  render(<PaperPage />);
  const warning = await screen.findByText(/手动订单意图不是立即成交/);
  expect(warning).toBeInTheDocument();
  expect(screen.queryByText(/立即买入/)).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "提交买入意图" })).toBeInTheDocument();
});

test("positions render with PnL signs", async () => {
  stubAccountAndSession();
  stubFetch({
    "/paper/accounts/a1/risk": { policy_id: "p1", version: 1, fingerprint: "p".repeat(64), name: "p", status: "ACTIVE", version_id: "v1", max_single_order_notional: "1000000", max_single_position_weight: "0.5", max_total_exposure: "1", cash_buffer_ratio: "0.1", max_daily_loss: "0.05", max_drawdown: "0.2", max_open_orders: 10, allowed_security_types: ["EQUITY"] },
    "/paper/accounts/a1": account,
    "/paper/accounts": { items: [account] },
    "/paper/sessions?account_id=a1": { items: [runningSession] },
    "/paper/sessions/s1": runningSession,
    "/positions": {
      items: [
        { instrument_id: "600000.XSHG", security_type: "EQUITY", symbol: "600000", total_quantity: 100, sellable_quantity: 0, average_cost: "10.2", market_value: "1040", unrealized_pnl: "20", realized_pnl: "0", updated_at: "2026-01-01" },
      ],
    },
  });
  render(<PaperPage />);
  const positionsTab = await screen.findByRole("button", { name: "持仓" });
  positionsTab.click();
  expect(await screen.findByText("600000")).toBeInTheDocument();
  expect(screen.getByText("+¥20.00")).toBeInTheDocument();
});

test("orders render risk rejection", async () => {
  stubAccountAndSession();
  stubFetch({
    "/paper/accounts/a1/risk": { policy_id: "p1", version: 1, fingerprint: "p".repeat(64), name: "p", status: "ACTIVE", version_id: "v1", max_single_order_notional: "1000000", max_single_position_weight: "0.5", max_total_exposure: "1", cash_buffer_ratio: "0.1", max_daily_loss: "0.05", max_drawdown: "0.2", max_open_orders: 10, allowed_security_types: ["EQUITY"] },
    "/paper/accounts/a1": account,
    "/paper/accounts": { items: [account] },
    "/paper/sessions?account_id=a1": { items: [runningSession] },
    "/paper/sessions/s1": runningSession,
    "/orders": {
      items: [
        { id: "o1", client_order_id: "co1", order_intent_id: "i1", risk_decision_id: "d1", instrument_id: "600000.XSHG", side: "BUY", requested_quantity: 100, accepted_quantity: 0, filled_quantity: 0, order_type: "MARKET_ON_OPEN_SIMULATED", limit_price: null, status: "RISK_REJECTED", submitted_session_date: null, execution_session_date: null, reject_reason: "ORDER_NOTIONAL_LIMIT", created_at: "2026-01-01", updated_at: "2026-01-01" },
      ],
    },
  });
  render(<PaperPage />);
  const ordersTab = await screen.findByRole("button", { name: "订单" });
  ordersTab.click();
  expect(await screen.findByText("RISK_REJECTED")).toBeInTheDocument();
  expect(screen.getByText("ORDER_NOTIONAL_LIMIT")).toBeInTheDocument();
});

test("fills render fee detail columns", async () => {
  stubAccountAndSession();
  stubFetch({
    "/paper/accounts/a1/risk": { policy_id: "p1", version: 1, fingerprint: "p".repeat(64), name: "p", status: "ACTIVE", version_id: "v1", max_single_order_notional: "1000000", max_single_position_weight: "0.5", max_total_exposure: "1", cash_buffer_ratio: "0.1", max_daily_loss: "0.05", max_drawdown: "0.2", max_open_orders: 10, allowed_security_types: ["EQUITY"] },
    "/paper/accounts/a1": account,
    "/paper/accounts": { items: [account] },
    "/paper/sessions?account_id=a1": { items: [runningSession] },
    "/paper/sessions/s1": runningSession,
    "/fills": {
      items: [
        { id: "f1", paper_order_id: "o1", instrument_id: "600000.XSHG", side: "BUY", quantity: 100, raw_price: "10.2", slippage: "0", fill_price: "10.2", commission: "5", stamp_tax: "0", transfer_fee: "0.01", total_fee: "5.01", trade_date: "2026-01-05", created_at: "2026-01-01" },
      ],
    },
  });
  render(<PaperPage />);
  const fillsTab = await screen.findByRole("button", { name: "成交" });
  fillsTab.click();
  expect(await screen.findByText("印花税")).toBeInTheDocument();
  expect(screen.getByText("过户费")).toBeInTheDocument();
  expect(screen.getByText("总费用")).toBeInTheDocument();
});

test("freeze and unfreeze follow account status", async () => {
  stubAccountAndSession();
  render(<PaperPage />);
  expect(await screen.findByRole("button", { name: "冻结账户" })).toBeInTheDocument();
});

test("frozen account shows unfreeze", async () => {
  stubFetch({
    "/paper/accounts/a1/risk": { policy_id: "p1", version: 1, fingerprint: "p".repeat(64), name: "p", status: "ACTIVE", version_id: "v1", max_single_order_notional: "1000000", max_single_position_weight: "0.5", max_total_exposure: "1", cash_buffer_ratio: "0.1", max_daily_loss: "0.05", max_drawdown: "0.2", max_open_orders: 10, allowed_security_types: ["EQUITY"] },
    "/paper/accounts/a1": { ...account, status: "FROZEN" },
    "/paper/accounts": { items: [{ ...account, status: "FROZEN" }] },
    "/paper/sessions?account_id=a1": { items: [runningSession] },
    "/paper/sessions/s1": runningSession,
  });
  render(<PaperPage />);
  expect(await screen.findByRole("button", { name: "解除冻结" })).toBeInTheDocument();
});

test("risk decisions render reason labels", async () => {
  stubAccountAndSession();
  stubFetch({
    "/paper/accounts/a1/risk": { policy_id: "p1", version: 1, fingerprint: "p".repeat(64), name: "p", status: "ACTIVE", version_id: "v1", max_single_order_notional: "1000000", max_single_position_weight: "0.5", max_total_exposure: "1", cash_buffer_ratio: "0.1", max_daily_loss: "0.05", max_drawdown: "0.2", max_open_orders: 10, allowed_security_types: ["EQUITY"] },
    "/paper/accounts/a1": account,
    "/paper/accounts": { items: [account] },
    "/paper/sessions?account_id=a1": { items: [runningSession] },
    "/paper/sessions/s1": runningSession,
    "/risk-decisions": {
      items: [
        { id: "d1", order_intent_id: "i1", decision: "REJECT", reason_codes: ["ORDER_NOTIONAL_LIMIT"], risk_policy_version: 1, risk_policy_fingerprint: "p".repeat(64), evaluated_metrics: { estimated_order_notional: "2000" }, evaluated_at: "2026-01-01T00:00:00Z" },
      ],
    },
  });
  render(<PaperPage />);
  const riskTab = await screen.findByRole("button", { name: "风控" });
  riskTab.click();
  expect(await screen.findByText("单笔订单金额超过限制")).toBeInTheDocument();
});

test("audit renders payload safely", async () => {
  stubAccountAndSession();
  stubFetch({
    "/paper/accounts/a1/risk": { policy_id: "p1", version: 1, fingerprint: "p".repeat(64), name: "p", status: "ACTIVE", version_id: "v1", max_single_order_notional: "1000000", max_single_position_weight: "0.5", max_total_exposure: "1", cash_buffer_ratio: "0.1", max_daily_loss: "0.05", max_drawdown: "0.2", max_open_orders: 10, allowed_security_types: ["EQUITY"] },
    "/paper/accounts/a1": account,
    "/paper/accounts": { items: [account] },
    "/paper/sessions?account_id=a1": { items: [runningSession] },
    "/paper/sessions/s1": runningSession,
    "/audit": { items: [{ id: "ev1", event_type: "SESSION_ADVANCED", payload: { resulting_session_date: "2026-01-02" }, created_at: "2026-01-01T00:00:00Z" }] },
  });
  render(<PaperPage />);
  const auditTab = await screen.findByRole("button", { name: "审计" });
  auditTab.click();
  expect(await screen.findByText("推进交易日")).toBeInTheDocument();
  expect(screen.getByText(/resulting_session_date/)).toBeInTheDocument();
});
