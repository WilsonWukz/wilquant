import { useEffect, useState } from "react";
import {
  advanceSession,
  cancelOrder,
  createAccount,
  createManualIntent,
  createRiskPolicy,
  createSession,
  fetchAccounts,
  fetchAccount,
  fetchAudit,
  fetchEquity,
  fetchFills,
  fetchInstruments,
  fetchOrders,
  fetchPositions,
  fetchRiskDecisions,
  fetchRiskPolicy,
  fetchSessions,
  fetchSession,
  fetchStrategies,
  fetchStrategyVersions,
  freezeAccount,
  patchRiskPolicy,
  pauseSession,
  resumeSession,
  startSession,
  stopSession,
  unfreezeAccount,
  type RiskPolicyLimits,
  type SessionCreatePayload,
} from "../services/paper";
import { fetchProfiles } from "../services/marketData";
import type {
  ApiError,
  Instrument,
  PaperAccount,
  PaperAdvanceResult,
  PaperAuditEvent,
  PaperEquityPoint,
  PaperFill,
  PaperOrder,
  PaperPosition,
  PaperRiskDecision,
  PaperRiskPolicy,
  PaperSession,
  StrategyDefinition,
  StrategyVersion,
} from "../types/paper";
import type { MarketDataProfile } from "../types/marketData";

type Tab = "overview" | "positions" | "orders" | "fills" | "risk" | "audit";

const TAB_LABELS: Record<Tab, string> = {
  overview: "概览",
  positions: "持仓",
  orders: "订单",
  fills: "成交",
  risk: "风控",
  audit: "审计",
};

const EVENT_LABELS: Record<string, string> = {
  SESSION_CREATED: "创建会话",
  SESSION_STARTED: "启动会话",
  SESSION_RESUMED: "恢复会话",
  SESSION_PAUSED: "暂停会话",
  SESSION_STOPPED: "停止会话",
  SESSION_ADVANCED: "推进交易日",
  SESSION_FAILED: "会话失败",
  INTENT_CREATED: "创建订单意图",
  RISK_APPROVED: "风控通过",
  RISK_REJECTED: "风控拒绝",
  ORDER_CREATED: "创建订单",
  ORDER_SUBMITTED: "提交订单",
  ORDER_FILLED: "订单成交",
  ORDER_PARTIALLY_FILLED: "订单部分成交",
  ORDER_EXPIRED: "订单过期",
  ORDER_CANCELLED: "订单取消",
  ORDER_REJECTED: "订单拒绝",
  ACCOUNT_FROZEN: "账户冻结",
  ACCOUNT_UNFROZEN: "账户解冻",
  ACCOUNT_CREATED: "创建账户",
};

const REASON_LABELS: Record<string, string> = {
  ACCOUNT_FROZEN: "账户已冻结",
  SESSION_NOT_RUNNING: "会话未运行",
  SECURITY_NOT_ALLOWED: "证券类型不允许",
  ORDER_NOTIONAL_LIMIT: "单笔订单金额超过限制",
  CASH_BUFFER_LIMIT: "现金缓冲不足",
  POSITION_CONCENTRATION_LIMIT: "单标的仓位超限",
  TOTAL_EXPOSURE_LIMIT: "总敞口超限",
  OPEN_ORDER_LIMIT: "未完成订单数量超限",
  DAILY_LOSS_LIMIT: "当日亏损超限",
  DRAWDOWN_LIMIT: "回撤超限",
};

function isApiError(error: unknown): error is ApiError {
  return typeof error === "object" && error !== null && "error_code" in error && "message" in error;
}

function apiMessage(error: unknown): string {
  if (isApiError(error)) return error.message + " (" + error.error_code + ")";
  return "操作失败";
}

function pctToRatio(pct: string): string {
  const n = Number(pct);
  return Number.isFinite(n) ? String(n / 100) : "0";
}

function ratioToPct(ratio: string): string {
  const n = Number(ratio);
  return Number.isFinite(n) ? String(n * 100) : "0";
}

function money(value: string): string {
  const n = Number(value);
  return "¥" + (Number.isFinite(n) ? n.toFixed(2) : "0.00");
}

function signedMoney(value: string): string {
  const n = Number(value);
  if (!Number.isFinite(n)) return "¥0.00";
  return (n >= 0 ? "+" : "-") + "¥" + Math.abs(n).toFixed(2);
}

export function PaperPage() {
  const [accounts, setAccounts] = useState<PaperAccount[]>([]);
  const [accountId, setAccountId] = useState("");
  const [account, setAccount] = useState<PaperAccount | null>(null);
  const [policy, setPolicy] = useState<PaperRiskPolicy | null>(null);
  const [sessions, setSessions] = useState<PaperSession[]>([]);
  const [sessionId, setSessionId] = useState("");
  const [session, setSession] = useState<PaperSession | null>(null);
  const [tab, setTab] = useState<Tab>("overview");
  const [refreshKey, setRefreshKey] = useState(0);
  const [notice, setNotice] = useState<string | null>(null);

  const reloadAccounts = () => {
    fetchAccounts()
      .then((items) => {
        setAccounts(items);
        if (items.length > 0 && !items.some((a) => a.id === accountId)) {
          setAccountId(items[0].id);
        }
      })
      .catch((e) => setNotice(apiMessage(e)));
  };

  useEffect(() => {
    reloadAccounts();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!accountId) {
      setAccount(null);
      setPolicy(null);
      setSessions([]);
      setSessionId("");
      return;
    }
    fetchAccount(accountId).then(setAccount).catch((e) => setNotice(apiMessage(e)));
    fetchRiskPolicy(accountId).then(setPolicy).catch(() => setPolicy(null));
    fetchSessions({ account_id: accountId }).then(setSessions).catch(() => setSessions([]));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [accountId, refreshKey]);

  useEffect(() => {
    if (!sessionId) {
      setSession(null);
      return;
    }
    fetchSession(sessionId).then(setSession).catch((e) => setNotice(apiMessage(e)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId, refreshKey]);

  useEffect(() => {
    if (sessions.length > 0 && !sessions.some((s) => s.id === sessionId)) {
      setSessionId(sessions[0].id);
    }
    if (sessions.length === 0) setSessionId("");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessions]);

  const refresh = () => setRefreshKey((k) => k + 1);

  return (
    <main className="page-shell">
      <header className="hero">
        <div>
          <p className="hero__kicker">PHASE 5 · PAPER TRADING</p>
          <h1>PAPER · 模拟交易工作台</h1>
          <p className="hero__summary">所有资金、订单和成交均为本地模拟，不会发送到真实券商。</p>
        </div>
        <div className="mode-badge" aria-label="当前运行模式">
          <span>运行模式</span>
          <strong>PAPER</strong>
        </div>
      </header>

      <section className="state-panel state-panel--success" aria-live="polite">
        <div>
          <p className="state-panel__label">PAPER · 模拟交易</p>
          <h2>本地历史回放，非实盘</h2>
        </div>
        <p className="version">不发送真实券商订单 · 不涉及真实资金</p>
      </section>

      {notice && (
        <section className="state-panel state-panel--danger" role="alert">
          <h2>操作提示</h2>
          <p>{notice}</p>
          <button type="button" onClick={() => setNotice(null)}>关闭</button>
        </section>
      )}

      {accounts.length === 0 ? (
        <Onboarding />
      ) : (
        <>
          <AccountPanel
            accounts={accounts}
            accountId={accountId}
            account={account}
            onSelect={setAccountId}
            onCreate={reloadAccounts}
            onRefresh={refresh}
          />
          {account && (
            <RiskPolicyPanel account={account} policy={policy} onChanged={refresh} onNotice={setNotice} />
          )}
          <SessionPanel
            accountId={accountId}
            sessions={sessions}
            sessionId={sessionId}
            onSelect={setSessionId}
            onCreate={refresh}
            onNotice={setNotice}
          />
          {session && <SessionControls session={session} onChanged={refresh} onNotice={setNotice} />}
          {session && session.status === "RUNNING" && session.current_session_date != null && (
            <ManualIntentPanel session={session} onCreated={refresh} onNotice={setNotice} />
          )}
          <nav aria-label="PAPER 数据视图">
            {(Object.keys(TAB_LABELS) as Tab[]).map((t) => (
              <button key={t} onClick={() => setTab(t)} aria-pressed={tab === t}>
                {TAB_LABELS[t]}
              </button>
            ))}
          </nav>
          {tab === "overview" && session && (
            <OverviewTab
              session={session}
              account={account}
              policy={policy}
              refreshKey={refreshKey}
              onNotice={setNotice}
            />
          )}
          {tab === "positions" && session && <PositionsTab session={session} refreshKey={refreshKey} />}
          {tab === "orders" && session && (
            <OrdersTab session={session} refreshKey={refreshKey} onChanged={refresh} onNotice={setNotice} />
          )}
          {tab === "fills" && session && <FillsTab session={session} refreshKey={refreshKey} />}
          {tab === "risk" && session && <RiskTab session={session} policy={policy} refreshKey={refreshKey} />}
          {tab === "audit" && session && <AuditTab session={session} refreshKey={refreshKey} />}
        </>
      )}
    </main>
  );
}

function Onboarding() {
  return (
    <section className="state-panel">
      <div>
        <h2>暂无 PAPER 账户</h2>
        <p>请先创建账户 → 配置风控 → 创建会话 → Start 并 Advance。</p>
      </div>
    </section>
  );
}

function AccountPanel({
  accounts,
  accountId,
  account,
  onSelect,
  onCreate,
  onRefresh,
}: {
  accounts: PaperAccount[];
  accountId: string;
  account: PaperAccount | null;
  onSelect: (id: string) => void;
  onCreate: () => void;
  onRefresh: () => void;
}) {
  const [name, setName] = useState("");
  const [initialCash, setInitialCash] = useState("100000");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      const created = await createAccount({ name, initial_cash: initialCash, base_currency: "CNY" });
      setName("");
      onCreate();
      onSelect(created.id);
    } catch (e) {
      setError(apiMessage(e));
    } finally {
      setBusy(false);
    }
  };

  const freeze = async () => {
    if (!accountId) return;
    setBusy(true);
    try {
      await freezeAccount(accountId);
      onRefresh();
    } catch (e) {
      setError(apiMessage(e));
    } finally {
      setBusy(false);
    }
  };

  const unfreeze = async () => {
    if (!accountId) return;
    setBusy(true);
    try {
      await unfreezeAccount(accountId);
      onRefresh();
    } catch (e) {
      setError(apiMessage(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="import-panel">
      <h2>PAPER 账户</h2>
      <label>
        选择账户
        <select value={accountId} onChange={(e) => onSelect(e.target.value)}>
          {accounts.map((a) => (
            <option key={a.id} value={a.id}>
              {a.name} · {a.status}
            </option>
          ))}
        </select>
      </label>
      {account && (
        <div className="metric-grid" aria-label="账户摘要">
          <div>
            <strong>{money(account.cash)}</strong>
            <span>现金</span>
          </div>
          <div>
            <strong>{money(account.market_value)}</strong>
            <span>市值</span>
          </div>
          <div>
            <strong>{money(account.account_equity)}</strong>
            <span>权益</span>
          </div>
          <div>
            <strong>{money(account.initial_cash)}</strong>
            <span>初始资金</span>
          </div>
          <div>
            <strong>{account.status}</strong>
            <span>账户状态</span>
          </div>
        </div>
      )}
      {account && account.status === "ACTIVE" && (
        <button type="button" onClick={freeze} disabled={busy}>冻结账户</button>
      )}
      {account && account.status === "FROZEN" && (
        <button type="button" onClick={unfreeze} disabled={busy}>解除冻结</button>
      )}
      <div>
        <input aria-label="新账户名称" value={name} onChange={(e) => setName(e.target.value)} placeholder="账户名称" />
        <input aria-label="初始资金" value={initialCash} onChange={(e) => setInitialCash(e.target.value)} placeholder="初始资金" />
        <button type="button" onClick={submit} disabled={busy || !name || Number(initialCash) <= 0}>创建账户</button>
      </div>
      {error && <p role="alert">{error}</p>}
    </section>
  );
}

const DEFAULT_LIMITS: RiskPolicyLimits = {
  max_single_order_notional: "1000000",
  max_single_position_weight: "0.5",
  max_total_exposure: "1",
  cash_buffer_ratio: "0.1",
  max_daily_loss: "0.05",
  max_drawdown: "0.2",
  max_open_orders: 10,
  allowed_security_types: ["EQUITY"],
};

function RiskPolicyPanel({
  account,
  policy,
  onChanged,
  onNotice,
}: {
  account: PaperAccount;
  policy: PaperRiskPolicy | null;
  onChanged: () => void;
  onNotice: (msg: string) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [maxDrawdown, setMaxDrawdown] = useState("20");

  const create = async () => {
    setBusy(true);
    try {
      await createRiskPolicy(account.id, { name: "默认风控", ...DEFAULT_LIMITS });
      onChanged();
    } catch (e) {
      onNotice(apiMessage(e));
    } finally {
      setBusy(false);
    }
  };

  const patch = async () => {
    setBusy(true);
    try {
      await patchRiskPolicy(account.id, { max_drawdown: pctToRatio(maxDrawdown) });
      onChanged();
    } catch (e) {
      onNotice(apiMessage(e));
    } finally {
      setBusy(false);
    }
  };

  if (!policy) {
    return (
      <section className="state-panel state-panel--danger" role="alert">
        <div>
          <h2>尚未配置风控策略</h2>
          <p>该账户没有风控策略，无法创建 Session 与推进。</p>
        </div>
        <button type="button" onClick={create} disabled={busy}>配置风控</button>
      </section>
    );
  }

  return (
    <section className="import-panel">
      <h2>风控策略</h2>
      <p>Policy version {policy.version} · Fingerprint {policy.fingerprint.slice(0, 12)}…</p>
      <p>
        单笔订单金额 {money(policy.max_single_order_notional)} · 单标的权重 {ratioToPct(policy.max_single_position_weight)}%
        · 总敞口 {ratioToPct(policy.max_total_exposure)}% · 最大回撤 {ratioToPct(policy.max_drawdown)}%
      </p>
      <div>
        <label>
          最大回撤 (%)（创建新版本）
          <input aria-label="最大回撤百分比" value={maxDrawdown} onChange={(e) => setMaxDrawdown(e.target.value)} />
        </label>
        <button type="button" onClick={patch} disabled={busy}>创建新风控版本</button>
      </div>
      <p className="version">修改会创建新的不可变 RiskPolicyVersion，历史 RiskDecision 仍引用旧版本。</p>
    </section>
  );
}

function SessionPanel({
  accountId,
  sessions,
  sessionId,
  onSelect,
  onCreate,
  onNotice,
}: {
  accountId: string;
  sessions: PaperSession[];
  sessionId: string;
  onSelect: (id: string) => void;
  onCreate: () => void;
  onNotice: (msg: string) => void;
}) {
  const [showForm, setShowForm] = useState(false);
  return (
    <section className="import-panel">
      <h2>PAPER Session</h2>
      <label>
        选择 Session
        <select value={sessionId} onChange={(e) => onSelect(e.target.value)}>
          {sessions.map((s) => (
            <option key={s.id} value={s.id}>
              {s.name} · {s.status} · {s.current_session_date ?? "未推进"}
            </option>
          ))}
        </select>
      </label>
      {sessions.length === 0 && <p>暂无 Session</p>}
      <button type="button" onClick={() => setShowForm((v) => !v)} aria-expanded={showForm}>
        {showForm ? "收起" : "新建 Session"}
      </button>
      {showForm && (
        <SessionCreateForm
          accountId={accountId}
          onCreated={() => {
            setShowForm(false);
            onCreate();
          }}
          onNotice={onNotice}
        />
      )}
    </section>
  );
}

function SessionCreateForm({
  accountId,
  onCreated,
  onNotice,
}: {
  accountId: string;
  onCreated: () => void;
  onNotice: (msg: string) => void;
}) {
  const [name, setName] = useState("");
  const [profiles, setProfiles] = useState<MarketDataProfile[]>([]);
  const [profileId, setProfileId] = useState("");
  const [mode, setMode] = useState<"manual" | "strategy">("manual");
  const [strategies, setStrategies] = useState<StrategyDefinition[]>([]);
  const [strategyDefId, setStrategyDefId] = useState("");
  const [strategyVersions, setStrategyVersions] = useState<StrategyVersion[]>([]);
  const [strategyVersionId, setStrategyVersionId] = useState("");
  const [replayStart, setReplayStart] = useState("2026-01-02");
  const [replayEnd, setReplayEnd] = useState("");
  const [maxVolume, setMaxVolume] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    fetchProfiles().then(setProfiles).catch(() => setProfiles([]));
    fetchStrategies().then(setStrategies).catch(() => setStrategies([]));
  }, []);

  useEffect(() => {
    if (strategyDefId) {
      fetchStrategyVersions(strategyDefId).then(setStrategyVersions).catch(() => setStrategyVersions([]));
    } else {
      setStrategyVersions([]);
    }
  }, [strategyDefId]);

  const submit = async () => {
    setBusy(true);
    try {
      const payload: SessionCreatePayload = {
        name,
        paper_account_id: accountId,
        market_data_profile_id: profileId,
        strategy_version_id: mode === "strategy" ? strategyVersionId : null,
        replay_start_date: replayStart,
        replay_end_date: replayEnd || null,
        execution_config: {
          fee_policy: {},
          slippage_policy: {},
          max_volume_participation: maxVolume || null,
        },
      };
      await createSession(payload);
      onCreated();
    } catch (e) {
      onNotice(apiMessage(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div>
      <input aria-label="Session 名称" value={name} onChange={(e) => setName(e.target.value)} placeholder="Session 名称" />
      <label>
        MarketDataProfile
        <select value={profileId} onChange={(e) => setProfileId(e.target.value)}>
          <option value="">选择 Profile</option>
          {profiles.map((p) => (
            <option key={p.profile_id} value={p.profile_id}>
              {p.name} · {p.status} · DS {p.bars_dataset_version_id.slice(0, 8)}
            </option>
          ))}
        </select>
      </label>
      <fieldset>
        <legend>运行模式</legend>
        <label>
          <input type="radio" name="mode" checked={mode === "manual"} onChange={() => setMode("manual")} />
          仅手动订单
        </label>
        <label>
          <input type="radio" name="mode" checked={mode === "strategy"} onChange={() => setMode("strategy")} />
          策略驱动
        </label>
      </fieldset>
      {mode === "strategy" && (
        <>
          <label>
            策略
            <select value={strategyDefId} onChange={(e) => setStrategyDefId(e.target.value)}>
              <option value="">选择策略</option>
              {strategies.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name} · {s.strategy_type}
                </option>
              ))}
            </select>
          </label>
          <label>
            策略版本
            <select value={strategyVersionId} onChange={(e) => setStrategyVersionId(e.target.value)}>
              <option value="">选择版本</option>
              {strategyVersions.map((v) => (
                <option key={v.id} value={v.id}>
                  v{v.version} · {v.strategy_fingerprint.slice(0, 8)}
                </option>
              ))}
            </select>
          </label>
        </>
      )}
      <label>
        Replay 开始日期（历史回放，非真实时钟）
        <input aria-label="Replay 开始日期" value={replayStart} onChange={(e) => setReplayStart(e.target.value)} />
      </label>
      <label>
        Replay 结束日期（可选）
        <input aria-label="Replay 结束日期" value={replayEnd} onChange={(e) => setReplayEnd(e.target.value)} />
      </label>
      <label>
        最大成交量参与比例（0-1，可选）
        <input aria-label="最大成交量参与" value={maxVolume} onChange={(e) => setMaxVolume(e.target.value)} />
      </label>
      <p className="version">创建 Session 后，该 Execution Config 被冻结，不会随风控策略修改而变化。</p>
      <button
        type="button"
        onClick={submit}
        disabled={busy || !name || !profileId || (mode === "strategy" && !strategyVersionId)}
      >
        创建 Session
      </button>
    </div>
  );
}

function SessionControls({
  session,
  onChanged,
  onNotice,
}: {
  session: PaperSession;
  onChanged: () => void;
  onNotice: (msg: string) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [advanceResult, setAdvanceResult] = useState<PaperAdvanceResult | null>(null);
  const [advanceBusy, setAdvanceBusy] = useState(false);

  const status = session.status;
  const canStart = status === "CREATED";
  const canPause = status === "RUNNING";
  const canResume = status === "PAUSED";
  const canStop = status === "RUNNING" || status === "PAUSED";
  const canAdvance = status === "RUNNING";

  const run = async (action: () => Promise<unknown>) => {
    setBusy(true);
    try {
      await action();
      onChanged();
    } catch (e) {
      if (isApiError(e) && e.error_code === "SESSION_VERSION_CONFLICT") {
        onNotice("会话状态已被其他操作更新，请确认最新状态后重试。");
        onChanged();
      } else {
        onNotice(apiMessage(e));
      }
    } finally {
      setBusy(false);
    }
  };

  const advance = async () => {
    setAdvanceBusy(true);
    setAdvanceResult(null);
    const key = crypto.randomUUID();
    try {
      const result = await advanceSession(session.id, {
        idempotency_key: key,
        expected_version: session.version,
        expected_current_session_date: session.current_session_date,
      });
      setAdvanceResult(result);
      onChanged();
    } catch (e) {
      if (isApiError(e) && e.error_code === "SESSION_VERSION_CONFLICT") {
        onNotice("会话状态已被其他操作更新，请确认最新状态后重试。");
        onChanged();
      } else {
        onNotice(apiMessage(e));
      }
    } finally {
      setAdvanceBusy(false);
    }
  };

  return (
    <section className="import-panel">
      <h2>Session 控制</h2>
      <p>
        状态：<strong>{session.status}</strong> · 当前交易日：{session.current_session_date ?? "无"} · 版本 {session.version}
      </p>
      {session.status === "FAILED" && <p role="alert">会话已失败，禁止继续推进。</p>}
      <div>
        <button type="button" onClick={() => run(() => startSession(session.id, session.version))} disabled={busy || !canStart}>
          START
        </button>
        <button type="button" onClick={() => run(() => pauseSession(session.id, session.version))} disabled={busy || !canPause}>
          PAUSE
        </button>
        <button type="button" onClick={() => run(() => resumeSession(session.id, session.version))} disabled={busy || !canResume}>
          RESUME
        </button>
        <button type="button" onClick={advance} disabled={advanceBusy || !canAdvance}>
          {advanceBusy ? "推进中…" : "ADVANCE"}
        </button>
        <button type="button" onClick={() => run(() => stopSession(session.id, session.version))} disabled={busy || !canStop}>
          STOP
        </button>
      </div>
      {advanceResult && (
        <div>
          <p>
            Trading Session: {advanceResult.resulting_session_date ?? "-"}
            {advanceResult.idempotent_replay && "（该推进请求已执行过，本次返回原结果。）"}
          </p>
          <p>
            执行订单 {advanceResult.executed_order_count} · 成交 {advanceResult.fill_count} · 风控通过{" "}
            {advanceResult.risk_approved_count} · 风控拒绝 {advanceResult.risk_rejected_count}
          </p>
          <p>
            现金 {money(advanceResult.cash)} · 市值 {money(advanceResult.market_value)} · 权益 {money(advanceResult.account_equity)}
          </p>
        </div>
      )}
    </section>
  );
}

function ManualIntentPanel({
  session,
  onCreated,
  onNotice,
}: {
  session: PaperSession;
  onCreated: () => void;
  onNotice: (msg: string) => void;
}) {
  const [instruments, setInstruments] = useState<Instrument[]>([]);
  const [instrumentId, setInstrumentId] = useState("");
  const [side, setSide] = useState<"BUY" | "SELL">("BUY");
  const [quantity, setQuantity] = useState("100");
  const [limitPrice, setLimitPrice] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    fetchInstruments(session.market_data_profile_id).then(setInstruments).catch(() => setInstruments([]));
  }, [session.market_data_profile_id]);

  const submit = async () => {
    setBusy(true);
    try {
      await createManualIntent(session.id, {
        idempotency_key: crypto.randomUUID(),
        instrument_id: instrumentId,
        side,
        quantity: Number(quantity),
        order_type: "MARKET_ON_OPEN_SIMULATED",
        limit_price: limitPrice || null,
        reason: reason || null,
        metadata: {},
      });
      onCreated();
      setInstrumentId("");
      setQuantity("100");
      setLimitPrice("");
      setReason("");
    } catch (e) {
      onNotice(apiMessage(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="import-panel">
      <h2>手动订单意图</h2>
      <p className="version">
        手动订单意图不是立即成交，会在后续 PAPER 推进中经过风控，并按下一个可执行 TradingSession 处理。
      </p>
      <label>
        标的
        <select value={instrumentId} onChange={(e) => setInstrumentId(e.target.value)}>
          <option value="">选择标的</option>
          {instruments.map((i) => (
            <option key={i.instrument_id} value={i.instrument_id}>
              {i.symbol} · {i.exchange} · {i.security_type}
            </option>
          ))}
        </select>
      </label>
      <label>
        方向
        <select value={side} onChange={(e) => setSide(e.target.value as "BUY" | "SELL")}>
          <option value="BUY">BUY</option>
          <option value="SELL">SELL</option>
        </select>
      </label>
      <input aria-label="数量" value={quantity} onChange={(e) => setQuantity(e.target.value)} placeholder="数量" />
      <input aria-label="限价" value={limitPrice} onChange={(e) => setLimitPrice(e.target.value)} placeholder="限价（可选）" />
      <input aria-label="原因" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="原因（可选）" />
      <button type="button" onClick={submit} disabled={busy || !instrumentId || Number(quantity) <= 0}>
        {side === "BUY" ? "提交买入意图" : "提交卖出意图"}
      </button>
    </section>
  );
}

function OverviewTab({
  session,
  account,
  policy,
  refreshKey,
  onNotice,
}: {
  session: PaperSession;
  account: PaperAccount | null;
  policy: PaperRiskPolicy | null;
  refreshKey: number;
  onNotice: (message: string) => void;
}) {
  const [equity, setEquity] = useState<PaperEquityPoint[]>([]);
  useEffect(() => {
    fetchEquity(session.id)
      .then(setEquity)
      .catch((error) => {
        setEquity([]);
        onNotice(apiMessage(error));
      });
  }, [session.id, refreshKey, onNotice]);

  return (
    <section>
      <h2>概览</h2>
      <div className="metric-grid">
        <div>
          <strong>{account ? money(account.initial_cash) : "-"}</strong>
          <span>初始资金</span>
        </div>
        <div>
          <strong>{account ? money(account.cash) : "-"}</strong>
          <span>现金</span>
        </div>
        <div>
          <strong>{account ? money(account.market_value) : "-"}</strong>
          <span>市值</span>
        </div>
        <div>
          <strong>{account ? money(account.account_equity) : "-"}</strong>
          <span>权益</span>
        </div>
      </div>
      <h3>Session</h3>
      <p>
        状态 {session.status} · Replay {session.replay_start_date} - {session.replay_end_date ?? "末端"} · 版本 {session.version}
      </p>
      <h3>数据快照</h3>
      <p>DatasetVersion {session.dataset_version_id ?? "-"} · CalendarVersion {session.calendar_version_id ?? "-"}</p>
      <p>Snapshot fingerprint {session.market_data_snapshot_fingerprint.slice(0, 12)}…</p>
      <p>StrategyVersion {session.strategy_version_id ?? "无（仅手动）"}</p>
      <h3>Execution Config</h3>
      <p>
        Fee {Object.keys(session.execution_config.fee_policy).length} 项 · Slippage{" "}
        {Object.keys(session.execution_config.slippage_policy).length} 项 · Volume participation{" "}
        {session.execution_config.max_volume_participation ?? "-"}
      </p>
      <p>ExecutionConfig fingerprint {session.execution_config_fingerprint.slice(0, 12)}…</p>
      <h3>风险策略</h3>
      <p>{policy ? "Policy version " + policy.version + " · " + policy.fingerprint.slice(0, 12) + "…" : "未配置"}</p>
      <EquitySection equity={equity} />
    </section>
  );
}

function EquitySection({ equity }: { equity: PaperEquityPoint[] }) {
  if (equity.length === 0) return <p>暂无权益曲线</p>;
  const min = Math.min(...equity.map((e) => Number(e.equity)));
  const max = Math.max(...equity.map((e) => Number(e.equity)));
  const span = max - min || 1;
  const width = 640;
  const height = 160;
  const points = equity
    .map((e, i) => {
      const x = (i / Math.max(equity.length - 1, 1)) * width;
      const y = height - ((Number(e.equity) - min) / span) * height;
      return x.toFixed(1) + "," + y.toFixed(1);
    })
    .join(" ");
  return (
    <div>
      <h3>Equity Curve</h3>
      <svg viewBox={"0 0 " + width + " " + height} role="img" aria-label="权益曲线" width="640" height="160">
        <polyline points={points} fill="none" stroke="#1d5a45" strokeWidth="2" />
      </svg>
      <table>
        <thead>
          <tr>
            <th>日期</th>
            <th>现金</th>
            <th>市值</th>
            <th>权益</th>
            <th>当日 PnL</th>
            <th>回撤</th>
          </tr>
        </thead>
        <tbody>
          {equity.map((e) => (
            <tr key={e.session_date}>
              <td>{e.session_date}</td>
              <td>{money(e.cash)}</td>
              <td>{money(e.market_value)}</td>
              <td>{money(e.equity)}</td>
              <td>{signedMoney(e.daily_pnl)}</td>
              <td>{ratioToPct(e.drawdown)}%</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function PositionsTab({ session, refreshKey }: { session: PaperSession; refreshKey: number }) {
  const [positions, setPositions] = useState<PaperPosition[]>([]);
  const [includeClosed, setIncludeClosed] = useState(false);
  useEffect(() => {
    fetchPositions(session.id, includeClosed).then(setPositions).catch(() => setPositions([]));
  }, [session.id, includeClosed, refreshKey]);

  return (
    <section>
      <h2>持仓</h2>
      <label>
        <input type="checkbox" checked={includeClosed} onChange={(e) => setIncludeClosed(e.target.checked)} />
        显示已清仓
      </label>
      {positions.length === 0 ? (
        <p>暂无持仓</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>标的</th>
              <th>类型</th>
              <th>数量</th>
              <th>可卖</th>
              <th>均价</th>
              <th>市值</th>
              <th>未实现 PnL</th>
              <th>已实现 PnL</th>
            </tr>
          </thead>
          <tbody>
            {positions.map((p) => (
              <tr key={p.instrument_id}>
                <td>{p.symbol ?? p.instrument_id}</td>
                <td>{p.security_type ?? "-"}</td>
                <td>{p.total_quantity}</td>
                <td>{p.sellable_quantity}</td>
                <td>{money(p.average_cost)}</td>
                <td>{money(p.market_value)}</td>
                <td>{signedMoney(p.unrealized_pnl)}</td>
                <td>{signedMoney(p.realized_pnl)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

function OrdersTab({
  session,
  refreshKey,
  onChanged,
  onNotice,
}: {
  session: PaperSession;
  refreshKey: number;
  onChanged: () => void;
  onNotice: (msg: string) => void;
}) {
  const [orders, setOrders] = useState<PaperOrder[]>([]);
  useEffect(() => {
    fetchOrders(session.id).then(setOrders).catch(() => setOrders([]));
  }, [session.id, refreshKey]);

  const cancel = async (order: PaperOrder) => {
    try {
      await cancelOrder(order.id, order.status);
      onChanged();
    } catch (e) {
      if (isApiError(e) && e.error_code === "ORDER_STATE_CONFLICT") {
        onNotice("订单状态已变化，无法取消。");
        onChanged();
      } else {
        onNotice(apiMessage(e));
      }
    }
  };

  return (
    <section>
      <h2>订单</h2>
      {orders.length === 0 ? (
        <p>暂无订单</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>创建</th>
              <th>标的</th>
              <th>方向</th>
              <th>请求</th>
              <th>接受</th>
              <th>成交</th>
              <th>类型</th>
              <th>状态</th>
              <th>执行日期</th>
              <th>拒绝原因</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {orders.map((o) => (
              <tr key={o.id}>
                <td>{o.created_at}</td>
                <td>{o.instrument_id}</td>
                <td>{o.side}</td>
                <td>{o.requested_quantity}</td>
                <td>{o.accepted_quantity}</td>
                <td>{o.filled_quantity}</td>
                <td>{o.order_type}</td>
                <td>{o.status}</td>
                <td>{o.execution_session_date ?? "-"}</td>
                <td>{o.reject_reason ?? "-"}</td>
                <td>
                  {(o.status === "APPROVED" || o.status === "SUBMITTED") && (
                    <button type="button" onClick={() => cancel(o)}>取消</button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

function FillsTab({ session, refreshKey }: { session: PaperSession; refreshKey: number }) {
  const [fills, setFills] = useState<PaperFill[]>([]);
  useEffect(() => {
    fetchFills(session.id).then(setFills).catch(() => setFills([]));
  }, [session.id, refreshKey]);

  return (
    <section>
      <h2>成交</h2>
      {fills.length === 0 ? (
        <p>暂无成交</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>日期</th>
              <th>标的</th>
              <th>方向</th>
              <th>数量</th>
              <th>原始价</th>
              <th>成交价</th>
              <th>滑点</th>
              <th>佣金</th>
              <th>印花税</th>
              <th>过户费</th>
              <th>总费用</th>
            </tr>
          </thead>
          <tbody>
            {fills.map((f) => (
              <tr key={f.id}>
                <td>{f.trade_date}</td>
                <td>{f.instrument_id}</td>
                <td>{f.side}</td>
                <td>{f.quantity}</td>
                <td>{money(f.raw_price)}</td>
                <td>{money(f.fill_price)}</td>
                <td>{money(f.slippage)}</td>
                <td>{money(f.commission)}</td>
                <td>{money(f.stamp_tax)}</td>
                <td>{money(f.transfer_fee)}</td>
                <td>{money(f.total_fee)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

function RiskTab({
  session,
  policy,
  refreshKey,
}: {
  session: PaperSession;
  policy: PaperRiskPolicy | null;
  refreshKey: number;
}) {
  const [decisions, setDecisions] = useState<PaperRiskDecision[]>([]);
  useEffect(() => {
    fetchRiskDecisions(session.id).then(setDecisions).catch(() => setDecisions([]));
  }, [session.id, refreshKey]);

  return (
    <section>
      <h2>当前风控策略</h2>
      {policy ? (
        <p>
          Version {policy.version} · Fingerprint {policy.fingerprint.slice(0, 12)}… · 单笔订单 {money(policy.max_single_order_notional)}{" "}
          · 最大回撤 {ratioToPct(policy.max_drawdown)}%
        </p>
      ) : (
        <p>尚未配置风控策略</p>
      )}
      <h2>风控决策</h2>
      {decisions.length === 0 ? (
        <p>暂无风控决策</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>时间</th>
              <th>决策</th>
              <th>原因</th>
              <th>策略版本</th>
              <th>指标</th>
            </tr>
          </thead>
          <tbody>
            {decisions.map((d) => (
              <tr key={d.id}>
                <td>{d.evaluated_at}</td>
                <td>{d.decision}</td>
                <td>{d.reason_codes.map((c) => REASON_LABELS[c] ?? c).join(", ") || "-"}</td>
                <td>v{d.risk_policy_version}</td>
                <td>
                  {d.evaluated_metrics.estimated_order_notional != null
                    ? "notional " + d.evaluated_metrics.estimated_order_notional
                    : "-"}
                  {d.evaluated_metrics.projected_position_weight != null
                    ? " · weight " + d.evaluated_metrics.projected_position_weight
                    : ""}
                  {d.evaluated_metrics.projected_exposure_ratio != null
                    ? " · exposure " + d.evaluated_metrics.projected_exposure_ratio
                    : ""}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

function AuditTab({ session, refreshKey }: { session: PaperSession; refreshKey: number }) {
  const [audit, setAudit] = useState<PaperAuditEvent[]>([]);
  useEffect(() => {
    fetchAudit(session.id).then((items) => setAudit([...items].reverse())).catch(() => setAudit([]));
  }, [session.id, refreshKey]);

  return (
    <section>
      <h2>审计事件</h2>
      {audit.length === 0 ? (
        <p>暂无审计事件</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>时间</th>
              <th>事件</th>
              <th>摘要</th>
            </tr>
          </thead>
          <tbody>
            {audit.map((a) => (
              <tr key={a.id}>
                <td>{a.created_at}</td>
                <td>{EVENT_LABELS[a.event_type] ?? a.event_type}</td>
                <td>
                  <pre>{JSON.stringify(a.payload, null, 2)}</pre>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
