from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from pathlib import Path
from typing import TypedDict, cast

from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from quant_lab.ai.contracts import (
    AssetType,
    EvidenceClassification,
    EvidenceScalar,
    EvidenceSemanticType,
    EvidenceSourceType,
    FreshnessClass,
    Market,
)
from quant_lab.ai.fingerprints import fingerprint_payload
from quant_lab.ai.resolvers import (
    EvidenceResolverRegistry,
    EvidenceSourceNotFound,
    ExplicitSnapshotResolver,
    SourceLoader,
    SourceSnapshot,
    TemporalMetadataUnavailable,
)
from quant_lab.backtest.persistence import BacktestArtifactModel, BacktestRunModel
from quant_lab.backtest.repository import BacktestRepository
from quant_lab.backtest.strategy_library import (
    StrategyLibrary,
)
from quant_lab.core.config import RunMode
from quant_lab.datasets.persistence import DatasetModel, DatasetVersionModel
from quant_lab.datasets.repository import DatasetRepository
from quant_lab.paper.repository import PaperRepository
from quant_lab.research.artifacts import ArtifactReader
from quant_lab.research.comparability import (
    BacktestComparabilityService,
    BacktestComparisonService,
)
from quant_lab.research.diagnostics import ResearchDiagnosticsService
from quant_lab.research.reports import ResearchReportService
from quant_lab.research.repository import ResearchRepository

FACT = EvidenceClassification.FACT
NOTE = EvidenceClassification.USER_NOTE
METRIC = EvidenceClassification.DERIVED_METRIC
STATE = EvidenceClassification.SYSTEM_STATE
NUMBER = EvidenceSemanticType.NUMBER
MONEY = EvidenceSemanticType.MONEY
RATIO = EvidenceSemanticType.RATIO
COUNT = EvidenceSemanticType.COUNT
TEXT = EvidenceSemanticType.TEXT
ENUM = EvidenceSemanticType.ENUM
DATETIME = EvidenceSemanticType.DATETIME
BOOLEAN = EvidenceSemanticType.BOOLEAN
IDENTIFIER = EvidenceSemanticType.IDENTIFIER
JSON = EvidenceSemanticType.JSON


@dataclass(frozen=True, slots=True)
class SourceFieldPolicy:
    classifications: Mapping[str, EvidenceClassification]
    semantic_types: Mapping[str, EvidenceSemanticType]
    units: Mapping[str, str | None]
    resolver_policy_version: str = "2"

    @property
    def fields(self) -> frozenset[str]:
        return frozenset(self.classifications)


def _policy(
    classifications: Mapping[str, EvidenceClassification],
    semantic_types: Mapping[str, EvidenceSemanticType],
    units: Mapping[str, str | None] | None = None,
) -> SourceFieldPolicy:
    if set(classifications) != set(semantic_types):
        raise ValueError("semantic type policy must cover every source field")
    return SourceFieldPolicy(
        classifications=dict(classifications),
        semantic_types=dict(semantic_types),
        units=dict(units or {}),
    )


SUPPORTED_SOURCE_POLICIES: Mapping[EvidenceSourceType, SourceFieldPolicy] = {
    EvidenceSourceType.DATASET_VERSION: _policy(
        {
            "dataset_id": FACT,
            "version": FACT,
            "row_count": FACT,
            "instrument_count": FACT,
            "min_timestamp": FACT,
            "max_timestamp": FACT,
            "status": STATE,
            "schema_version": FACT,
            "publication_fingerprint": FACT,
            "quality_issue_count": FACT,
        },
        {
            "dataset_id": IDENTIFIER,
            "version": COUNT,
            "row_count": COUNT,
            "instrument_count": COUNT,
            "min_timestamp": DATETIME,
            "max_timestamp": DATETIME,
            "status": ENUM,
            "schema_version": IDENTIFIER,
            "publication_fingerprint": IDENTIFIER,
            "quality_issue_count": COUNT,
        },
    ),
    EvidenceSourceType.MARKET_DATA_SNAPSHOT: _policy(
        {
            "profile_id": STATE,
            "bars_dataset_version_id": FACT,
            "bars_dataset_fingerprint": FACT,
            "calendar_version_id": FACT,
            "calendar_fingerprint": FACT,
            "snapshot_fingerprint": FACT,
        },
        {
            "profile_id": IDENTIFIER,
            "bars_dataset_version_id": IDENTIFIER,
            "bars_dataset_fingerprint": IDENTIFIER,
            "calendar_version_id": IDENTIFIER,
            "calendar_fingerprint": IDENTIFIER,
            "snapshot_fingerprint": IDENTIFIER,
        },
    ),
    EvidenceSourceType.STRATEGY_VERSION: _policy(
        {
            "strategy_id": FACT,
            "strategy_type": FACT,
            "version": FACT,
            "strategy_fingerprint": FACT,
            "specification": NOTE,
        },
        {
            "strategy_id": IDENTIFIER,
            "strategy_type": ENUM,
            "version": COUNT,
            "strategy_fingerprint": IDENTIFIER,
            "specification": JSON,
        },
    ),
    EvidenceSourceType.BACKTEST_RUN: _policy(
        {
            "status": STATE,
            "strategy_version_id": FACT,
            "dataset_version_ids": FACT,
            "run_input_fingerprint": FACT,
            "artifact_hashes": FACT,
            "metrics.sharpe": METRIC,
            "metrics.max_drawdown": METRIC,
            "start_date": FACT,
            "end_date": FACT,
        },
        {
            "status": ENUM,
            "strategy_version_id": IDENTIFIER,
            "dataset_version_ids": JSON,
            "run_input_fingerprint": IDENTIFIER,
            "artifact_hashes": JSON,
            "metrics.sharpe": RATIO,
            "metrics.max_drawdown": RATIO,
            "start_date": DATETIME,
            "end_date": DATETIME,
        },
    ),
    EvidenceSourceType.RESEARCH_EXPERIMENT: _policy(
        {
            "status": STATE,
            "tags": STATE,
            "hypothesis": NOTE,
            "linked_run_ids": FACT,
            "name": FACT,
        },
        {
            "status": ENUM,
            "tags": JSON,
            "hypothesis": TEXT,
            "linked_run_ids": JSON,
            "name": TEXT,
        },
    ),
    EvidenceSourceType.RESEARCH_COMPARISON: _policy(
        {
            "comparability": METRIC,
            "ranking_allowed": METRIC,
            "metric_deltas": METRIC,
            "input_run_ids": FACT,
        },
        {
            "comparability": JSON,
            "ranking_allowed": BOOLEAN,
            "metric_deltas": JSON,
            "input_run_ids": JSON,
        },
    ),
    EvidenceSourceType.RESEARCH_DIAGNOSTIC: _policy(
        {"counts": METRIC, "ratios": METRIC, "run_id": FACT, "artifact_hashes": FACT},
        {"counts": JSON, "ratios": JSON, "run_id": IDENTIFIER, "artifact_hashes": JSON},
    ),
    EvidenceSourceType.RESEARCH_REPORT: _policy(
        {
            "run_ids": FACT,
            "report_fingerprint": FACT,
            "metrics": METRIC,
            "diagnostics": METRIC,
        },
        {
            "run_ids": JSON,
            "report_fingerprint": IDENTIFIER,
            "metrics": JSON,
            "diagnostics": JSON,
        },
    ),
    EvidenceSourceType.PAPER_SESSION: _policy(
        {
            "status": STATE,
            "current_session_date": STATE,
            "version": STATE,
            "snapshot_fingerprint": FACT,
            "strategy_version_id": FACT,
            "replay_range": FACT,
            "execution_config_fingerprint": FACT,
            "account_id": FACT,
        },
        {
            "status": ENUM,
            "current_session_date": DATETIME,
            "version": COUNT,
            "snapshot_fingerprint": IDENTIFIER,
            "strategy_version_id": IDENTIFIER,
            "replay_range": JSON,
            "execution_config_fingerprint": IDENTIFIER,
            "account_id": IDENTIFIER,
        },
    ),
    EvidenceSourceType.PAPER_ACCOUNT_SNAPSHOT: _policy(
        {
            "cash": FACT,
            "market_value": FACT,
            "equity": FACT,
            "gross_exposure": FACT,
            "daily_pnl": FACT,
            "cumulative_pnl": FACT,
            "drawdown": METRIC,
            "session_date": FACT,
        },
        {
            "cash": MONEY,
            "market_value": MONEY,
            "equity": MONEY,
            "gross_exposure": MONEY,
            "daily_pnl": MONEY,
            "cumulative_pnl": MONEY,
            "drawdown": RATIO,
            "session_date": DATETIME,
        },
        {
            "cash": "CURRENCY",
            "market_value": "CURRENCY",
            "equity": "CURRENCY",
            "gross_exposure": "CURRENCY",
            "daily_pnl": "CURRENCY",
            "cumulative_pnl": "CURRENCY",
            "drawdown": "RATIO",
        },
    ),
    EvidenceSourceType.RISK_DECISION: _policy(
        {
            "decision": STATE,
            "reason_codes": FACT,
            "risk_policy_version": FACT,
            "risk_policy_fingerprint": FACT,
            "evaluated_metrics": FACT,
            "freeze_required": STATE,
        },
        {
            "decision": ENUM,
            "reason_codes": JSON,
            "risk_policy_version": COUNT,
            "risk_policy_fingerprint": IDENTIFIER,
            "evaluated_metrics": JSON,
            "freeze_required": BOOLEAN,
        },
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
                field_semantic_types=policy.semantic_types,
                field_units=policy.units,
                resolver_policy_version=policy.resolver_policy_version,
                loader=loader,
            )
        )
    return registry


def _utc(value: datetime | None) -> datetime:
    if value is None:
        raise TemporalMetadataUnavailable("required temporal metadata is unavailable")
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _date_utc(value: date) -> datetime:
    return datetime.combine(value, time.max, tzinfo=UTC)


class _MarketIdentity(TypedDict):
    market: Market
    asset_type: AssetType
    currency: str
    effective_at: datetime


def _market(value: str) -> Market:
    normalized = value.upper()
    if normalized in {"CN", "CN_A_SHARE", "A_SHARE"}:
        return "CN_A_SHARE"
    if normalized in {"US", "US_EQUITY", "USA"}:
        return "US_EQUITY"
    raise EvidenceSourceNotFound("source market is not supported by AI-2")


def _market_identity(session: Session, dataset_version_id: str) -> _MarketIdentity:
    version = session.get(DatasetVersionModel, dataset_version_id)
    if version is None:
        raise EvidenceSourceNotFound("frozen dataset version does not exist")
    dataset = session.get(DatasetModel, version.dataset_id)
    if dataset is None:
        raise EvidenceSourceNotFound("dataset does not exist")
    market = _market(dataset.market)
    return {
        "market": market,
        "asset_type": "ETF" if dataset.dataset_type.upper() == "ETF" else "EQUITY",
        "currency": "USD" if market == "US_EQUITY" else "CNY",
        "effective_at": _utc(version.max_timestamp),
    }


def _snapshot_identity(session: Session, payload: Mapping[str, object]) -> _MarketIdentity:
    version_id = payload.get("bars_dataset_version_id")
    if not isinstance(version_id, str):
        raise TemporalMetadataUnavailable("frozen snapshot lacks dataset version")
    return _market_identity(session, version_id)


def _source_snapshot(
    *,
    source_id: str,
    source_version_id: str,
    source_fingerprint: str,
    subject: str,
    effective_at: datetime,
    known_at: datetime,
    market: Market,
    asset_type: AssetType,
    currency: str | None,
    values: Mapping[str, object],
    analysis_scope: str,
) -> SourceSnapshot:
    return SourceSnapshot(
        source_entity_id=source_id,
        source_version_id=source_version_id,
        source_fingerprint=source_fingerprint,
        subject=subject,
        effective_at=effective_at,
        known_at=known_at,
        observed_at=known_at,
        market_timestamp=effective_at,
        freshness_class=FreshnessClass.IMMUTABLE_HISTORICAL,
        market=market,
        asset_type=asset_type,
        instrument_id=None,
        currency=currency,
        context={"market": market, "analysis_scope": analysis_scope},
        values=cast(Mapping[str, EvidenceScalar], values),
    )


class _DomainSnapshotLoaders:
    """Eleven explicit read-only adapters over existing domain repositories/services."""

    def __init__(self, engine: Engine, artifact_root: Path, clock: Callable[[], datetime]) -> None:
        self.engine = engine
        self.clock = clock
        self.datasets = DatasetRepository(engine, run_mode=RunMode.RESEARCH)
        self.runs = BacktestRepository(engine)
        self.research = ResearchRepository(engine)
        self.paper = PaperRepository(engine)
        self.library = StrategyLibrary(engine)
        self.reader = ArtifactReader(artifact_root)
        self.diagnostics = ResearchDiagnosticsService(self.reader)
        self.comparison = BacktestComparisonService(
            self.runs,
            self.reader,
            self.library,
            BacktestComparabilityService(),
        )
        self.reports = ResearchReportService(
            self.runs, self.reader, self.diagnostics, self.research
        )

    def dataset_version(self, source_id: str) -> SourceSnapshot:
        with Session(self.engine) as session:
            version = session.get(DatasetVersionModel, source_id)
            if version is None:
                raise EvidenceSourceNotFound("dataset version does not exist")
            dataset = session.get(DatasetModel, version.dataset_id)
            if dataset is None:
                raise EvidenceSourceNotFound("dataset does not exist")
            version = self.datasets.get_version(dataset.dataset_id, source_id)
            identity = _market_identity(session, source_id)
            known_at = _utc(version.published_at or version.created_at)
            values = {
                "dataset_id": version.dataset_id,
                "version": version.version,
                "row_count": version.row_count,
                "instrument_count": version.instrument_count,
                "min_timestamp": version.min_timestamp,
                "max_timestamp": version.max_timestamp,
                "status": version.status,
                "schema_version": version.schema_version,
                "publication_fingerprint": version.publication_fingerprint,
                "quality_issue_count": version.quality_issue_count,
            }
            return _source_snapshot(
                source_id=source_id,
                source_version_id=str(version.version),
                source_fingerprint=version.publication_fingerprint,
                subject=dataset.logical_key,
                effective_at=identity["effective_at"],
                known_at=known_at,
                market=identity["market"],
                asset_type=identity["asset_type"],
                currency=identity["currency"],
                values=values,
                analysis_scope="DATASET_VERSION",
            )

    def market_data_snapshot(self, source_id: str) -> SourceSnapshot:
        try:
            run = self.runs.get(source_id)
        except Exception:
            run = None
        if run is None:
            try:
                paper = self.paper.get_session(source_id)
            except Exception:
                paper = None
        else:
            paper = None
        with Session(self.engine) as session:
            if run is not None:
                payload = json.loads(run.market_data_snapshot_json)
                known_at = _utc(run.created_at)
                fingerprint = run.market_data_snapshot_fingerprint
            elif paper is not None:
                payload = json.loads(paper.market_data_snapshot_json)
                known_at = _utc(paper.created_at)
                fingerprint = paper.market_data_snapshot_fingerprint
            else:
                raise EvidenceSourceNotFound("frozen market-data snapshot does not exist")
            identity = _snapshot_identity(session, payload)
            values = {
                "profile_id": payload.get("profile_id"),
                "bars_dataset_version_id": payload.get("bars_dataset_version_id"),
                "bars_dataset_fingerprint": payload.get("bars_dataset_fingerprint"),
                "calendar_version_id": payload.get("calendar_version_id"),
                "calendar_fingerprint": payload.get("calendar_fingerprint"),
                "snapshot_fingerprint": payload.get("snapshot_fingerprint", fingerprint),
            }
            return _source_snapshot(
                source_id=source_id,
                source_version_id=fingerprint,
                source_fingerprint=fingerprint,
                subject=f"MARKET_DATA_SNAPSHOT:{source_id}",
                effective_at=identity["effective_at"],
                known_at=known_at,
                market=identity["market"],
                asset_type=identity["asset_type"],
                currency=identity["currency"],
                values=values,
                analysis_scope="FROZEN_MARKET_DATA",
            )

    def strategy_version(self, source_id: str) -> SourceSnapshot:
        try:
            version, strategy_type = self.library.version(source_id)
        except Exception as error:
            raise EvidenceSourceNotFound("strategy version does not exist") from error
        values = {
            "strategy_id": version.strategy_definition_id,
            "strategy_type": strategy_type,
            "version": version.version,
            "strategy_fingerprint": version.strategy_fingerprint,
            "specification": json.loads(version.strategy_spec_json),
        }
        known_at = _utc(version.created_at)
        return _source_snapshot(
            source_id=source_id,
            source_version_id=str(version.version),
            source_fingerprint=version.strategy_fingerprint,
            subject=f"STRATEGY:{version.strategy_definition_id}",
            effective_at=known_at,
            known_at=known_at,
            market="CN_A_SHARE",
            asset_type="EQUITY",
            currency=None,
            values=values,
            analysis_scope="STRATEGY_VERSION",
        )

    def _run_parts(
        self, source_id: str
    ) -> tuple[BacktestRunModel, dict[str, object], _MarketIdentity]:
        try:
            run = self.runs.get(source_id)
        except Exception as error:
            raise EvidenceSourceNotFound("backtest run does not exist") from error
        payload = json.loads(run.market_data_snapshot_json)
        with Session(self.engine) as session:
            identity = _snapshot_identity(session, payload)
        return run, payload, identity

    def _artifacts_and_metrics(
        self, source_id: str
    ) -> tuple[tuple[BacktestArtifactModel, ...], dict[str, object]]:
        artifacts = self.runs.artifacts(source_id)
        metrics_artifact = next(
            (artifact for artifact in artifacts if artifact.artifact_type == "METRICS"), None
        )
        metrics = self.reader.read_json(metrics_artifact) if metrics_artifact else {}
        return artifacts, metrics

    def backtest_run(self, source_id: str) -> SourceSnapshot:
        run, payload, identity = self._run_parts(source_id)
        artifacts, metrics = self._artifacts_and_metrics(source_id)
        artifact_hashes = {artifact.artifact_type: artifact.sha256 for artifact in artifacts}
        values = {
            "status": run.status,
            "strategy_version_id": run.strategy_version_id,
            "dataset_version_ids": [payload.get("bars_dataset_version_id")],
            "run_input_fingerprint": run.run_input_fingerprint,
            "artifact_hashes": artifact_hashes,
            "metrics.sharpe": metrics.get("sharpe_ratio"),
            "metrics.max_drawdown": metrics.get("max_drawdown"),
            "start_date": _date_utc(run.start_date),
            "end_date": _date_utc(run.end_date),
        }
        return _source_snapshot(
            source_id=source_id,
            source_version_id=run.run_input_fingerprint,
            source_fingerprint=fingerprint_payload(
                {"run": run.run_input_fingerprint, "artifacts": artifact_hashes}
            ),
            subject=f"BACKTEST_RUN:{source_id}",
            effective_at=identity["effective_at"],
            known_at=_utc(run.completed_at or run.created_at),
            market=identity["market"],
            asset_type=identity["asset_type"],
            currency=identity["currency"],
            values=values,
            analysis_scope="BACKTEST_RUN",
        )

    def research_experiment(self, source_id: str) -> SourceSnapshot:
        try:
            experiment = self.research.get_experiment(source_id)
        except Exception as error:
            raise EvidenceSourceNotFound("research experiment does not exist") from error
        links = self.research.list_run_links(source_id)
        runs = [self.runs.get(link.backtest_run_id) for link in links]
        if not runs:
            raise TemporalMetadataUnavailable("experiment has no frozen run context")
        first_payload = json.loads(runs[0].market_data_snapshot_json)
        with Session(self.engine) as session:
            identity = _snapshot_identity(session, first_payload)
        values = {
            "status": experiment.status,
            "tags": json.loads(experiment.tags_json),
            "hypothesis": experiment.hypothesis,
            "linked_run_ids": [link.backtest_run_id for link in links],
            "name": experiment.name,
        }
        fingerprint = fingerprint_payload(values)
        return _source_snapshot(
            source_id=source_id,
            source_version_id=fingerprint,
            source_fingerprint=fingerprint,
            subject=f"RESEARCH_EXPERIMENT:{source_id}",
            effective_at=max(_date_utc(run.end_date) for run in runs),
            # Current mutable links have no revision history. This projection is
            # first known when Core observes it, never at an old backtest date.
            known_at=max(
                _utc(self.clock()),
                _utc(experiment.updated_at),
                *(_utc(link.created_at) for link in links),
                *(_utc(run.completed_at or run.created_at) for run in runs),
            ),
            market=identity["market"],
            asset_type=identity["asset_type"],
            currency=identity["currency"],
            values=values,
            analysis_scope="RESEARCH_EXPERIMENT",
        )

    def research_comparison(self, source_id: str) -> SourceSnapshot:
        try:
            experiment = self.research.get_experiment(source_id)
        except Exception as error:
            raise EvidenceSourceNotFound("research experiment does not exist") from error
        links = self.research.list_run_links(source_id)
        runs = [self.runs.get(link.backtest_run_id) for link in links]
        if not runs:
            raise TemporalMetadataUnavailable("comparison has no runs")
        comparison = self.comparison.compare(experiment, links, runs)
        first_payload = json.loads(runs[0].market_data_snapshot_json)
        with Session(self.engine) as session:
            identity = _snapshot_identity(session, first_payload)
        raw_rows = comparison.get("runs", [])
        rows = (
            [row for row in raw_rows if isinstance(row, dict)] if isinstance(raw_rows, list) else []
        )
        values = {
            "comparability": [row.get("comparability") for row in rows],
            "ranking_allowed": comparison.get("ranking_allowed"),
            "metric_deltas": [row.get("deltas") for row in rows],
            "input_run_ids": [run.backtest_run_id for run in runs],
        }
        fingerprint = fingerprint_payload(values)
        return _source_snapshot(
            source_id=source_id,
            source_version_id=fingerprint,
            source_fingerprint=fingerprint,
            subject=f"RESEARCH_COMPARISON:{source_id}",
            effective_at=max(_date_utc(run.end_date) for run in runs),
            known_at=max(
                _utc(self.clock()),
                _utc(experiment.updated_at),
                *(_utc(link.created_at) for link in links),
                *(_utc(run.completed_at or run.created_at) for run in runs),
            ),
            market=identity["market"],
            asset_type=identity["asset_type"],
            currency=identity["currency"],
            values=values,
            analysis_scope="RESEARCH_COMPARISON",
        )

    def research_diagnostic(self, source_id: str) -> SourceSnapshot:
        run, _payload, identity = self._run_parts(source_id)
        artifacts = self.runs.artifacts(source_id)
        result = self.diagnostics.compute(run, artifacts)
        counts = {
            "execution": result.get("execution"),
            "data_quality": result.get("data_quality"),
        }
        ratios = {"portfolio": result.get("portfolio"), "cost": result.get("cost")}
        artifact_hashes = {artifact.artifact_type: artifact.sha256 for artifact in artifacts}
        values = {
            "counts": counts,
            "ratios": ratios,
            "run_id": source_id,
            "artifact_hashes": artifact_hashes,
        }
        fingerprint = fingerprint_payload(
            {"policy": result.get("policy_version"), "values": values}
        )
        return _source_snapshot(
            source_id=source_id,
            source_version_id=str(result.get("policy_version", "1")),
            source_fingerprint=fingerprint,
            subject=f"RESEARCH_DIAGNOSTIC:{source_id}",
            effective_at=identity["effective_at"],
            known_at=_utc(run.completed_at or run.created_at),
            market=identity["market"],
            asset_type=identity["asset_type"],
            currency=identity["currency"],
            values=values,
            analysis_scope="RESEARCH_DIAGNOSTIC",
        )

    def research_report(self, source_id: str) -> SourceSnapshot:
        run, _payload, identity = self._run_parts(source_id)
        strategy_identity: dict[str, object] = {
            "strategy_type": run.strategy_type,
            "strategy_version_id": run.strategy_version_id,
            "strategy_fingerprint": run.strategy_fingerprint,
        }
        report = self.reports.run_report(run, strategy_identity)
        values = {
            "run_ids": [source_id],
            "metrics": report.get("metrics"),
            "diagnostics": report.get("diagnostics"),
        }
        projection_fingerprint = fingerprint_payload(
            {
                "projection_policy_version": "2",
                "run_input_fingerprint": run.run_input_fingerprint,
                "artifact_integrity": report["artifact_integrity"],
                "values": values,
            }
        )
        values["report_fingerprint"] = projection_fingerprint
        return _source_snapshot(
            source_id=source_id,
            source_version_id=projection_fingerprint,
            source_fingerprint=projection_fingerprint,
            subject=f"RESEARCH_REPORT:{source_id}",
            effective_at=identity["effective_at"],
            known_at=_utc(run.completed_at or run.created_at),
            market=identity["market"],
            asset_type=identity["asset_type"],
            currency=identity["currency"],
            values=values,
            analysis_scope="RESEARCH_REPORT",
        )

    def paper_session(self, source_id: str) -> SourceSnapshot:
        try:
            paper = self.paper.get_session(source_id)
        except Exception as error:
            raise EvidenceSourceNotFound("paper session does not exist") from error
        with Session(self.engine) as session:
            payload = json.loads(paper.market_data_snapshot_json)
            identity = _snapshot_identity(session, payload)
            values = {
                "status": paper.status,
                "current_session_date": (
                    _date_utc(paper.current_session_date)
                    if paper.current_session_date is not None
                    else None
                ),
                "version": paper.version,
                "snapshot_fingerprint": paper.market_data_snapshot_fingerprint,
                "strategy_version_id": paper.strategy_version_id,
                "replay_range": {
                    "start": paper.replay_start_date.isoformat(),
                    "end": paper.replay_end_date.isoformat()
                    if paper.replay_end_date is not None
                    else None,
                },
                "execution_config_fingerprint": paper.execution_config_fingerprint,
                "account_id": paper.paper_account_id,
            }
            fingerprint = fingerprint_payload(
                {"session": source_id, "version": paper.version, "values": values}
            )
            return _source_snapshot(
                source_id=source_id,
                source_version_id=str(paper.version),
                source_fingerprint=fingerprint,
                subject=f"PAPER_SESSION:{source_id}",
                effective_at=identity["effective_at"],
                known_at=_utc(paper.updated_at),
                market=identity["market"],
                asset_type=identity["asset_type"],
                currency=identity["currency"],
                values=values,
                analysis_scope="PAPER_SESSION",
            )

    def paper_account_snapshot(self, source_id: str) -> SourceSnapshot:
        try:
            snapshot = self.paper.get_snapshot(source_id)
            paper = self.paper.get_session(snapshot.paper_session_id)
            account = self.paper.get_account(snapshot.paper_account_id)
        except Exception as error:
            raise EvidenceSourceNotFound("paper account snapshot does not exist") from error
        with Session(self.engine) as session:
            payload = json.loads(paper.market_data_snapshot_json)
            identity = _snapshot_identity(session, payload)
            values = {
                "cash": snapshot.cash,
                "market_value": snapshot.market_value,
                "equity": snapshot.equity,
                "gross_exposure": snapshot.gross_exposure,
                "daily_pnl": snapshot.daily_pnl,
                "cumulative_pnl": snapshot.cumulative_pnl,
                "drawdown": snapshot.drawdown,
                "session_date": _date_utc(snapshot.session_date),
            }
            fingerprint = fingerprint_payload(
                {"snapshot": source_id, "created_at": _utc(snapshot.created_at), "values": values}
            )
            return _source_snapshot(
                source_id=source_id,
                source_version_id=fingerprint,
                source_fingerprint=fingerprint,
                subject=f"PAPER_ACCOUNT:{snapshot.paper_account_id}",
                effective_at=_date_utc(snapshot.session_date),
                known_at=_utc(snapshot.created_at),
                market=identity["market"],
                asset_type=identity["asset_type"],
                currency=account.base_currency,
                values=values,
                analysis_scope="PAPER_ACCOUNT_SNAPSHOT",
            )

    def risk_decision(self, source_id: str) -> SourceSnapshot:
        try:
            decision = self.paper.get_risk_decision(source_id)
            intent = self.paper.get_intent(decision.order_intent_id)
            policy = self.paper.get_policy_version(decision.risk_policy_version_id)
            paper = self.paper.get_session(intent.paper_session_id)
        except Exception as error:
            raise EvidenceSourceNotFound("risk decision does not exist") from error
        with Session(self.engine) as session:
            payload = json.loads(paper.market_data_snapshot_json)
            identity = _snapshot_identity(session, payload)
            market_context = json.loads(decision.market_context_json)
            evaluated_metrics = market_context.get("evaluated_metrics")
            if not isinstance(evaluated_metrics, dict):
                raise EvidenceSourceNotFound("persisted risk evaluation metrics are unavailable")
            values = {
                "decision": decision.decision,
                "reason_codes": json.loads(decision.reason_codes_json),
                "risk_policy_version": decision.risk_policy_version,
                "risk_policy_fingerprint": policy.policy_fingerprint,
                "evaluated_metrics": evaluated_metrics,
                "freeze_required": bool(
                    {"DAILY_LOSS_LIMIT", "DRAWDOWN_LIMIT"}
                    & set(json.loads(decision.reason_codes_json))
                ),
            }
            fingerprint = fingerprint_payload(
                {"decision": source_id, "policy": policy.policy_fingerprint, "values": values}
            )
            return _source_snapshot(
                source_id=source_id,
                source_version_id=fingerprint,
                source_fingerprint=fingerprint,
                subject=intent.instrument_id,
                effective_at=_utc(decision.evaluated_at),
                known_at=_utc(decision.evaluated_at),
                market=identity["market"],
                asset_type=identity["asset_type"],
                currency=identity["currency"],
                values=values,
                analysis_scope="RISK_DECISION",
            ).model_copy(update={"instrument_id": intent.instrument_id})


def build_domain_resolver_registry(
    *,
    engine: Engine,
    artifact_root: Path,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> EvidenceResolverRegistry:
    loaders = _DomainSnapshotLoaders(engine, artifact_root, clock)
    return build_supported_resolver_registry(
        {
            EvidenceSourceType.DATASET_VERSION: loaders.dataset_version,
            EvidenceSourceType.MARKET_DATA_SNAPSHOT: loaders.market_data_snapshot,
            EvidenceSourceType.STRATEGY_VERSION: loaders.strategy_version,
            EvidenceSourceType.BACKTEST_RUN: loaders.backtest_run,
            EvidenceSourceType.RESEARCH_EXPERIMENT: loaders.research_experiment,
            EvidenceSourceType.RESEARCH_COMPARISON: loaders.research_comparison,
            EvidenceSourceType.RESEARCH_DIAGNOSTIC: loaders.research_diagnostic,
            EvidenceSourceType.RESEARCH_REPORT: loaders.research_report,
            EvidenceSourceType.PAPER_SESSION: loaders.paper_session,
            EvidenceSourceType.PAPER_ACCOUNT_SNAPSHOT: loaders.paper_account_snapshot,
            EvidenceSourceType.RISK_DECISION: loaders.risk_decision,
        }
    )
