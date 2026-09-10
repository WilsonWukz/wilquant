from decimal import Decimal

import pytest


def budget(**values):
    from quant_lab.ai.provider_budget import ProviderBudgetPolicy

    return ProviderBudgetPolicy(**values)


def test_budget_module_exists():
    from importlib.util import find_spec

    assert find_spec("quant_lab.ai.provider_budget") is not None


def test_no_pricing_is_unknown_not_free():
    policy = budget()
    assert policy.reservation(100, 10) is None
    assert policy.settlement(0, 0, 0) is None


def test_amount_limit_without_pricing_fails_closed():
    policy = budget(max_estimated_cost=Decimal("1"))
    with pytest.raises(ValueError, match="AI_BUDGET_PRICING_UNAVAILABLE"):
        policy.preflight(0, Decimal(0), 100, 10)


def test_priced_reservation_and_actual_settlement():
    policy = budget(
        input_cost_per_1m_tokens=Decimal("2"),
        cached_input_cost_per_1m_tokens=Decimal("1"),
        output_cost_per_1m_tokens=Decimal("4"),
    )
    assert policy.reservation(100, 10) == Decimal("0.00024")
    assert policy.settlement(100, 20, 10) == Decimal("0.00022")
    assert policy.settlement(None, None, None) is None
    assert policy.settlement(0, 0, 0) == Decimal("0")


@pytest.mark.parametrize(
    "values,args",
    [
        ({"max_calls": 1}, (1, Decimal(0), 100, 10)),
        ({"max_output_tokens": 10}, (0, Decimal(0), 100, 11)),
        ({"max_input_tokens": 10}, (0, Decimal(0), 11, 1)),
        (
            {
                "max_estimated_cost": Decimal("0.001"),
                "input_cost_per_1m_tokens": 10,
                "output_cost_per_1m_tokens": 10,
            },
            (0, Decimal("0.0005"), 100, 10),
        ),
    ],
)
def test_hard_limits(values, args):
    with pytest.raises(ValueError, match="AI_BUDGET_EXCEEDED"):
        budget(**values).preflight(*args)


def test_soft_warning_at_eighty_percent():
    assert budget(max_calls=5).preflight(3, Decimal(0), 10, 10)[1] is True


def test_invalid_prices_are_rejected():
    with pytest.raises(ValueError):
        budget(input_cost_per_1m_tokens=Decimal("NaN"))
