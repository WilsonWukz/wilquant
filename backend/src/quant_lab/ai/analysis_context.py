from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast

from quant_lab.ai.analysis_contracts import AnalysisType, ResearchAnalysisRequest
from quant_lab.ai.analysis_memory import resolve_case_evidence
from quant_lab.ai.cases import ResearchCaseInput, ResearchCaseService
from quant_lab.ai.contracts import (
    AnalysisRequirements,
    CanonicalEvidenceItem,
    EvidenceContext,
    EvidencePack,
    FreshnessRequirement,
    GateResult,
    Market,
    RetrievalQuery,
    RetrievalSnapshot,
    RuleTopic,
    TemporalContext,
    ValidationFinding,
    ValidationLayer,
)
from quant_lab.ai.contracts import (
    EvidenceSourceType as Source,
)
from quant_lab.ai.fingerprints import fingerprint_payload
from quant_lab.ai.gates import ResearchGate
from quant_lab.ai.packs import EvidencePackError, EvidencePackService
from quant_lab.ai.repository import AIRepository
from quant_lab.ai.resolvers import (
    EvidenceRequest,
    EvidenceResolverError,
    EvidenceResolverRegistry,
    TemporalMetadataUnavailable,
)
from quant_lab.ai.retrieval import ResearchCaseRetrievalService
from quant_lab.ai.validation import ValidationService, _finding
from quant_lab.market_data.normalization import SHANGHAI_TZ

CONTEXT_POLICY_VERSION = "ai-analysis-context-v1"
RULE_WORDS: dict[str, tuple[str, ...]] = {
    "T_PLUS_ONE": ("t+1", "t\uff0b1"),
    "SAME_DAY_SELL": ("same-day", "当日卖", "日内卖"),
    "LOT_SIZE": ("lot size", "手数", "每手"),
    "PRICE_LIMIT": ("price limit", "涨跌停"),
    "FRACTIONAL_QUANTITY": ("fractional", "碎股"),
    "TRADING_SESSION": ("trading session", "交易时段"),
    "SETTLEMENT": ("settlement", "交收", "结算"),
    "SELLABILITY": ("sellability", "可卖"),
}


@dataclass(frozen=True)
class PreparedAnalysisContext:
    pack: EvidencePack
    retrieval: RetrievalSnapshot | None
    case_memory: tuple[dict[str, object], ...]
    gate: GateResult
    resolved_knowledge_cutoff: datetime


class AnalysisContextBuilder:
    def __init__(self, repository: AIRepository, registry: EvidenceResolverRegistry) -> None:
        self.repository, self.registry = repository, registry

    def _requests(self, request: ResearchAnalysisRequest) -> list[EvidenceRequest]:
        selected: set[tuple[Source, str]] = set()

        def add(source: Source, ids: object) -> None:
            if isinstance(ids, str):
                selected.add((source, ids))
            elif isinstance(ids, tuple | list):
                selected.update((source, str(identity)) for identity in ids)

        kind = request.analysis_type
        if kind == AnalysisType.MARKET_DIAGNOSIS:
            if (
                request.experiment_id
                or request.paper_session_id
                or request.strategy_version_ids
                or request.backtest_run_ids
                or request.paper_account_snapshot_ids
                or request.risk_decision_ids
            ):
                raise ValueError("ANALYSIS_SOURCE_POLICY_VIOLATION")
            add(Source.DATASET_VERSION, request.dataset_version_ids)
            add(Source.MARKET_DATA_SNAPSHOT, request.market_data_snapshot_id)
        else:
            add(Source.STRATEGY_VERSION, request.strategy_version_ids)
            add(Source.BACKTEST_RUN, request.backtest_run_ids)
            add(Source.MARKET_DATA_SNAPSHOT, request.backtest_run_ids)
            add(Source.RESEARCH_DIAGNOSTIC, request.backtest_run_ids)
            if kind == AnalysisType.EXPERIMENT_REVIEW:
                add(Source.RESEARCH_EXPERIMENT, request.experiment_id)
                add(Source.RESEARCH_COMPARISON, request.experiment_id)
            elif request.experiment_id:
                raise ValueError("ANALYSIS_SOURCE_POLICY_VIOLATION")
            if kind == AnalysisType.PAPER_REVIEW:
                add(Source.PAPER_SESSION, request.paper_session_id)
                add(Source.MARKET_DATA_SNAPSHOT, request.paper_session_id)
                add(Source.PAPER_ACCOUNT_SNAPSHOT, request.paper_account_snapshot_ids)
                add(Source.RISK_DECISION, request.risk_decision_ids)
            elif (
                request.paper_session_id
                or request.paper_account_snapshot_ids
                or request.risk_decision_ids
            ):
                raise ValueError("ANALYSIS_SOURCE_POLICY_VIOLATION")
            if request.dataset_version_ids or request.market_data_snapshot_id:
                raise ValueError("ANALYSIS_SOURCE_POLICY_VIOLATION")
        return [
            EvidenceRequest(source_type=source, source_id=identity)
            for source, identity in sorted(selected)
        ]

    def build(
        self,
        request: ResearchAnalysisRequest,
        *,
        persist_observations: Callable[[dict[str, object]], None] | None = None,
    ) -> PreparedAnalysisContext:
        if request.market != "CN_A_SHARE":
            raise ValueError("ANALYSIS_MARKET_FOUNDATION_UNAVAILABLE")
        if request.analysis_type == AnalysisType.PAPER_REVIEW:
            self.registry.validate_paper_relationships(
                paper_session_id=request.paper_session_id or "",
                paper_account_snapshot_ids=request.paper_account_snapshot_ids,
                risk_decision_ids=request.risk_decision_ids,
            )
        findings: list[ValidationFinding] = []
        items: list[CanonicalEvidenceItem] = []
        observed: dict[tuple[Source, str], tuple[CanonicalEvidenceItem, ...]] = {}

        def observe(selection: EvidenceRequest) -> tuple[CanonicalEvidenceItem, ...]:
            identity = (selection.source_type, selection.source_id)
            if identity not in observed:
                observed[identity] = ()
                observed[identity] = self.registry.resolve(
                    EvidenceRequest(
                        source_type=selection.source_type, source_id=selection.source_id
                    )
                )
            return tuple(
                item
                for item in observed[identity]
                if not selection.fields or item.field_path in selection.fields
            )

        for selection in self._requests(request):
            try:
                resolved = observe(selection)
                items.extend(resolved)
                # Experiment links are explicit Core-resolved identities, never user field paths.
                if selection.source_type == Source.RESEARCH_EXPERIMENT:
                    links = next(
                        (i.value for i in resolved if i.field_path == "linked_run_ids"), []
                    )
                    if isinstance(links, list | tuple):
                        for run_id in sorted(set(str(link) for link in links))[:20]:
                            for source in (
                                Source.BACKTEST_RUN,
                                Source.MARKET_DATA_SNAPSHOT,
                                Source.RESEARCH_DIAGNOSTIC,
                                Source.RESEARCH_REPORT,
                            ):
                                items.extend(
                                    observe(EvidenceRequest(source_type=source, source_id=run_id))
                                )
            except EvidenceResolverError as error:
                code = (
                    "TEMPORAL_METADATA_UNAVAILABLE"
                    if isinstance(error, TemporalMetadataUnavailable)
                    else "INSUFFICIENT_EVIDENCE"
                )
                findings.append(_finding(ValidationLayer.TEMPORAL, code, retryable=False))
        items = list({item.ref: item for item in items}.values())
        if persist_observations is not None:
            persist_observations(
                {
                    "items": [item.model_dump(mode="json") for item in items],
                    "findings": [finding.model_dump(mode="json") for finding in findings],
                }
            )
        cutoff = request.knowledge_cutoff
        if request.knowledge_cutoff_mode == "SERVER_FROZEN_CURRENT":
            if persist_observations is None:
                raise ValueError("ANALYSIS_DURABLE_OBSERVATION_REQUIRED")
            cutoff = datetime.now(UTC)
        if cutoff is None:
            raise ValueError("ANALYSIS_KNOWLEDGE_CUTOFF_REQUIRED")
        # No multi-market foundation is manufactured by orchestration.
        if request.market not in {"CN_A_SHARE", "US_EQUITY"} or request.asset_type not in {
            "EQUITY",
            "ETF",
        }:
            raise ValueError("ANALYSIS_MARKET_UNSUPPORTED")
        timezone = "Asia/Shanghai" if request.market == "CN_A_SHARE" else "America/New_York"
        instruments = {i.instrument_id for i in items if i.instrument_id}
        instrument = request.instrument_id or (
            next(iter(instruments))
            if len(instruments) == 1
            else "UNIVERSE:" + fingerprint_payload(sorted(request.universe or ()))[:32]
        )
        context = EvidenceContext(
            market=cast(Market, request.market),
            asset_type=request.asset_type,
            instrument_id=instrument,
            timezone=timezone,
            currency="CNY" if request.market == "CN_A_SHARE" else "USD",
        )
        temporal = TemporalContext(
            market=context.market,
            asset_type=context.asset_type,
            timezone=timezone,
            analysis_mode=request.analysis_mode.value,
            market_data_cutoff=request.market_data_cutoff,
            knowledge_cutoff=cutoff,
        )
        text_question = request.research_question.casefold()
        topics = tuple(
            cast(RuleTopic, topic)
            for topic, terms in RULE_WORDS.items()
            if any(term in text_question for term in terms)
        )
        requirements = AnalysisRequirements(
            required_rule_topics=topics,
            requires_comparability=request.analysis_type == AnalysisType.EXPERIMENT_REVIEW,
        )
        valid: dict[str, CanonicalEvidenceItem] = {}
        for item in items:
            try:
                EvidencePackService._validate_item(item, temporal, context)
                valid[item.ref] = item
            except EvidencePackError as error:
                findings.append(_finding(ValidationLayer.TEMPORAL, error.code, retryable=False))
        items = list(valid.values())
        if not items:
            findings.append(
                _finding(ValidationLayer.GROUNDING, "INSUFFICIENT_EVIDENCE", retryable=False)
            )
        if request.analysis_type == AnalysisType.MARKET_DIAGNOSIS:
            # Existing market snapshot exposes metadata only, not trend/volatility facts.
            findings.append(
                _finding(ValidationLayer.GROUNDING, "INSUFFICIENT_EVIDENCE", retryable=False)
            )
        if request.analysis_type == AnalysisType.STRATEGY_REVIEW and not any(
            i.source_type == Source.BACKTEST_RUN for i in items
        ):
            findings.append(
                _finding(ValidationLayer.GROUNDING, "INSUFFICIENT_EVIDENCE", retryable=False)
            )
        if request.analysis_type == AnalysisType.EXPERIMENT_REVIEW:
            ranking = [
                i
                for i in items
                if i.source_type == Source.RESEARCH_COMPARISON and i.field_path == "ranking_allowed"
            ]
            if not ranking:
                findings.append(
                    _finding(ValidationLayer.GROUNDING, "INSUFFICIENT_EVIDENCE", retryable=False)
                )
            elif any(i.value is not True for i in ranking):
                findings.append(
                    _finding(ValidationLayer.SEMANTIC, "NOT_COMPARABLE", retryable=False)
                )
        if request.analysis_type == AnalysisType.PAPER_REVIEW and not any(
            i.source_type == Source.PAPER_ACCOUNT_SNAPSHOT for i in items
        ):
            findings.append(
                _finding(ValidationLayer.GROUNDING, "INSUFFICIENT_EVIDENCE", retryable=False)
            )
        case = ResearchCaseService(self.repository).freeze(
            ResearchCaseInput(
                purpose=request.analysis_type.value,
                market=context.market,
                exchange="ANALYSIS_SCOPE",
                symbol=instrument,
                instrument_id=instrument,
                asset_type=context.asset_type,
                currency=context.currency or "",
                timeframe="RESEARCH",
                as_of_utc=request.market_data_cutoff,
                market_local_trade_date=request.market_data_cutoff.astimezone(SHANGHAI_TZ).date(),
                bindings={
                    "market_data_fingerprint": fingerprint_payload(
                        [i.source_fingerprint for i in items]
                    ),
                    "calendar_fingerprint": next(
                        (i.value for i in items if i.field_path == "calendar_fingerprint"), None
                    ),
                    "market_rules_fingerprint": None,
                    "request_fingerprint": fingerprint_payload(request.model_dump(mode="python")),
                },
            ),
            actor="USER",
        )
        retrieval = None
        memory: list[dict[str, object]] = []
        if request.requested_case_count:
            retrieval = ResearchCaseRetrievalService(self.repository).retrieve(
                RetrievalQuery(
                    market=context.market,
                    asset_type=context.asset_type,
                    market_data_cutoff=request.market_data_cutoff,
                    knowledge_cutoff=cutoff,
                    query_text=request.research_question[:500],
                    universe=tuple(
                        sorted(
                            request.universe
                            or ((request.instrument_id,) if request.instrument_id else ())
                        )
                    ),
                    requires_market_rules=requirements.market_rules_required,
                    limit=request.requested_case_count,
                )
            )
            for candidate in retrieval.candidates:
                document = self.repository.get_research_case_document_by_case_id(candidate.case_id)
                if (
                    document is None
                    or document.document_fingerprint != candidate.document_fingerprint
                ):
                    raise ValueError("ANALYSIS_CASE_DOCUMENT_DRIFT")
                case_items = resolve_case_evidence(
                    self.repository,
                    self.registry,
                    case_id=candidate.case_id,
                    analysis_type=request.analysis_type,
                    temporal=temporal,
                    context=context,
                    resolver=observe,
                )
                for item in case_items:
                    valid[item.ref] = item
                memory.append(
                    {
                        "case_id": candidate.case_id,
                        "document_id": candidate.document_id,
                        "document_fingerprint": candidate.document_fingerprint,
                        "classification": "CASE_MEMORY_UNTRUSTED",
                        "summary": document.summary[:1000],
                        "strategy_family": document.strategy_family,
                        "success_factors": [
                            str(v)[:300] for v in json.loads(document.success_factors_json)[:3]
                        ],
                        "failure_factors": [
                            str(v)[:300] for v in json.loads(document.failure_factors_json)[:3]
                        ],
                        "evidence_refs": [i.ref for i in case_items],
                    }
                )
        pack = EvidencePackService(self.repository).freeze(
            case_id=case.id,
            temporal_context=temporal,
            evidence_context=context,
            requirements=requirements,
            items=list(valid.values()),
        )
        if request.freshness_requirement != FreshnessRequirement.HISTORICAL_OK:
            claims = [
                {
                    "claim_id": str(index),
                    "claim_type": "INFERENCE",
                    "text": "证据时效检查",
                    "subject": item.subject,
                    "predicate": "EQ",
                    "value": item.value,
                    "unit": item.unit,
                    "uncertainty": "HIGH",
                    "evidence_refs": [item.ref],
                }
                for index, item in enumerate(pack.items)
            ]
            result = ValidationService().validate(
                {
                    "schema_version": "ai-structured-output-v1",
                    "action_type": "RESEARCH_RECOMMENDATION",
                    "claims": claims,
                },
                pack,
                origin_attempt_id="CONTEXT_PREFLIGHT",
                freshness_requirement=request.freshness_requirement,
                reference_now=datetime.now(UTC),
            )
            findings.extend(result.findings)
        gate = ResearchGate().decide(
            findings=findings, evidence_context=context, requirements=requirements
        )
        return PreparedAnalysisContext(pack, retrieval, tuple(memory), gate, cutoff)
