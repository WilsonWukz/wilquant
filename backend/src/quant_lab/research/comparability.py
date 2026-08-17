from __future__ import annotations

import json
from decimal import Decimal

from quant_lab.backtest.repository import BacktestRepository
from quant_lab.backtest.strategy_library import StrategyLibrary
from quant_lab.datasets.errors import DatasetError
from quant_lab.research.artifacts import ArtifactReader
from quant_lab.research.domain import ComparabilityStatus, RunRole


def _frozen_factors(run) -> dict[str, object]:
    snapshot = json.loads(run.market_data_snapshot_json)
    config = json.loads(run.config_json)
    return {
        "dataset_version_id": snapshot.get("bars_dataset_version_id"),
        "calendar_version_id": snapshot.get("calendar_version_id"),
        "snapshot_fingerprint": run.market_data_snapshot_fingerprint,
        "start_date": run.start_date.isoformat(),
        "end_date": run.end_date.isoformat(),
        "initial_cash": _decimal_text(run.initial_cash),
        "fee_policy": _canonical(config.get("fee_policy")),
        "slippage_policy": _canonical(config.get("slippage_policy")),
        "max_volume_participation": _canonical(config.get("max_volume_participation")),
        "instrument_metadata_overrides": _canonical(config.get("instrument_metadata_overrides")),
        "engine_version": run.engine_version,
    }


def _canonical(value: object) -> object:
    return json.dumps(value, sort_keys=True, default=str) if value is not None else None


def _decimal_text(value: Decimal) -> str:
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


class BacktestComparabilityService:
    """Deterministic comparability guard based on each Run's frozen snapshot."""

    def compute(self, baseline_run, candidate_run) -> dict[str, object]:
        baseline = _frozen_factors(baseline_run)
        candidate = _frozen_factors(candidate_run)
        checks: list[dict[str, object]] = []
        reasons: list[str] = []

        def check(name: str, key: str, reason: str) -> bool:
            passed = baseline[key] == candidate[key]
            checks.append(
                {
                    "name": name,
                    "passed": passed,
                    "baseline_value": baseline[key],
                    "candidate_value": candidate[key],
                }
            )
            if not passed:
                reasons.append(reason)
            return passed

        check("SAME_DATASET_VERSION", "dataset_version_id", "DIFFERENT_DATASET_VERSION")
        check("SAME_CALENDAR_VERSION", "calendar_version_id", "DIFFERENT_CALENDAR_VERSION")
        same_range = (
            baseline["start_date"] == candidate["start_date"]
            and baseline["end_date"] == candidate["end_date"]
        )
        checks.append(
            {
                "name": "SAME_DATE_RANGE",
                "passed": same_range,
                "baseline_value": f"{baseline['start_date']}..{baseline['end_date']}",
                "candidate_value": f"{candidate['start_date']}..{candidate['end_date']}",
            }
        )
        if not same_range:
            reasons.append("DIFFERENT_DATE_RANGE")
        check("SAME_INITIAL_CASH", "initial_cash", "DIFFERENT_INITIAL_CASH")
        check("SAME_FEE_POLICY", "fee_policy", "DIFFERENT_FEE_POLICY")
        check("SAME_SLIPPAGE_POLICY", "slippage_policy", "DIFFERENT_SLIPPAGE_POLICY")
        check("SAME_ENGINE_VERSION", "engine_version", "DIFFERENT_ENGINE_VERSION")
        check(
            "SAME_VOLUME_PARTICIPATION",
            "max_volume_participation",
            "DIFFERENT_VOLUME_PARTICIPATION",
        )
        check(
            "SAME_INSTRUMENT_METADATA",
            "instrument_metadata_overrides",
            "DIFFERENT_INSTRUMENT_METADATA",
        )

        succeeded = baseline_run.status == "SUCCEEDED" and candidate_run.status == "SUCCEEDED"
        checks.append(
            {
                "name": "RUN_SUCCEEDED",
                "passed": succeeded,
                "baseline_value": baseline_run.status,
                "candidate_value": candidate_run.status,
            }
        )
        if not succeeded:
            reasons.append("RUN_NOT_SUCCEEDED")

        same_market_env = (
            baseline["dataset_version_id"] == candidate["dataset_version_id"]
            and baseline["calendar_version_id"] == candidate["calendar_version_id"]
            and same_range
            and baseline["engine_version"] == candidate["engine_version"]
        )
        if not same_market_env or not succeeded:
            status = ComparabilityStatus.NOT_COMPARABLE.value
        elif len(reasons) == 0:
            status = ComparabilityStatus.STRICTLY_COMPARABLE.value
        else:
            status = ComparabilityStatus.PARTIALLY_COMPARABLE.value

        return {
            "status": status,
            "reasons": sorted(set(reasons)),
            "checks": checks,
        }


def _run_metrics(
    run_repository: BacktestRepository, reader: ArtifactReader, run
) -> dict[str, object]:
    artifacts = run_repository.artifacts(run.backtest_run_id)
    metrics_artifact = next((a for a in artifacts if a.artifact_type == "METRICS"), None)
    if metrics_artifact is None:
        return {}
    return reader.read_json(metrics_artifact)


class BacktestComparisonService:
    def __init__(
        self,
        run_repository: BacktestRepository,
        reader: ArtifactReader,
        strategy_library: StrategyLibrary,
        comparability: BacktestComparabilityService,
    ) -> None:
        self.runs = run_repository
        self.reader = reader
        self.library = strategy_library
        self.comparability = comparability

    def _strategy_identity(self, run) -> dict[str, object]:
        identity: dict[str, object] = {
            "strategy_type": run.strategy_type,
            "strategy_fingerprint": run.strategy_fingerprint,
            "strategy_definition_id": None,
            "strategy_version_id": run.strategy_version_id,
            "strategy_name": None,
            "strategy_version": None,
        }
        if run.strategy_version_id:
            try:
                version, _ = self.library.version(run.strategy_version_id)
                identity["strategy_version"] = version.version
                definition = self.library.get(version.strategy_definition_id)
                identity["strategy_definition_id"] = definition.id
                identity["strategy_name"] = definition.name
            except DatasetError:
                pass
        return identity

    def _row(self, run, role, label) -> dict[str, object]:
        metrics = _run_metrics(self.runs, self.reader, run)
        return {
            "run_id": run.backtest_run_id,
            "role": role,
            "label": label,
            "status": run.status,
            "start_date": run.start_date.isoformat(),
            "end_date": run.end_date.isoformat(),
            "initial_cash": _decimal_text(run.initial_cash),
            "final_equity": metrics.get("final_equity"),
            "total_return": metrics.get("total_return"),
            "annualized_return": metrics.get("annualized_return"),
            "annualized_volatility": metrics.get("annualized_volatility"),
            "sharpe_ratio": metrics.get("sharpe_ratio"),
            "max_drawdown": metrics.get("max_drawdown"),
            "trade_count": metrics.get("trade_count"),
            "order_count": metrics.get("order_count"),
            "total_fees": metrics.get("total_fees"),
            **self._strategy_identity(run),
        }

    def compare(self, experiment, links, runs) -> dict[str, object]:
        baseline_link = next(
            (link for link in links if link.role == RunRole.BASELINE.value), None
        )
        baseline = (
            next((r for r in runs if r.backtest_run_id == baseline_link.backtest_run_id), None)
            if baseline_link
            else None
        )
        rows: list[dict[str, object]] = []
        for link in links:
            run = next((r for r in runs if r.backtest_run_id == link.backtest_run_id), None)
            if run is None:
                continue
            row = self._row(run, link.role, link.label)
            if baseline is not None and run.backtest_run_id != baseline.backtest_run_id:
                row["comparability"] = self.comparability.compute(baseline, run)
                row["deltas"] = self._deltas(baseline, run)
            rows.append(row)
        ranking_allowed = baseline is not None and all(
            _comparability_status(row) == ComparabilityStatus.STRICTLY_COMPARABLE.value
            for row in rows
            if row.get("comparability") is not None
        )
        return {
            "experiment_id": experiment.id,
            "baseline_run_id": baseline.backtest_run_id if baseline else None,
            "ranking_allowed": ranking_allowed,
            "runs": rows,
        }

    def _deltas(self, baseline, run) -> dict[str, object]:
        base_metrics = _run_metrics(self.runs, self.reader, baseline)
        run_metrics = _run_metrics(self.runs, self.reader, run)
        return {
            "final_equity_delta": _delta(base_metrics, run_metrics, "final_equity"),
            "total_return_delta": _delta(base_metrics, run_metrics, "total_return"),
            "annualized_return_delta": _delta(base_metrics, run_metrics, "annualized_return"),
            "sharpe_delta": _delta(base_metrics, run_metrics, "sharpe_ratio"),
            "max_drawdown_delta": _delta(base_metrics, run_metrics, "max_drawdown"),
            "total_fees_delta": _delta(base_metrics, run_metrics, "total_fees"),
            "trade_count_delta": _delta(base_metrics, run_metrics, "trade_count"),
        }


def _comparability_status(row: dict[str, object]) -> object:
    comparison = row.get("comparability")
    if not isinstance(comparison, dict):
        return None
    return comparison.get("status")


def _delta(base: dict, candidate: dict, key: str) -> object | None:
    if key not in base or key not in candidate:
        return None
    b = base[key]
    c = candidate[key]
    if b is None or c is None:
        return None
    try:
        return _decimal_text(Decimal(str(c)) - Decimal(str(b)))
    except Exception:
        return None
