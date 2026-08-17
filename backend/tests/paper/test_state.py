from __future__ import annotations

import pytest

from quant_lab.paper.enums import PaperOrderStatus, PaperSessionStatus
from quant_lab.paper.errors import PaperError
from quant_lab.paper.state import (
    is_order_terminal,
    validate_order_transition,
    validate_session_transition,
)


def test_session_legal_transitions():
    validate_session_transition(PaperSessionStatus.CREATED, PaperSessionStatus.RUNNING)
    validate_session_transition(PaperSessionStatus.RUNNING, PaperSessionStatus.PAUSED)
    validate_session_transition(PaperSessionStatus.PAUSED, PaperSessionStatus.RUNNING)
    validate_session_transition(PaperSessionStatus.RUNNING, PaperSessionStatus.STOPPED)
    validate_session_transition(PaperSessionStatus.RUNNING, PaperSessionStatus.FAILED)
    validate_session_transition(PaperSessionStatus.PAUSED, PaperSessionStatus.FAILED)
    validate_session_transition(PaperSessionStatus.CREATED, PaperSessionStatus.FAILED)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (PaperSessionStatus.CREATED, PaperSessionStatus.PAUSED),
        (PaperSessionStatus.CREATED, PaperSessionStatus.STOPPED),
        (PaperSessionStatus.PAUSED, PaperSessionStatus.CREATED),
        (PaperSessionStatus.STOPPED, PaperSessionStatus.RUNNING),
        (PaperSessionStatus.FAILED, PaperSessionStatus.RUNNING),
    ],
)
def test_session_illegal_transitions(current, target):
    with pytest.raises(PaperError, match="SESSION_STATE_TRANSITION_INVALID"):
        validate_session_transition(current, target)


def test_order_legal_transitions():
    validate_order_transition(PaperOrderStatus.CREATED, PaperOrderStatus.APPROVED)
    validate_order_transition(PaperOrderStatus.CREATED, PaperOrderStatus.RISK_REJECTED)
    validate_order_transition(PaperOrderStatus.APPROVED, PaperOrderStatus.SUBMITTED)
    validate_order_transition(PaperOrderStatus.APPROVED, PaperOrderStatus.CANCELLED)
    validate_order_transition(PaperOrderStatus.SUBMITTED, PaperOrderStatus.FILLED)
    validate_order_transition(PaperOrderStatus.SUBMITTED, PaperOrderStatus.PARTIALLY_FILLED)
    validate_order_transition(PaperOrderStatus.PARTIALLY_FILLED, PaperOrderStatus.EXPIRED)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (PaperOrderStatus.CREATED, PaperOrderStatus.SUBMITTED),
        (PaperOrderStatus.CREATED, PaperOrderStatus.FILLED),
        (PaperOrderStatus.APPROVED, PaperOrderStatus.FILLED),
        (PaperOrderStatus.FILLED, PaperOrderStatus.CANCELLED),
        (PaperOrderStatus.CANCELLED, PaperOrderStatus.APPROVED),
        (PaperOrderStatus.EXPIRED, PaperOrderStatus.FILLED),
        (PaperOrderStatus.PARTIALLY_FILLED, PaperOrderStatus.FILLED),
    ],
)
def test_order_illegal_transitions(current, target):
    with pytest.raises(PaperError, match="ORDER_STATE_TRANSITION_INVALID"):
        validate_order_transition(current, target)


def test_terminal_states():
    assert is_order_terminal(PaperOrderStatus.RISK_REJECTED)
    assert is_order_terminal(PaperOrderStatus.FILLED)
    assert is_order_terminal(PaperOrderStatus.CANCELLED)
    assert is_order_terminal(PaperOrderStatus.EXPIRED)
    assert is_order_terminal(PaperOrderStatus.REJECTED)
    assert not is_order_terminal(PaperOrderStatus.CREATED)
    assert not is_order_terminal(PaperOrderStatus.APPROVED)
    assert not is_order_terminal(PaperOrderStatus.SUBMITTED)
    assert not is_order_terminal(PaperOrderStatus.PARTIALLY_FILLED)
