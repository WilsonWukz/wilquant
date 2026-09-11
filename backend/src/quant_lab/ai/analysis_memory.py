"""将检索记忆与可重新验证的正式证据分离。"""

from __future__ import annotations

from collections.abc import Callable

from quant_lab.ai.analysis_contracts import AnalysisType
from quant_lab.ai.contracts import CanonicalEvidenceItem, EvidenceContext, TemporalContext
from quant_lab.ai.contracts import EvidenceSourceType as Source
from quant_lab.ai.packs import EvidencePackError, EvidencePackService, _pack_from_model
from quant_lab.ai.repository import AIRepository
from quant_lab.ai.resolvers import EvidenceRequest, EvidenceResolverError, EvidenceResolverRegistry

CASE_SOURCE_POLICY = {
    AnalysisType.MARKET_DIAGNOSIS: {Source.DATASET_VERSION, Source.MARKET_DATA_SNAPSHOT},
    AnalysisType.STRATEGY_REVIEW: {
        Source.STRATEGY_VERSION,
        Source.BACKTEST_RUN,
        Source.MARKET_DATA_SNAPSHOT,
        Source.RESEARCH_DIAGNOSTIC,
        Source.RESEARCH_COMPARISON,
    },
    AnalysisType.EXPERIMENT_REVIEW: {
        Source.RESEARCH_EXPERIMENT,
        Source.BACKTEST_RUN,
        Source.MARKET_DATA_SNAPSHOT,
        Source.RESEARCH_COMPARISON,
        Source.RESEARCH_DIAGNOSTIC,
        Source.RESEARCH_REPORT,
    },
    AnalysisType.PAPER_REVIEW: {
        Source.PAPER_SESSION,
        Source.PAPER_ACCOUNT_SNAPSHOT,
        Source.RISK_DECISION,
        Source.STRATEGY_VERSION,
        Source.BACKTEST_RUN,
        Source.MARKET_DATA_SNAPSHOT,
    },
}


def resolve_case_evidence(
    repository: AIRepository,
    registry: EvidenceResolverRegistry,
    *,
    case_id: str,
    analysis_type: AnalysisType,
    temporal: TemporalContext,
    context: EvidenceContext,
    resolver: Callable[[EvidenceRequest], tuple[CanonicalEvidenceItem, ...]] | None = None,
) -> tuple[CanonicalEvidenceItem, ...]:
    """历史 pack 仅给出线索。重新解析后的同一身份才有资格成为 FACT。"""
    selected: dict[str, CanonicalEvidenceItem] = {}
    allowed = CASE_SOURCE_POLICY[analysis_type]
    for stored in repository.list_case_evidence_packs(case_id):
        for historical in _pack_from_model(stored).items:
            if historical.classification != "FACT" or historical.source_type not in allowed:
                continue
            try:
                resolved = (resolver or registry.resolve)(
                    EvidenceRequest(
                        source_type=historical.source_type,
                        source_id=historical.source_id,
                        fields=(historical.field_path,),
                    )
                )
                for item in resolved:
                    if (
                        item.ref != historical.ref
                        or item.source_fingerprint != historical.source_fingerprint
                        or item.value_fingerprint != historical.value_fingerprint
                    ):
                        continue
                    EvidencePackService._validate_item(item, temporal, context)
                    selected[item.ref] = item
            except (EvidenceResolverError, EvidencePackError):
                # 不可重验的历史事实不提升为证据。记忆仍显式不可信。
                continue
            if len(selected) >= 8:
                return tuple(selected[key] for key in sorted(selected))
    return tuple(selected[key] for key in sorted(selected))
