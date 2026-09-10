from __future__ import annotations

from decimal import ROUND_CEILING, Decimal

from pydantic import BaseModel, ConfigDict, Field

MILLION = Decimal(1_000_000)
MONEY_STEP = Decimal("0.00000001")


class ProviderBudgetPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    version: str = "ai-provider-budget-v1"
    max_calls: int = Field(default=3, ge=1, le=100)
    max_input_tokens: int = Field(default=32768, ge=1, le=1_000_000)
    max_output_tokens: int = Field(default=2048, ge=1, le=32768)
    max_estimated_cost: Decimal | None = Field(default=None, ge=0)
    input_cost_per_1m_tokens: Decimal | None = Field(default=None, ge=0)
    cached_input_cost_per_1m_tokens: Decimal | None = Field(default=None, ge=0)
    output_cost_per_1m_tokens: Decimal | None = Field(default=None, ge=0)
    currency: str = Field(default="USD", pattern=r"^[A-Z]{3}$")

    def reservation(self, input_bound: int, output_bound: int) -> Decimal | None:
        if self.input_cost_per_1m_tokens is None or self.output_cost_per_1m_tokens is None:
            return None
        input_price = max(
            self.input_cost_per_1m_tokens, self.cached_input_cost_per_1m_tokens or Decimal(0)
        )
        return (
            (input_bound * input_price + output_bound * self.output_cost_per_1m_tokens) / MILLION
        ).quantize(MONEY_STEP, rounding=ROUND_CEILING)

    def settlement(
        self, prompt: int | None, cached: int | None, completion: int | None
    ) -> Decimal | None:
        if (
            prompt is None
            or completion is None
            or self.input_cost_per_1m_tokens is None
            or self.output_cost_per_1m_tokens is None
        ):
            return None
        if cached is None and self.cached_input_cost_per_1m_tokens is not None:
            return None
        cached_price = self.cached_input_cost_per_1m_tokens
        if cached_price is None:
            cached_price = self.input_cost_per_1m_tokens
        cached_count = cached if cached is not None else 0
        return (
            (
                (prompt - cached_count) * self.input_cost_per_1m_tokens
                + cached_count * cached_price
                + completion * self.output_cost_per_1m_tokens
            )
            / MILLION
        ).quantize(MONEY_STEP, rounding=ROUND_CEILING)

    def preflight(
        self, calls: int, charged: Decimal, input_bound: int, output_bound: int
    ) -> tuple[Decimal | None, bool]:
        if (
            calls >= self.max_calls
            or input_bound > self.max_input_tokens
            or output_bound > self.max_output_tokens
        ):
            raise ValueError("AI_BUDGET_EXCEEDED")
        reserve = self.reservation(input_bound, output_bound)
        if self.max_estimated_cost is not None:
            if reserve is None:
                raise ValueError("AI_BUDGET_PRICING_UNAVAILABLE")
            if charged + reserve > self.max_estimated_cost:
                raise ValueError("AI_BUDGET_EXCEEDED")
        warning = Decimal(calls + 1) >= Decimal(self.max_calls) * Decimal("0.8")
        if self.max_estimated_cost is not None and reserve is not None:
            warning |= charged + reserve >= self.max_estimated_cost * Decimal("0.8")
        return reserve, warning
