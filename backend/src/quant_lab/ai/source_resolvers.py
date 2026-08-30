from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from quant_lab.ai.contracts import EvidenceClassification, EvidenceSourceType
from quant_lab.ai.resolvers import (
    EvidenceResolverRegistry,
    ExplicitSnapshotResolver,
    SourceLoader,
)

FACT = EvidenceClassification.FACT
NOTE = EvidenceClassification.USER_NOTE
METRIC = EvidenceClassification.DERIVED_METRIC
STATE = EvidenceClassification.SYSTEM_STATE


@dataclass(frozen=True, slots=True)
class SourceFieldPolicy:
    classifications: Mapping[str, EvidenceClassification]
    units: Mapping[str, str | None]

    @property
    def fields(self) -> frozenset[str]:
        return frozenset(self.classifications)


def _policy(
    classifications: Mapping[str, EvidenceClassification],
    units: Mapping[str, str | None] | None = None,
) -> SourceFieldPolicy:
    return SourceFieldPolicy(classifications=dict(classifications), units=dict(units or {}))


SUPPORTED_SOURCE_POLICIES: Mapping[EvidenceSourceType, SourceFieldPolicy] = {
    EvidenceSourceType.DATASET_VERSION: _policy(
        {
            "dataset_id": FACT,
            "version": FACT,
            "row_count": FACT,
            "min_timestamp": FACT,
            "max_timestamp": FACT,
            "quality_status": FACT,
            "schema_fingerprint": FACT,
        }
    ),
    EvidenceSourceType.MARKET_DATA_SNAPSHOT: _policy(
        {
            "profile_id": STATE,
            "dataset_version_ids": FACT,
            "dataset_fingerprints": FACT,
            "calendar_version": FACT,
            "quality_status": STATE,
            "snapshot_fingerprint": FACT,
        }
    ),
    EvidenceSourceType.STRATEGY_VERSION: _policy(
        {
            "strategy_id": FACT,
            "strategy_type": FACT,
            "version": FACT,
            "fingerprint": FACT,
            "specification": NOTE,
        }
    ),
    EvidenceSourceType.BACKTEST_RUN: _policy(
        {
            "status": STATE,
            "strategy_version_id": FACT,
            "dataset_version_ids": FACT,
            "input_fingerprint": FACT,
            "artifact_hashes": FACT,
            "metrics": METRIC,
        }
    ),
    EvidenceSourceType.RESEARCH_EXPERIMENT: _policy(
        {
            "status": STATE,
            "tags": STATE,
            "hypothesis": NOTE,
            "research_prose": NOTE,
            "linked_run_ids": FACT,
        }
    ),
    EvidenceSourceType.RESEARCH_COMPARISON: _policy(
        {"comparability": METRIC, "metric_deltas": METRIC, "input_run_ids": FACT}
    ),
    EvidenceSourceType.RESEARCH_DIAGNOSTIC: _policy(
        {"counts": METRIC, "ratios": METRIC, "run_id": FACT, "artifact_hashes": FACT}
    ),
    EvidenceSourceType.RESEARCH_REPORT: _policy(
        {
            "metrics": METRIC,
            "diagnostics": METRIC,
            "summary_prose": NOTE,
            "recommendation_prose": NOTE,
        }
    ),
    EvidenceSourceType.PAPER_SESSION: _policy(
        {"status": STATE, "session_config": STATE, "account_id": FACT}
    ),
    EvidenceSourceType.PAPER_ACCOUNT_SNAPSHOT: _policy(
        {
            "cash": FACT,
            "equity": FACT,
            "gross_exposure": FACT,
            "realized_pnl": FACT,
            "unrealized_pnl": FACT,
        },
        {
            "cash": "CURRENCY",
            "equity": "CURRENCY",
            "gross_exposure": "CURRENCY",
            "realized_pnl": "CURRENCY",
            "unrealized_pnl": "CURRENCY",
        },
    ),
    EvidenceSourceType.RISK_DECISION: _policy(
        {
            "decision": FACT,
            "reason_codes": FACT,
            "policy_version": FACT,
            "input_fingerprint": FACT,
        }
    ),
}


def build_supported_resolver_registry(
    loaders: Mapping[EvidenceSourceType, SourceLoader],
) -> EvidenceResolverRegistry:
    registry = EvidenceResolverRegistry()
    for source_type, loader in loaders.items():
        policy = SUPPORTED_SOURCE_POLICIES.get(source_type)
        if policy is None:
            continue
        registry.register(
            ExplicitSnapshotResolver(
                source_type=source_type,
                field_classifications=policy.classifications,
                field_units=policy.units,
                loader=loader,
            )
        )
    return registry

