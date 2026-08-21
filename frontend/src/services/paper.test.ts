import { afterEach, describe, expect, it, vi } from "vitest";

import {
  advanceSession,
  cancelOrder,
  createAccount,
  createManualIntent,
  createRiskPolicy,
  createSession,
  fetchAccounts,
  fetchEquity,
  fetchRiskPolicy,
  patchRiskPolicy,
} from "./paper";

afterEach(() => vi.unstubAllGlobals());

describe("paper service", () => {
  it("creates an account with a POST body", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ id: "a1", name: "acct", status: "ACTIVE" }), { status: 201 }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await createAccount({ name: "acct", initial_cash: "100000", base_currency: "CNY" });

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/paper/accounts",
      expect.objectContaining({ method: "POST" }),
    );
    const request = fetchMock.mock.calls[0][1] as RequestInit;
    expect(JSON.parse(request.body as string)).toMatchObject({ name: "acct", initial_cash: "100000" });
  });

  it("creates a session with frozen execution config", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ id: "s1", status: "CREATED", version: 1 }), { status: 201 }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await createSession({
      name: "sess",
      paper_account_id: "a1",
      market_data_profile_id: "p",
      strategy_version_id: null,
      replay_start_date: "2026-01-02",
      replay_end_date: null,
      execution_config: { fee_policy: {}, slippage_policy: {}, max_volume_participation: null },
    });

    const request = fetchMock.mock.calls[0][1] as RequestInit;
    const body = JSON.parse(request.body as string);
    expect(body.market_data_profile_id).toBe("p");
    expect(body.execution_config).toEqual({ fee_policy: {}, slippage_policy: {}, max_volume_participation: null });
  });

  it("advance preserves the explicit idempotency key", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ paper_session_id: "s1", resulting_session_date: "2026-01-02" }), { status: 200 }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await advanceSession("s1", {
      idempotency_key: "key-abc",
      expected_version: 2,
      expected_current_session_date: null,
    });

    const request = fetchMock.mock.calls[0][1] as RequestInit;
    expect(JSON.parse(request.body as string)).toMatchObject({
      idempotency_key: "key-abc",
      expected_version: 2,
    });
  });

  it("parses the API error contract", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ error_code: "SESSION_VERSION_CONFLICT", message: "会话版本冲突" }), {
          status: 409,
        }),
      ),
    );

    await expect(fetchRiskPolicy("a1")).rejects.toMatchObject({
      error_code: "SESSION_VERSION_CONFLICT",
      message: "会话版本冲突",
    });
  });

  it("patches the risk policy to create a new version", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ policy_id: "p1", version: 2 }), { status: 200 }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await patchRiskPolicy("a1", { max_drawdown: "0.3" });

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/paper/accounts/a1/risk",
      expect.objectContaining({ method: "PATCH" }),
    );
    const request = fetchMock.mock.calls[0][1] as RequestInit;
    expect(JSON.parse(request.body as string)).toEqual({ max_drawdown: "0.3" });
  });

  it("lists accounts", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ items: [{ id: "a1", name: "acct", status: "ACTIVE" }] }), { status: 200 }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(fetchAccounts()).resolves.toEqual([{ id: "a1", name: "acct", status: "ACTIVE" }]);
    expect(fetchMock).toHaveBeenCalledWith("/api/v1/paper/accounts", undefined);
  });

  it("normalizes an empty equity response to an empty array", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ items: [] }), { status: 200 }),
      ),
    );

    await expect(fetchEquity("s1")).resolves.toEqual([]);
  });

  it("rejects a malformed equity response instead of returning undefined", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ id: "s1", status: "RUNNING" }), { status: 200 }),
      ),
    );

    await expect(fetchEquity("s1")).rejects.toMatchObject({
      error_code: "INVALID_RESPONSE",
    });
  });

  it("cancels an order with expected status", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ id: "o1", status: "CANCELLED" }), { status: 200 }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await cancelOrder("o1", "SUBMITTED");

    expect(fetchMock).toHaveBeenCalledWith("/api/v1/paper/orders/o1/cancel", expect.objectContaining({ method: "POST" }));
  });

  it("submits a manual intent as BUY", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ id: "i1", source_type: "MANUAL", side: "BUY" }), { status: 201 }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await createManualIntent("s1", {
      idempotency_key: "key-1",
      instrument_id: "600000.XSHG",
      side: "BUY",
      quantity: 100,
      order_type: "MARKET_ON_OPEN_SIMULATED",
      limit_price: null,
      reason: null,
      metadata: {},
    });

    const request = fetchMock.mock.calls[0][1] as RequestInit;
    expect(JSON.parse(request.body as string)).toMatchObject({ side: "BUY", quantity: 100 });
  });
});
