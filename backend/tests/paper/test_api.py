# ruff: noqa: E501

from __future__ import annotations

from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.anyio

DEFAULT_POLICY = {
    "name": "p",
    "max_single_order_notional": "1000000",
    "max_single_position_weight": "1",
    "max_total_exposure": "1",
    "cash_buffer_ratio": "0",
    "max_daily_loss": "0.5",
    "max_drawdown": "0.5",
    "max_open_orders": 100,
    "allowed_security_types": ["EQUITY"],
}


def _dec(value) -> Decimal:
    return Decimal(str(value))


async def _create_account(client: AsyncClient, initial_cash: str = "100000") -> dict:
    r = await client.post(
        "/api/v1/paper/accounts",
        json={"name": "a", "initial_cash": initial_cash, "base_currency": "CNY"},
    )
    assert r.status_code == 201
    return r.json()


async def _create_policy(client: AsyncClient, account_id: str) -> dict:
    r = await client.post(f"/api/v1/paper/accounts/{account_id}/risk", json=DEFAULT_POLICY)
    assert r.status_code == 201
    return r.json()


async def _create_session(client: AsyncClient, account_id: str, **overrides) -> dict:
    payload = {
        "name": "s",
        "paper_account_id": account_id,
        "market_data_profile_id": "p",
        "strategy_version_id": None,
        "replay_start_date": "2026-01-02",
        "replay_end_date": None,
        "execution_config": {
            "fee_policy": {},
            "slippage_policy": {},
            "max_volume_participation": None,
        },
    }
    payload.update(overrides)
    r = await client.post("/api/v1/paper/sessions", json=payload)
    assert r.status_code == 201
    return r.json()


async def _start_session(client: AsyncClient, session_id: str, version: int) -> dict:
    r = await client.post(
        f"/api/v1/paper/sessions/{session_id}/start", json={"expected_version": version}
    )
    assert r.status_code == 200
    return r.json()


# --- accounts ---


async def test_create_account(paper_client):
    payload = await _create_account(paper_client)
    assert payload["status"] == "ACTIVE"
    assert _dec(payload["cash"]) == Decimal("100000")
    assert _dec(payload["account_equity"]) == Decimal("100000")


async def test_create_account_invalid_cash(paper_client):
    r = await paper_client.post(
        "/api/v1/paper/accounts",
        json={"name": "a", "initial_cash": "-1", "base_currency": "CNY"},
    )
    assert r.status_code == 422


async def test_list_accounts(paper_client):
    created = await _create_account(paper_client)
    listed = await paper_client.get("/api/v1/paper/accounts")
    assert listed.status_code == 200
    assert any(item["id"] == created["id"] for item in listed.json()["items"])


async def test_get_account(paper_client):
    created = await _create_account(paper_client)
    fetched = await paper_client.get(f"/api/v1/paper/accounts/{created['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["id"] == created["id"]


async def test_account_missing_404(paper_client):
    r = await paper_client.get("/api/v1/paper/accounts/missing")
    assert r.status_code == 404
    assert r.json()["error_code"] == "PAPER_ACCOUNT_NOT_FOUND"


# --- sessions ---


async def test_create_session(paper_client):
    account = await _create_account(paper_client)
    session = await _create_session(paper_client, account["id"])
    assert session["status"] == "CREATED"
    assert session["version"] == 1
    assert session["current_session_date"] is None
    assert session["replay_start_date"] == "2026-01-02"


async def test_create_session_freezes_snapshot_and_config(paper_client):
    account = await _create_account(paper_client)
    session = await _create_session(paper_client, account["id"])
    assert session["market_data_snapshot_fingerprint"]
    assert session["execution_config_fingerprint"]
    assert session["dataset_version_id"]
    assert session["calendar_version_id"]
    assert session["execution_config"]["max_volume_participation"] is None


async def test_list_and_get_session(paper_client):
    account = await _create_account(paper_client)
    created = await _create_session(paper_client, account["id"])
    listed = await paper_client.get(f"/api/v1/paper/sessions?account_id={account['id']}")
    assert listed.status_code == 200
    assert any(item["id"] == created["id"] for item in listed.json()["items"])
    fetched = await paper_client.get(f"/api/v1/paper/sessions/{created['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["id"] == created["id"]


async def test_session_lifecycle_flow(paper_client):
    account = await _create_account(paper_client)
    session = await _create_session(paper_client, account["id"])
    started = await _start_session(paper_client, session["id"], 1)
    assert started["status"] == "RUNNING"
    assert started["version"] == 2
    paused = await paper_client.post(
        f"/api/v1/paper/sessions/{session['id']}/pause", json={"expected_version": 2}
    )
    assert paused.status_code == 200
    assert paused.json()["status"] == "PAUSED"
    resumed = await paper_client.post(
        f"/api/v1/paper/sessions/{session['id']}/resume", json={"expected_version": 3}
    )
    assert resumed.json()["status"] == "RUNNING"
    stopped = await paper_client.post(
        f"/api/v1/paper/sessions/{session['id']}/stop", json={"expected_version": 4}
    )
    assert stopped.json()["status"] == "STOPPED"


async def test_lifecycle_stale_version_409(paper_client):
    account = await _create_account(paper_client)
    session = await _create_session(paper_client, account["id"])
    r = await paper_client.post(
        f"/api/v1/paper/sessions/{session['id']}/start", json={"expected_version": 99}
    )
    assert r.status_code == 409
    assert r.json()["error_code"] == "SESSION_VERSION_CONFLICT"


async def test_lifecycle_invalid_transition_409(paper_client):
    account = await _create_account(paper_client)
    session = await _create_session(paper_client, account["id"])
    await _start_session(paper_client, session["id"], 1)
    r = await paper_client.post(
        f"/api/v1/paper/sessions/{session['id']}/start", json={"expected_version": 2}
    )
    assert r.status_code == 409
    assert r.json()["error_code"] == "SESSION_STATE_TRANSITION_INVALID"


# --- advance ---


async def test_advance_success(paper_client):
    account = await _create_account(paper_client)
    await _create_policy(paper_client, account["id"])
    session = await _create_session(paper_client, account["id"])
    await _start_session(paper_client, session["id"], 1)
    r = await paper_client.post(
        f"/api/v1/paper/sessions/{session['id']}/advance",
        json={"idempotency_key": "k1", "expected_version": 2, "expected_current_session_date": None},
    )
    assert r.status_code == 200
    payload = r.json()
    assert payload["resulting_session_date"] == "2026-01-02"
    assert payload["session_version"] == 3
    assert payload["idempotent_replay"] is False
    assert "account_equity" in payload


async def test_advance_duplicate_key_idempotent(paper_client):
    account = await _create_account(paper_client)
    await _create_policy(paper_client, account["id"])
    session = await _create_session(paper_client, account["id"])
    await _start_session(paper_client, session["id"], 1)
    first = await paper_client.post(
        f"/api/v1/paper/sessions/{session['id']}/advance",
        json={"idempotency_key": "dup", "expected_version": 2, "expected_current_session_date": None},
    )
    second = await paper_client.post(
        f"/api/v1/paper/sessions/{session['id']}/advance",
        json={"idempotency_key": "dup", "expected_version": 2, "expected_current_session_date": None},
    )
    assert first.status_code == second.status_code == 200
    assert first.json()["resulting_session_date"] == second.json()["resulting_session_date"]
    assert second.json()["idempotent_replay"] is True


async def test_advance_version_conflict_409(paper_client):
    account = await _create_account(paper_client)
    await _create_policy(paper_client, account["id"])
    session = await _create_session(paper_client, account["id"])
    await _start_session(paper_client, session["id"], 1)
    r = await paper_client.post(
        f"/api/v1/paper/sessions/{session['id']}/advance",
        json={"idempotency_key": "k1", "expected_version": 1, "expected_current_session_date": None},
    )
    assert r.status_code == 409
    assert r.json()["error_code"] == "SESSION_VERSION_CONFLICT"


async def test_advance_date_conflict_409(paper_client):
    account = await _create_account(paper_client)
    await _create_policy(paper_client, account["id"])
    session = await _create_session(paper_client, account["id"])
    await _start_session(paper_client, session["id"], 1)
    r = await paper_client.post(
        f"/api/v1/paper/sessions/{session['id']}/advance",
        json={"idempotency_key": "k1", "expected_version": 2, "expected_current_session_date": "2026-01-05"},
    )
    assert r.status_code == 409
    assert r.json()["error_code"] == "SESSION_VERSION_CONFLICT"


async def test_advance_paused_409(paper_client):
    account = await _create_account(paper_client)
    await _create_policy(paper_client, account["id"])
    session = await _create_session(paper_client, account["id"])
    await _start_session(paper_client, session["id"], 1)
    await paper_client.post(
        f"/api/v1/paper/sessions/{session['id']}/pause", json={"expected_version": 2}
    )
    r = await paper_client.post(
        f"/api/v1/paper/sessions/{session['id']}/advance",
        json={"idempotency_key": "k1", "expected_version": 3, "expected_current_session_date": None},
    )
    assert r.status_code == 409
    assert r.json()["error_code"] == "SESSION_NOT_RUNNING"


# --- manual intent ---


async def test_create_manual_intent(paper_client):
    account = await _create_account(paper_client)
    await _create_policy(paper_client, account["id"])
    session = await _create_session(paper_client, account["id"])
    await _start_session(paper_client, session["id"], 1)
    await paper_client.post(
        f"/api/v1/paper/sessions/{session['id']}/advance",
        json={"idempotency_key": "a1", "expected_version": 2, "expected_current_session_date": None},
    )
    r = await paper_client.post(
        f"/api/v1/paper/sessions/{session['id']}/order-intents",
        json={
            "idempotency_key": "i1",
            "instrument_id": "600000.XSHG",
            "side": "BUY",
            "quantity": 100,
            "order_type": "MARKET_ON_OPEN_SIMULATED",
            "limit_price": None,
            "reason": None,
            "metadata": {},
        },
    )
    assert r.status_code == 201
    payload = r.json()
    assert payload["source_type"] == "MANUAL"
    assert payload["signal_session_date"] == "2026-01-02"
    assert payload["intended_execution_session"] == "2026-01-06"
    assert payload["risk_status"] == "PENDING"


async def test_manual_intent_duplicate_idempotent(paper_client):
    account = await _create_account(paper_client)
    await _create_policy(paper_client, account["id"])
    session = await _create_session(paper_client, account["id"])
    await _start_session(paper_client, session["id"], 1)
    await paper_client.post(
        f"/api/v1/paper/sessions/{session['id']}/advance",
        json={"idempotency_key": "a1", "expected_version": 2, "expected_current_session_date": None},
    )
    payload = {
        "idempotency_key": "i1",
        "instrument_id": "600000.XSHG",
        "side": "BUY",
        "quantity": 100,
        "order_type": "MARKET_ON_OPEN_SIMULATED",
        "limit_price": None,
        "reason": None,
        "metadata": {},
    }
    first = await paper_client.post(
        f"/api/v1/paper/sessions/{session['id']}/order-intents", json=payload
    )
    second = await paper_client.post(
        f"/api/v1/paper/sessions/{session['id']}/order-intents", json=payload
    )
    assert first.status_code == second.status_code == 201
    assert first.json()["id"] == second.json()["id"]


async def test_manual_intent_delayed_retry_replays_before_future_date_validation(paper_client):
    account = await _create_account(paper_client)
    await _create_policy(paper_client, account["id"])
    session = await _create_session(
        paper_client, account["id"], replay_end_date="2026-01-06"
    )
    await _start_session(paper_client, session["id"], 1)
    await paper_client.post(
        f"/api/v1/paper/sessions/{session['id']}/advance",
        json={
            "idempotency_key": "delayed-a1",
            "expected_version": 2,
            "expected_current_session_date": None,
        },
    )
    payload = {
        "idempotency_key": "delayed-i1",
        "instrument_id": "600000.XSHG",
        "side": "BUY",
        "quantity": 100,
        "order_type": "MARKET_ON_OPEN_SIMULATED",
        "limit_price": None,
        "reason": None,
        "metadata": {},
    }
    first = await paper_client.post(
        f"/api/v1/paper/sessions/{session['id']}/order-intents", json=payload
    )
    assert first.status_code == 201
    await paper_client.post(
        f"/api/v1/paper/sessions/{session['id']}/advance",
        json={
            "idempotency_key": "delayed-a2",
            "expected_version": 3,
            "expected_current_session_date": "2026-01-02",
        },
    )

    delayed_retry = await paper_client.post(
        f"/api/v1/paper/sessions/{session['id']}/order-intents", json=payload
    )
    assert delayed_retry.status_code == 201
    assert delayed_retry.json()["id"] == first.json()["id"]
    paused = await paper_client.post(
        f"/api/v1/paper/sessions/{session['id']}/pause",
        json={"expected_version": 4},
    )
    assert paused.status_code == 200
    paused_retry = await paper_client.post(
        f"/api/v1/paper/sessions/{session['id']}/order-intents", json=payload
    )
    assert paused_retry.status_code == 201
    assert paused_retry.json()["id"] == first.json()["id"]


async def test_manual_intent_payload_conflict_409(paper_client):
    account = await _create_account(paper_client)
    await _create_policy(paper_client, account["id"])
    session = await _create_session(paper_client, account["id"])
    await _start_session(paper_client, session["id"], 1)
    await paper_client.post(
        f"/api/v1/paper/sessions/{session['id']}/advance",
        json={"idempotency_key": "a1", "expected_version": 2, "expected_current_session_date": None},
    )
    first = await paper_client.post(
        f"/api/v1/paper/sessions/{session['id']}/order-intents",
        json={
            "idempotency_key": "i1", "instrument_id": "600000.XSHG", "side": "BUY",
            "quantity": 100, "order_type": "MARKET_ON_OPEN_SIMULATED",
            "limit_price": None, "reason": None, "metadata": {},
        },
    )
    assert first.status_code == 201
    second = await paper_client.post(
        f"/api/v1/paper/sessions/{session['id']}/order-intents",
        json={
            "idempotency_key": "i1", "instrument_id": "600000.XSHG", "side": "BUY",
            "quantity": 200, "order_type": "MARKET_ON_OPEN_SIMULATED",
            "limit_price": None, "reason": None, "metadata": {},
        },
    )
    assert second.status_code == 409
    assert second.json()["error_code"] == "IDEMPOTENCY_KEY_CONFLICT"


async def test_manual_intent_before_advance_rejected(paper_client):
    account = await _create_account(paper_client)
    await _create_policy(paper_client, account["id"])
    session = await _create_session(paper_client, account["id"])
    await _start_session(paper_client, session["id"], 1)
    r = await paper_client.post(
        f"/api/v1/paper/sessions/{session['id']}/order-intents",
        json={
            "idempotency_key": "i1", "instrument_id": "600000.XSHG", "side": "BUY",
            "quantity": 100, "order_type": "MARKET_ON_OPEN_SIMULATED",
            "limit_price": None, "reason": None, "metadata": {},
        },
    )
    assert r.status_code == 409
    assert r.json()["error_code"] == "SESSION_NOT_STARTED"


async def test_manual_intent_requires_execution_session_within_replay_end(paper_client):
    account = await _create_account(paper_client)
    await _create_policy(paper_client, account["id"])
    session = await _create_session(
        paper_client, account["id"], replay_end_date="2026-01-05"
    )
    await _start_session(paper_client, session["id"], 1)
    await paper_client.post(
        f"/api/v1/paper/sessions/{session['id']}/advance",
        json={
            "idempotency_key": "bounded-a1",
            "expected_version": 2,
            "expected_current_session_date": None,
        },
    )
    response = await paper_client.post(
        f"/api/v1/paper/sessions/{session['id']}/order-intents",
        json={
            "idempotency_key": "bounded-i1",
            "instrument_id": "600000.XSHG",
            "side": "BUY",
            "quantity": 100,
            "order_type": "MARKET_ON_OPEN_SIMULATED",
            "limit_price": None,
            "reason": None,
            "metadata": {},
        },
    )
    assert response.status_code == 409
    assert response.json()["error_code"] == "NO_FUTURE_SESSION"


# --- orders / fills / positions / equity ---


async def test_manual_intent_advance_produces_order(paper_client):
    account = await _create_account(paper_client)
    await _create_policy(paper_client, account["id"])
    session = await _create_session(paper_client, account["id"])
    await _start_session(paper_client, session["id"], 1)
    await paper_client.post(
        f"/api/v1/paper/sessions/{session['id']}/advance",
        json={"idempotency_key": "a1", "expected_version": 2, "expected_current_session_date": None},
    )
    await paper_client.post(
        f"/api/v1/paper/sessions/{session['id']}/order-intents",
        json={
            "idempotency_key": "i1", "instrument_id": "600000.XSHG", "side": "BUY",
            "quantity": 100, "order_type": "MARKET_ON_OPEN_SIMULATED",
            "limit_price": None, "reason": None, "metadata": {},
        },
    )
    await paper_client.post(
        f"/api/v1/paper/sessions/{session['id']}/advance",
        json={"idempotency_key": "a2", "expected_version": 3, "expected_current_session_date": "2026-01-02"},
    )
    orders = await paper_client.get(f"/api/v1/paper/sessions/{session['id']}/orders")
    assert orders.status_code == 200
    assert len(orders.json()["items"]) == 1
    assert orders.json()["items"][0]["status"] == "SUBMITTED"


async def test_cancel_submitted_order(paper_client):
    account = await _create_account(paper_client)
    await _create_policy(paper_client, account["id"])
    session = await _create_session(paper_client, account["id"])
    await _start_session(paper_client, session["id"], 1)
    await paper_client.post(
        f"/api/v1/paper/sessions/{session['id']}/advance",
        json={"idempotency_key": "a1", "expected_version": 2, "expected_current_session_date": None},
    )
    await paper_client.post(
        f"/api/v1/paper/sessions/{session['id']}/order-intents",
        json={
            "idempotency_key": "i1", "instrument_id": "600000.XSHG", "side": "BUY",
            "quantity": 100, "order_type": "MARKET_ON_OPEN_SIMULATED",
            "limit_price": None, "reason": None, "metadata": {},
        },
    )
    await paper_client.post(
        f"/api/v1/paper/sessions/{session['id']}/advance",
        json={"idempotency_key": "a2", "expected_version": 3, "expected_current_session_date": "2026-01-02"},
    )
    orders = await paper_client.get(f"/api/v1/paper/sessions/{session['id']}/orders")
    order_id = orders.json()["items"][0]["id"]
    r = await paper_client.post(
        f"/api/v1/paper/orders/{order_id}/cancel", json={"expected_status": "SUBMITTED"}
    )
    assert r.status_code == 200
    assert r.json()["status"] == "CANCELLED"
    audit = await paper_client.get(f"/api/v1/paper/sessions/{session['id']}/audit")
    assert "ORDER_CANCELLED" in {item["event_type"] for item in audit.json()["items"]}


async def test_manual_intent_created_after_close_fills_on_a_future_session(paper_client):
    account = await _create_account(paper_client)
    await _create_policy(paper_client, account["id"])
    session = await _create_session(paper_client, account["id"])
    await _start_session(paper_client, session["id"], 1)

    first = await paper_client.post(
        f"/api/v1/paper/sessions/{session['id']}/advance",
        json={
            "idempotency_key": "manual-fill-a1",
            "expected_version": 2,
            "expected_current_session_date": None,
        },
    )
    assert first.status_code == 200
    created = await paper_client.post(
        f"/api/v1/paper/sessions/{session['id']}/order-intents",
        json={
            "idempotency_key": "manual-fill-i1",
            "instrument_id": "600000.XSHG",
            "side": "BUY",
            "quantity": 100,
            "order_type": "MARKET_ON_OPEN_SIMULATED",
            "limit_price": None,
            "reason": "phase-5g-regression",
            "metadata": {},
        },
    )
    assert created.status_code == 201
    assert (await paper_client.get(f"/api/v1/paper/sessions/{session['id']}/fills")).json()[
        "items"
    ] == []

    risk_and_order = await paper_client.post(
        f"/api/v1/paper/sessions/{session['id']}/advance",
        json={
            "idempotency_key": "manual-fill-a2",
            "expected_version": 3,
            "expected_current_session_date": "2026-01-02",
        },
    )
    assert risk_and_order.status_code == 200
    execution = await paper_client.post(
        f"/api/v1/paper/sessions/{session['id']}/advance",
        json={
            "idempotency_key": "manual-fill-a3",
            "expected_version": 4,
            "expected_current_session_date": "2026-01-05",
        },
    )
    assert execution.status_code == 200

    fills = await paper_client.get(f"/api/v1/paper/sessions/{session['id']}/fills")
    orders = await paper_client.get(f"/api/v1/paper/sessions/{session['id']}/orders")
    assert len(fills.json()["items"]) == 1
    filled_order = orders.json()["items"][0]
    assert filled_order["status"] == "FILLED"
    cancel = await paper_client.post(
        f"/api/v1/paper/orders/{filled_order['id']}/cancel",
        json={"expected_status": "FILLED"},
    )
    assert cancel.status_code == 409
    assert cancel.json()["error_code"] == "ORDER_STATE_CONFLICT"
    assert len(
        (
            await paper_client.get(f"/api/v1/paper/sessions/{session['id']}/fills")
        ).json()["items"]
    ) == 1


async def test_equity_sorted_and_filtered(paper_client):
    account = await _create_account(paper_client)
    await _create_policy(paper_client, account["id"])
    session = await _create_session(paper_client, account["id"])
    await _start_session(paper_client, session["id"], 1)
    await paper_client.post(
        f"/api/v1/paper/sessions/{session['id']}/advance",
        json={"idempotency_key": "a1", "expected_version": 2, "expected_current_session_date": None},
    )
    await paper_client.post(
        f"/api/v1/paper/sessions/{session['id']}/advance",
        json={"idempotency_key": "a2", "expected_version": 3, "expected_current_session_date": "2026-01-02"},
    )
    equity = await paper_client.get(
        f"/api/v1/paper/sessions/{session['id']}/equity?start=2026-01-02&end=2026-01-05"
    )
    assert equity.status_code == 200
    dates = [item["session_date"] for item in equity.json()["items"]]
    assert dates == sorted(dates)
    assert dates == ["2026-01-02", "2026-01-05"]


async def test_audit_list(paper_client):
    account = await _create_account(paper_client)
    await _create_policy(paper_client, account["id"])
    session = await _create_session(paper_client, account["id"])
    await _start_session(paper_client, session["id"], 1)
    await paper_client.post(
        f"/api/v1/paper/sessions/{session['id']}/advance",
        json={"idempotency_key": "a1", "expected_version": 2, "expected_current_session_date": None},
    )
    audit = await paper_client.get(f"/api/v1/paper/sessions/{session['id']}/audit")
    assert audit.status_code == 200
    assert any(item["event_type"] == "SESSION_ADVANCED" for item in audit.json()["items"])


# --- risk ---


async def test_create_and_get_policy(paper_client):
    account = await _create_account(paper_client)
    created = await _create_policy(paper_client, account["id"])
    assert created["version"] == 1
    assert created["fingerprint"]
    fetched = await paper_client.get(f"/api/v1/paper/accounts/{account['id']}/risk")
    assert fetched.status_code == 200
    assert fetched.json()["policy_id"] == created["policy_id"]


async def test_patch_policy_creates_new_version(paper_client):
    account = await _create_account(paper_client)
    created = await _create_policy(paper_client, account["id"])
    r = await paper_client.patch(
        f"/api/v1/paper/accounts/{account['id']}/risk",
        json={"max_drawdown": "0.3"},
    )
    assert r.status_code == 200
    assert r.json()["version"] == 2
    assert _dec(r.json()["max_drawdown"]) == Decimal("0.3")
    assert _dec(created["max_drawdown"]) == Decimal("0.5")


async def test_freeze_and_unfreeze(paper_client):
    account = await _create_account(paper_client)
    frozen = await paper_client.post(f"/api/v1/paper/accounts/{account['id']}/freeze")
    assert frozen.status_code == 200
    assert frozen.json()["status"] == "FROZEN"
    frozen_again = await paper_client.post(f"/api/v1/paper/accounts/{account['id']}/freeze")
    assert frozen_again.json()["status"] == "FROZEN"
    unfrozen = await paper_client.post(f"/api/v1/paper/accounts/{account['id']}/unfreeze")
    assert unfrozen.status_code == 200
    assert unfrozen.json()["status"] == "ACTIVE"


async def test_risk_decisions_list(paper_client):
    account = await _create_account(paper_client)
    await _create_policy(paper_client, account["id"])
    session = await _create_session(paper_client, account["id"])
    await _start_session(paper_client, session["id"], 1)
    await paper_client.post(
        f"/api/v1/paper/sessions/{session['id']}/advance",
        json={"idempotency_key": "a1", "expected_version": 2, "expected_current_session_date": None},
    )
    await paper_client.post(
        f"/api/v1/paper/sessions/{session['id']}/order-intents",
        json={
            "idempotency_key": "i1", "instrument_id": "600000.XSHG", "side": "BUY",
            "quantity": 100, "order_type": "MARKET_ON_OPEN_SIMULATED",
            "limit_price": None, "reason": None, "metadata": {},
        },
    )
    await paper_client.post(
        f"/api/v1/paper/sessions/{session['id']}/advance",
        json={"idempotency_key": "a2", "expected_version": 3, "expected_current_session_date": "2026-01-02"},
    )
    decisions = await paper_client.get(
        f"/api/v1/paper/sessions/{session['id']}/risk-decisions"
    )
    assert decisions.status_code == 200
    assert len(decisions.json()["items"]) == 1
    item = decisions.json()["items"][0]
    assert item["decision"] == "APPROVE"
    assert item["reason_codes"] == []
    assert item["risk_policy_fingerprint"]


# --- openapi ---


async def test_paper_routes_are_public_in_openapi():
    from quant_lab.main import create_app

    paths = create_app().openapi()["paths"]
    assert "/api/v1/paper/accounts" in paths
    assert "/api/v1/paper/accounts/{account_id}" in paths
    assert "/api/v1/paper/accounts/{account_id}/risk" in paths
    assert "/api/v1/paper/sessions" in paths
    assert "/api/v1/paper/sessions/{session_id}" in paths
    assert "/api/v1/paper/sessions/{session_id}/advance" in paths
    assert "/api/v1/paper/sessions/{session_id}/orders" in paths
    assert "/api/v1/paper/sessions/{session_id}/order-intents" in paths
    assert "/api/v1/paper/sessions/{session_id}/fills" in paths
    assert "/api/v1/paper/sessions/{session_id}/positions" in paths
    assert "/api/v1/paper/sessions/{session_id}/equity" in paths
    assert "/api/v1/paper/sessions/{session_id}/audit" in paths
    assert "/api/v1/paper/sessions/{session_id}/risk-decisions" in paths


# --- runtime smoke ---


async def test_runtime_smoke_full_flow_and_restart(paper_runtime_settings):
    from quant_lab.main import create_app

    app1 = create_app(paper_runtime_settings)
    transport1 = ASGITransport(app=app1)
    async with (
        app1.router.lifespan_context(app1),
        AsyncClient(transport=transport1, base_url="http://testserver") as client1,
    ):
        account = await _create_account(client1)
        await _create_policy(client1, account["id"])
        session = await _create_session(client1, account["id"])
        await _start_session(client1, session["id"], 1)

        r1 = await client1.post(
            f"/api/v1/paper/sessions/{session['id']}/advance",
            json={
                "idempotency_key": "restart-k1",
                "expected_version": 2,
                "expected_current_session_date": None,
            },
        )
        assert r1.json()["resulting_session_date"] == "2026-01-02"
        retry = await client1.post(
            f"/api/v1/paper/sessions/{session['id']}/advance",
            json={
                "idempotency_key": "restart-k1",
                "expected_version": 2,
                "expected_current_session_date": None,
            },
        )
        assert retry.json()["idempotent_replay"] is True

        manual = await client1.post(
            f"/api/v1/paper/sessions/{session['id']}/order-intents",
            json={
                "idempotency_key": "restart-manual",
                "instrument_id": "600000.XSHG",
                "side": "BUY",
                "quantity": 100,
                "order_type": "MARKET_ON_OPEN_SIMULATED",
                "limit_price": None,
                "reason": "restart acceptance",
                "metadata": {},
            },
        )
        assert manual.status_code == 201
        assert (await client1.get(f"/api/v1/paper/sessions/{session['id']}/fills")).json()[
            "items"
        ] == []
        r2 = await client1.post(
            f"/api/v1/paper/sessions/{session['id']}/advance",
            json={
                "idempotency_key": "restart-k2",
                "expected_version": 3,
                "expected_current_session_date": "2026-01-02",
            },
        )
        assert r2.json()["resulting_session_date"] == "2026-01-05"

    # app1 lifespan 与连接均已销毁; app2 重新连接同一 TEMP runtime 后继续推进.
    app2 = create_app(paper_runtime_settings)
    transport2 = ASGITransport(app=app2)
    async with (
        app2.router.lifespan_context(app2),
        AsyncClient(transport=transport2, base_url="http://testserver") as client2,
    ):
        account2 = await client2.get(f"/api/v1/paper/accounts/{account['id']}")
        assert account2.status_code == 200
        assert account2.json()["id"] == account["id"]
        session2 = await client2.get(f"/api/v1/paper/sessions/{session['id']}")
        assert session2.json()["current_session_date"] == "2026-01-05"
        assert session2.json()["version"] == 4
        equity = await client2.get(f"/api/v1/paper/sessions/{session['id']}/equity")
        assert len(equity.json()["items"]) == 2

        continued = await client2.post(
            f"/api/v1/paper/sessions/{session['id']}/advance",
            json={
                "idempotency_key": "restart-k3",
                "expected_version": 4,
                "expected_current_session_date": "2026-01-05",
            },
        )
        assert continued.status_code == 200
        assert continued.json()["resulting_session_date"] == "2026-01-06"
        assert len((await client2.get(f"/api/v1/paper/sessions/{session['id']}/orders")).json()["items"]) == 1
        assert len((await client2.get(f"/api/v1/paper/sessions/{session['id']}/fills")).json()["items"]) == 1
        assert len((await client2.get(f"/api/v1/paper/sessions/{session['id']}/positions")).json()["items"]) == 1
        assert len((await client2.get(f"/api/v1/paper/sessions/{session['id']}/risk-decisions")).json()["items"]) == 1
        audit_items = (
            await client2.get(f"/api/v1/paper/sessions/{session['id']}/audit")
        ).json()["items"]
        assert {"SESSION_ADVANCED", "ORDER_FILLED"} <= {
            item["event_type"] for item in audit_items
        }

        frozen = await client2.post(f"/api/v1/paper/accounts/{account['id']}/freeze")
        assert frozen.json()["status"] == "FROZEN"
        unfrozen = await client2.post(f"/api/v1/paper/accounts/{account['id']}/unfreeze")
        assert unfrozen.json()["status"] == "ACTIVE"
        policy = await client2.get(f"/api/v1/paper/accounts/{account['id']}/risk")
        assert policy.status_code == 200

    from sqlalchemy import text

    from quant_lab.db.sqlite import create_sqlite_engine

    verification_engine = create_sqlite_engine(paper_runtime_settings)
    with verification_engine.connect() as connection:
        account_audit_types = {
            row[0]
            for row in connection.execute(
                text(
                    "SELECT event_type FROM paper_audit_events "
                    "WHERE paper_account_id = :account_id"
                ),
                {"account_id": account["id"]},
            )
        }
    verification_engine.dispose()
    assert {"RISK_POLICY_VERSION_CREATED", "ACCOUNT_FROZEN", "ACCOUNT_UNFROZEN"} <= (
        account_audit_types
    )
