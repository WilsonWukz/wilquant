from __future__ import annotations

from quant_lab.paper.enums import PaperOrderStatus, PaperSessionStatus
from quant_lab.paper.errors import PaperError

_SESSION_TRANSITIONS: dict[PaperSessionStatus, frozenset[PaperSessionStatus]] = {
    PaperSessionStatus.CREATED: frozenset(
        {PaperSessionStatus.RUNNING, PaperSessionStatus.FAILED}
    ),
    PaperSessionStatus.RUNNING: frozenset(
        {PaperSessionStatus.PAUSED, PaperSessionStatus.STOPPED, PaperSessionStatus.FAILED}
    ),
    PaperSessionStatus.PAUSED: frozenset(
        {PaperSessionStatus.RUNNING, PaperSessionStatus.STOPPED, PaperSessionStatus.FAILED}
    ),
    PaperSessionStatus.STOPPED: frozenset(),
    PaperSessionStatus.FAILED: frozenset(),
}

_ORDER_TRANSITIONS: dict[PaperOrderStatus, frozenset[PaperOrderStatus]] = {
    PaperOrderStatus.CREATED: frozenset(
        {PaperOrderStatus.RISK_REJECTED, PaperOrderStatus.APPROVED}
    ),
    PaperOrderStatus.APPROVED: frozenset(
        {PaperOrderStatus.SUBMITTED, PaperOrderStatus.CANCELLED}
    ),
    PaperOrderStatus.SUBMITTED: frozenset(
        {
            PaperOrderStatus.FILLED,
            PaperOrderStatus.PARTIALLY_FILLED,
            PaperOrderStatus.REJECTED,
            PaperOrderStatus.CANCELLED,
            PaperOrderStatus.EXPIRED,
        }
    ),
    PaperOrderStatus.PARTIALLY_FILLED: frozenset({PaperOrderStatus.EXPIRED}),
    PaperOrderStatus.RISK_REJECTED: frozenset(),
    PaperOrderStatus.FILLED: frozenset(),
    PaperOrderStatus.CANCELLED: frozenset(),
    PaperOrderStatus.EXPIRED: frozenset(),
    PaperOrderStatus.REJECTED: frozenset(),
}

ORDER_TERMINAL_STATES = frozenset(
    {
        PaperOrderStatus.RISK_REJECTED,
        PaperOrderStatus.FILLED,
        PaperOrderStatus.CANCELLED,
        PaperOrderStatus.EXPIRED,
        PaperOrderStatus.REJECTED,
    }
)


def validate_session_transition(
    current: PaperSessionStatus, target: PaperSessionStatus
) -> None:
    if target not in _SESSION_TRANSITIONS[current]:
        raise PaperError(
            "SESSION_STATE_TRANSITION_INVALID",
            f"非法会话状态转换: {current.value} -> {target.value}",
        )


def validate_order_transition(current: PaperOrderStatus, target: PaperOrderStatus) -> None:
    if target not in _ORDER_TRANSITIONS[current]:
        raise PaperError(
            "ORDER_STATE_TRANSITION_INVALID",
            f"非法订单状态转换: {current.value} -> {target.value}",
        )


def is_order_terminal(status: PaperOrderStatus) -> bool:
    return status in ORDER_TERMINAL_STATES
