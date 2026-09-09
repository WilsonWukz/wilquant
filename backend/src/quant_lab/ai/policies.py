from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class AI2Policy(BaseModel):
    """Versioned, server-owned deterministic AI-2 limits and weights."""

    model_config = ConfigDict(frozen=True)

    evidence_policy_version: str = "ai-evidence-v2"
    validation_policy_version: str = "ai-validation-v2"
    retrieval_policy_version: str = "ai-retrieval-v1"
    research_gate_policy_version: str = "ai-research-gate-v2"
    realtime_max_age_seconds: int = 30
    max_evidence_items: int = 128
    max_evidence_bytes: int = 262_144
    max_retrieval_cases: int = 20
    money_tolerance: Decimal = Decimal("0.01")
    count_tolerance: Decimal = Decimal("0")
    ratio_absolute_tolerance: Decimal = Decimal("0.00000001")
    ratio_relative_tolerance: Decimal = Decimal("0.000001")
    number_absolute_tolerance: Decimal = Decimal("0.000000001")
    number_relative_tolerance: Decimal = Decimal("0.000001")
    strategy_family_weight: int = 40
    regime_label_weight: int = 10
    universe_weight: int = 8
    safe_tag_weight: int = 3
    lexical_weight: int = 2
    max_lexical_bucket: int = 20


AI2_POLICY = AI2Policy()
