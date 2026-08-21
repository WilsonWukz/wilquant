import type {
  ApiError,
  Instrument,
  PaperAccount,
  PaperAdvanceResult,
  PaperAuditEvent,
  PaperEquityPoint,
  PaperFill,
  PaperIntent,
  PaperOrder,
  PaperPosition,
  PaperRiskDecision,
  PaperRiskPolicy,
  PaperSession,
  StrategyDefinition,
  StrategyVersion,
} from "../types/paper";

async function toApiError(response: Response): Promise<ApiError> {
  try {
    const body = (await response.json()) as Partial<ApiError>;
    return {
      error_code: body.error_code ?? "UNKNOWN",
      message: body.message ?? "请求失败 (" + response.status + ")",
    };
  } catch {
    return { error_code: "UNKNOWN", message: "请求失败 (" + response.status + ")" };
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch("/api/v1" + path, init);
  if (!response.ok) {
    throw await toApiError(response);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

function jsonInit(method: string, body: unknown): RequestInit {
  return { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
}

function query(params: Record<string, string | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== "") search.set(key, value);
  }
  const text = search.toString();
  return text ? "?" + text : "";
}

type ListResponse<T> = { items: T[] };

function parseListItems<T>(response: ListResponse<T>, resource: string): T[] {
  if (!response || !Array.isArray(response.items)) {
    throw {
      error_code: "INVALID_RESPONSE",
      message: resource + " 响应格式无效",
    } satisfies ApiError;
  }
  return response.items;
}

// --- accounts ---

export function createAccount(payload: { name: string; initial_cash: string; base_currency: string }): Promise<PaperAccount> {
  return request<PaperAccount>("/paper/accounts", jsonInit("POST", payload));
}

export function fetchAccounts(): Promise<PaperAccount[]> {
  return request<ListResponse<PaperAccount>>("/paper/accounts").then((r) => r.items);
}

export function fetchAccount(accountId: string): Promise<PaperAccount> {
  return request<PaperAccount>("/paper/accounts/" + accountId);
}

// --- sessions ---

export type SessionCreatePayload = {
  name: string;
  paper_account_id: string;
  market_data_profile_id: string;
  strategy_version_id: string | null;
  replay_start_date: string;
  replay_end_date: string | null;
  execution_config: { fee_policy: Record<string, unknown>; slippage_policy: Record<string, unknown>; max_volume_participation: string | null };
};

export function createSession(payload: SessionCreatePayload): Promise<PaperSession> {
  return request<PaperSession>("/paper/sessions", jsonInit("POST", payload));
}

export function fetchSessions(params: { account_id?: string; status?: string } = {}): Promise<PaperSession[]> {
  return request<ListResponse<PaperSession>>("/paper/sessions" + query(params)).then((r) => r.items);
}

export function fetchSession(sessionId: string): Promise<PaperSession> {
  return request<PaperSession>("/paper/sessions/" + sessionId);
}

// --- lifecycle ---

function lifecycle(sessionId: string, action: "start" | "pause" | "resume" | "stop", expectedVersion: number): Promise<PaperSession> {
  return request<PaperSession>("/paper/sessions/" + sessionId + "/" + action, jsonInit("POST", { expected_version: expectedVersion }));
}

export function startSession(sessionId: string, expectedVersion: number): Promise<PaperSession> {
  return lifecycle(sessionId, "start", expectedVersion);
}

export function pauseSession(sessionId: string, expectedVersion: number): Promise<PaperSession> {
  return lifecycle(sessionId, "pause", expectedVersion);
}

export function resumeSession(sessionId: string, expectedVersion: number): Promise<PaperSession> {
  return lifecycle(sessionId, "resume", expectedVersion);
}

export function stopSession(sessionId: string, expectedVersion: number): Promise<PaperSession> {
  return lifecycle(sessionId, "stop", expectedVersion);
}

// --- advance ---

export function advanceSession(
  sessionId: string,
  payload: { idempotency_key: string; expected_version: number; expected_current_session_date: string | null },
): Promise<PaperAdvanceResult> {
  return request<PaperAdvanceResult>("/paper/sessions/" + sessionId + "/advance", jsonInit("POST", payload));
}

// --- manual intent ---

export type ManualIntentPayload = {
  idempotency_key: string;
  instrument_id: string;
  side: "BUY" | "SELL";
  quantity: number;
  order_type: string;
  limit_price: string | null;
  reason: string | null;
  metadata: Record<string, unknown>;
};

export function createManualIntent(sessionId: string, payload: ManualIntentPayload): Promise<PaperIntent> {
  return request<PaperIntent>("/paper/sessions/" + sessionId + "/order-intents", jsonInit("POST", payload));
}

// --- orders / cancel ---

export function fetchOrders(sessionId: string, params: { status?: string; instrument_id?: string } = {}): Promise<PaperOrder[]> {
  return request<ListResponse<PaperOrder>>("/paper/sessions/" + sessionId + "/orders" + query(params)).then((r) => r.items);
}

export function cancelOrder(orderId: string, expectedStatus?: string): Promise<PaperOrder> {
  return request<PaperOrder>("/paper/orders/" + orderId + "/cancel", jsonInit("POST", { expected_status: expectedStatus ?? null }));
}

// --- fills ---

export function fetchFills(sessionId: string, params: { instrument_id?: string; trade_date?: string } = {}): Promise<PaperFill[]> {
  return request<ListResponse<PaperFill>>("/paper/sessions/" + sessionId + "/fills" + query(params)).then((r) => r.items);
}

// --- positions ---

export function fetchPositions(sessionId: string, includeClosed = false): Promise<PaperPosition[]> {
  const path = includeClosed ? "/paper/sessions/" + sessionId + "/positions?include_closed=true" : "/paper/sessions/" + sessionId + "/positions";
  return request<ListResponse<PaperPosition>>(path).then((r) => r.items);
}

// --- equity ---

export function fetchEquity(sessionId: string, params: { start?: string; end?: string } = {}): Promise<PaperEquityPoint[]> {
  return request<ListResponse<PaperEquityPoint>>("/paper/sessions/" + sessionId + "/equity" + query(params)).then((response) =>
    parseListItems(response, "权益曲线"),
  );
}

// --- audit ---

export function fetchAudit(sessionId: string, params: { event_type?: string } = {}): Promise<PaperAuditEvent[]> {
  return request<ListResponse<PaperAuditEvent>>("/paper/sessions/" + sessionId + "/audit" + query(params)).then((r) => r.items);
}

// --- risk decisions ---

export function fetchRiskDecisions(sessionId: string): Promise<PaperRiskDecision[]> {
  return request<ListResponse<PaperRiskDecision>>("/paper/sessions/" + sessionId + "/risk-decisions").then((r) => r.items);
}

// --- risk policy ---

export type RiskPolicyLimits = {
  max_single_order_notional: string;
  max_single_position_weight: string;
  max_total_exposure: string;
  cash_buffer_ratio: string;
  max_daily_loss: string;
  max_drawdown: string;
  max_open_orders: number;
  allowed_security_types: string[];
};

export function fetchRiskPolicy(accountId: string): Promise<PaperRiskPolicy> {
  return request<PaperRiskPolicy>("/paper/accounts/" + accountId + "/risk");
}

export function createRiskPolicy(accountId: string, payload: { name: string } & RiskPolicyLimits): Promise<PaperRiskPolicy> {
  return request<PaperRiskPolicy>("/paper/accounts/" + accountId + "/risk", jsonInit("POST", payload));
}

export function patchRiskPolicy(accountId: string, payload: Partial<RiskPolicyLimits>): Promise<PaperRiskPolicy> {
  return request<PaperRiskPolicy>("/paper/accounts/" + accountId + "/risk", jsonInit("PATCH", payload));
}

// --- freeze / unfreeze ---

export function freezeAccount(accountId: string): Promise<PaperAccount> {
  return request<PaperAccount>("/paper/accounts/" + accountId + "/freeze", jsonInit("POST", {}));
}

export function unfreezeAccount(accountId: string): Promise<PaperAccount> {
  return request<PaperAccount>("/paper/accounts/" + accountId + "/unfreeze", jsonInit("POST", {}));
}

// --- strategies ---

export function fetchStrategies(): Promise<StrategyDefinition[]> {
  return request<ListResponse<StrategyDefinition>>("/strategies").then((r) => r.items);
}

export function fetchStrategyVersions(definitionId: string): Promise<StrategyVersion[]> {
  return request<ListResponse<StrategyVersion>>("/strategies/" + definitionId + "/versions").then((r) => r.items);
}

// --- instruments ---

export function fetchInstruments(profileId: string): Promise<Instrument[]> {
  return request<ListResponse<Instrument>>("/market-data/profiles/" + profileId + "/instruments").then((r) => r.items);
}
